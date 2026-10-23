from studio_attachments import DOCUMENTS as TEXT_FORMATS
"""Small loopback-only creation UI; uses the existing managed engine without ComfyUI."""
import traceback
from studio_diagnostics import LOG
import json, os, secrets, subprocess, threading, time, uuid, sys, shutil, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
DATA = ROOT / 'studio-data'
sys.path.insert(0,str(ROOT/'FreeVideo'))
IMAGE_JOBS = DATA / 'image-jobs'
VOICE_DATA = DATA / 'voices'
UPLOADS = DATA / 'uploads'
JOBS = DATA / 'jobs'
PORT = 57846
TOKEN = secrets.token_urlsafe(32)
IMAGE = {'.png', '.jpg', '.jpeg', '.webp'}
VIDEO = {'.mp4', '.mov', '.webm', '.mkv'}
QUALITY = {'light': ['--two-pass', '--base-steps', '8', '--refine-steps', '3'],
           'high': ['--no-two-pass', '--base-steps', '16']}
SIZES = {'source': (640,576), 'portrait': (512,768), 'landscape': (768,512)}
FFMPEG = PROJECT/'media-runtime/ffmpeg/ffmpeg.exe'

_workspace_directory=ContextVar('workspace_directory',default=None)
@contextmanager
def workspace_scope(directory):
    token=_workspace_directory.set(directory)
    try:yield
    finally:_workspace_directory.reset(token)
def jobs_root():return Path(_workspace_directory.get())/'jobs' if _workspace_directory.get() else JOBS
def uploads_root():return Path(_workspace_directory.get())/'uploads' if _workspace_directory.get() else UPLOADS
def image_jobs_root():return Path(_workspace_directory.get())/'image-jobs' if _workspace_directory.get() else IMAGE_JOBS
def voice_data_root():return Path(_workspace_directory.get())/'voices' if _workspace_directory.get() else VOICE_DATA
def scoped_method(fn):
    @wraps(fn)
    def run(self,*args,**kwargs):
        with workspace_scope(self.directory):return fn(self,*args,**kwargs)
    return run

def completed_job(identifier):
    if not isinstance(identifier,str) or not identifier or Path(identifier).name != identifier:
        raise ValueError('Invalid source video')
    folder=(jobs_root()/identifier).resolve()
    if not folder.is_relative_to(jobs_root().resolve()):
        raise ValueError('Invalid source video')
    try:
        row=json.loads((folder/'job.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):
        raise ValueError('Source video not found')
    if row.get('status')!='completed' or row.get('hidden') or not (folder/'video.mp4').is_file():
        raise ValueError('Choose a completed video to continue')
    return folder,row

def run_media(args):
    result=subprocess.run([str(FFMPEG),'-hide_banner','-loglevel','error','-nostdin',*args],
                          capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError('Could not process video: '+result.stderr.decode('utf-8',errors='replace')[-1500:])

def last_frame(source, target):
    # Decode the tail, not a whole growing chain into the reverse buffer.
    run_media(['-y','-threads','2','-sseof','-3','-i',str(source),'-map','0:v:0','-an',
               '-vf','reverse','-frames:v','1','-threads','2',str(target)])
    if not target.is_file():
        raise ValueError('Could not extract the last frame')

def silent_video_output(source):
    """Remove generated audio before publication, without re-encoding video."""
    target=source.with_name('silent-output.mp4')
    try:
        run_media(['-y','-i',str(source),'-map','0:v:0','-c:v','copy','-an','-movflags','+faststart',str(target)])
        if not target.is_file():raise ValueError('Silent video output was not created')
        os.replace(target,source)
    finally:target.unlink(missing_ok=True)

def join_continuation(folder, parent):
    source,record=completed_job(parent)
    previous=source/'combined.mp4' if record.get('combined',not bool(record.get('message'))) and (source/'combined.mp4').is_file() else source/'video.mp4'
    listing=folder/'join.txt'
    listing.write_text(''.join("file '"+str(p).replace('\\','/').replace("'","'\\''")+"'\n" for p in [previous,folder/'video.mp4']),encoding='utf-8')
    run_media(['-y','-f','concat','-safe','0','-i',str(listing),'-map','0','-c','copy',
               '-movflags','+faststart',str(folder/'combined.mp4')])

def join_clips(paths, output):
    # Normalize arbitrary clips: equal dimensions/FPS and silence only for
    # missing audio. Originals are preserved, never stream-copy
    # incompatible videos and hope the result plays.
    normalized=[]
    from PIL import Image
    probe=output.parent/'geometry.png';last_frame(paths[0],probe)
    with Image.open(probe) as image:width,height=image.size
    width+=width%2;height+=height%2
    try:
        for index,path in enumerate(paths):
            target=output.parent/f'join-part-{index}.mp4'
            probe_audio=subprocess.run([str(FFMPEG),'-hide_banner','-i',str(path)],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            audio='0:a:0' if b'Audio:' in probe_audio.stderr else '1:a:0'
            run_media(['-y','-threads','2','-i',str(path),'-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
                       '-map','0:v:0','-map',audio,'-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24',
                       '-c:v','libx264','-crf','18','-preset','fast','-threads','2','-c:a','aac','-ar','48000','-ac','2','-af','apad','-shortest',str(target)])
            normalized.append(target)
        listing=output.parent/'join.txt'
        listing.write_text(''.join("file '"+str(p).replace('\\','/').replace("'","'\\''")+"'\n" for p in normalized),encoding='utf-8')
        run_media(['-y','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(output)])
    finally:
        for path in normalized:path.unlink(missing_ok=True)
        probe.unlink(missing_ok=True)
    return [width,height]

def video_seconds(path):
    probe=subprocess.run([str(FFMPEG),'-hide_banner','-i',str(path)],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    match=re.search(rb'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)',probe.stderr)
    return round(int(match[1])*3600+int(match[2])*60+float(match[3]),2) if match else 0

def write_json(path, value):
    from studio_files import atomic_json
    return atomic_json(path,value)

def asset(value, kind):
    if not value:
        return None
    if value in ('lexi','canonical') and kind=='image' and _workspace_directory.get():
        owned=uploads_root()/('legacy-reference-'+value+'.png')
        if owned.exists():value=owned.name
    if value == 'lexi' and kind == 'image':
        return PROJECT / 'Lexi-stills/Lexi.png'
    if value == 'canonical' and kind == 'image':
        return PROJECT/'references/canonical/Lexi-approved-2026-10-15.png'
    if not isinstance(value, str) or Path(value).name != value:
        raise ValueError('Invalid uploaded reference')
    directory=_workspace_directory.get()
    if directory and (Path(directory)/'workspace.json').is_file():
        document=json.loads((Path(directory)/'workspace.json').read_text(encoding='utf-8'))
        for candidate in document['assets'].values():
            if candidate.get('trashed') and value in (candidate['metadata'].get('legacy_name'),candidate['metadata'].get('legacy_alias'),candidate['id']+Path(candidate['path']).suffix):raise ValueError('Reference is in workspace trash; restore it first')
    path = (uploads_root() / value).resolve()
    if not path.is_relative_to(uploads_root().resolve()) or path.suffix.lower() not in (IMAGE if kind == 'image' else VIDEO) or not path.is_file():
        raise ValueError('Reference not found')
    return path

def prepare(options, folder):
    prompt = options.get('prompt', '').strip()
    if not prompt or len(prompt) > 16000:
        raise ValueError('Enter a prompt of up to 16,000 characters')
    quality = options.get('quality', 'high')
    size = options.get('size', 'source')
    if quality not in QUALITY or size not in SIZES:
        raise ValueError('Invalid quality or framing')
    seconds = int(options.get('seconds', 5))
    if seconds not in (3,5,8,10,15,30):
        raise ValueError('Choose 3, 5, 8, 10, 15 or 30 seconds')
    seed_text = str(options.get('seed', '')).strip()
    seed = int(seed_text) if seed_text else secrets.randbelow(2147483647)
    if not 0 <= seed <= 2147483647:
        raise ValueError('Seed must be between 0 and 2147483647')
    parent=options.get('continue_from')
    previous={}
    if parent:
        source,previous=completed_job(parent)
        if options.get('image') or options.get('video'):
            raise ValueError('A continuation uses the source last frame; clear other references first')
        size=previous['settings']['size']
    audio_mode=options.get('audio_mode',previous.get('settings',{}).get('audio_mode','generated'))
    if audio_mode not in ('silent','generated'):raise ValueError('Choose Silent or Generated sound')
    image, video = asset(options.get('image'), 'image'), asset(options.get('video'), 'video')
    appearance=options.get('appearance',previous.get('settings',{}).get('appearance',''))
    if not isinstance(appearance,str) or len(appearance)>2000:raise ValueError('Appearance description limit is 2,000 characters')
    identity_id=options.get('identity_image') if 'identity_image' in options else previous.get('settings',{}).get('identity_image') or previous.get('settings',{}).get('image')
    if not parent and not identity_id:identity_id=options.get('image')
    identity=asset(identity_id,'image')
    identity_mode=options.get('identity_mode',previous.get('settings',{}).get('identity_mode',False))
    if type(identity_mode) is not bool:raise ValueError('Invalid identity mode')
    if identity_mode and not identity:raise ValueError('Select an identity image before enabling reference guidance')
    folder.mkdir(parents=True,exist_ok=True)
    if parent:
        image=folder/'last-frame.png'
        last_frame(source/'video.mp4',image)
    frames = max(39, 5 + 17 * ((seconds * 24 - 5 + 16) // 17))
    width, height = SIZES[size]
    media = {'version': 1}
    character_guidance=options.get('character_guidance',[])
    if character_guidance:
        if not isinstance(character_guidance,list) or len(character_guidance)>30:raise ValueError('Too many character reference descriptions')
        media['references']=([{'path':str(image),'kind':'image'}] if image else [])
        labels=[]
        for ref in character_guidance:
            path=asset(ref['image'],'image')
            if not any(r['path']==str(path) for r in media['references']):media['references'].append({'path':str(path),'kind':'image'})
            index=next(i for i,r in enumerate(media['references'],1) if r['path']==str(path));labels.append('Reference '+str(index)+' for '+ref['character']+'. Guidance: '+__import__('studio_characters').reference_description(ref)+'.')
        if identity_mode and identity and not any(r['path']==str(identity) for r in media['references']):
            media['references'].append({'path':str(identity),'kind':'image'});labels.append('Reference '+str(len(media['references']))+' is the additional explicit identity reference.')
        if len(media['references'])>4:raise ValueError('Combined starting frame and identity references exceed four images')
        if video:media['references'].append({'path':str(video),'kind':'video'})
        prompt+='\n'+' '.join(labels);task='ref2va'
    elif identity_mode and identity:
        media['references']=([{'path':str(image),'kind':'image'}] if image else [])+[{'path':str(identity),'kind':'image'}]+([{'path':str(video),'kind':'video'}] if video else [])
        task='ref2va'
    elif video:
        media['references'] = ([{'path': str(image), 'kind': 'image'}] if image else []) + [{'path': str(video), 'kind': 'video'}]
        task = 'ref2va'
    elif image:
        media['first'] = str(image)
        task = 'i2va'
    else:
        task = 't2va'
    # Human prompt remains intact; the model's required wrapper is added locally.
    native_audio=any(r.get('speech',{}).get('mode')=='native' for r in (options.get('scene_snapshot') or {}).get('roles',[]))
    wrapped = 'integrated_multimodal_description: [Shot 1] ' + prompt.replace('\r', '').replace('\n', ' ') + ('\noverall_soundscape: Character speech and scene audio as directed above.\nnon_diegetic_music: None.\n' if native_audio else '\noverall_soundscape: Quiet ambience, no dialogue.\nnon_diegetic_music: None.\n')
    continuity=''
    if appearance:continuity='Character continuity: '+appearance.replace('\n',' ')+' Keep the same facial identity, body proportions, muscle definition, hairstyle, clothing and art style throughout. Do not redesign or normalize the character. '
    if identity_mode and image and not character_guidance:continuity+='Use reference image 1 for the starting pose and scene and reference image 2 for the fixed character identity and proportions. '
    wrapped=wrapped.replace('[Shot 1] ','[Shot 1] '+continuity,1)
    action=options.get('user_prompt')
    if isinstance(action,str) and action and len(action)<=2000:
        action=action.replace('\r','').replace('\n',' ')
        wrapped=wrapped.replace('[Shot 1] ','[Shot 1] Primary scene/action: '+action+'. Show this action visibly. Reference images and character descriptions guide appearance; their poses and body language must not replace the requested action. ',1)
        wrapped=wrapped.replace('\noverall_soundscape:', ' Main action throughout this shot: '+action+'.\noverall_soundscape:',1)
    (folder/'prompt.txt').write_text(wrapped, encoding='utf-8')
    write_json(folder/'media.json', media)
    command = [str(ROOT/'runtime/envs/unified/Scripts/python.exe'), '-B', '-u', '-m', 'freevideo_engine.managed',
               '--root', str(ROOT/'runtime'), 'generate', '--prompt-file', str(folder/'prompt.txt'),
               '--task', task, '--width', str(width), '--height', str(height), '--frames', str(frames),
               '--seed', str(seed), *QUALITY[quality], '--out', str(folder/'video.mp4')]
    if image or video or identity_mode or character_guidance:
        command += ['--media', str(folder/'media.json')]
    return command, dict(prompt=prompt, quality=quality, size=size, seed=seed, frames=frames,
                         seconds=round(frames/24,2), resolution=[width,height], task=task,
                         image=options.get('image'), video=options.get('video'),continue_from=parent,
                         appearance=appearance,identity_image=identity_id,identity_mode=identity_mode,audio_mode=audio_mode,context_snapshot=options.get('context_snapshot'),workspace_id=options.get('workspace_id'),user_prompt=options.get('user_prompt'),model_spec=options.get('model_spec'),character_snapshot=options.get('character_snapshot'),character_guidance=character_guidance,scene_snapshot=options.get('scene_snapshot'))

def tail(path, limit=120000):
    if not path.is_file():
        return ''
    with path.open('rb') as file:
        file.seek(max(0,path.stat().st_size-limit))
        return file.read().decode('utf-8', errors='replace')

def phase(folder):
    event = None
    logs=[folder/name for name in ('video.engine.log','video.encoding.log','render.log') if (folder/name).is_file()]
    for name in sorted(logs,key=lambda path:path.stat().st_mtime,reverse=True):
        for line in reversed(tail(folder/name).splitlines()):
            try:
                row=json.loads(line)
                if row.get('event') in ('sampling_progress','sampling_start','step','decode_progress','decode_phase','model_load_phase','prepared_blocks','encoder_phase','encoding_start','video_start'):
                    event=row
                    break
            except (ValueError, AttributeError):
                pass
        if event:
            break
    if not event:
        return 'Starting local engine', None
    name=event['event']
    if name in ('sampling_progress','sampling_start','step'):
        done=event.get('completed_steps',0)
        return f'Sampling: {done} / {event.get("total",16)} steps', round(100*done/event.get('total',16))
    if name=='decode_progress':
        return f'Decoding: {event["done"]} / {event["total"]} frames', None
    if name=='encoder_phase':
        return 'Encoding reference and prompt: '+event.get('stage','').replace('_',' '), None
    return event.get('phase', 'Loading video model' if name in ('video_start','prepared_blocks') else 'Encoding reference and prompt'), None

class Studio:
    def __init__(self,directory=None,shared_profiles=None):
        self.directory=directory;self.shared_profiles=shared_profiles
        with workspace_scope(directory):self._initialize()
    def _initialize(self):
        uploads_root().mkdir(parents=True,exist_ok=True)
        jobs_root().mkdir(parents=True,exist_ok=True)
        image_jobs_root().mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        from studio_chat import StudioChat
        self.chat=StudioChat(Path(self.directory)/'conversations/chat.json' if self.directory else None)
        self.process=None
        self.current=None
        self.image_current=None
        self.image_service=None
        self.image_states={}
        from voice_studio import VoiceStudio
        self.voice=VoiceStudio(voice_data_root(),profiles=self.shared_profiles,busy=lambda:bool(self.current or self.image_current),release=lambda:self.image_service.stop_for_generation() if self.image_service else None)
        for path in jobs_root().glob('*/job.json'):
            try:
                row=json.loads(path.read_text(encoding='utf-8'))
                if row['status'] in ('running','cancelling','pausing'):
                    row.update(status='interrupted', message='Launcher stopped before this job finished.')
                    write_json(path,row)
            except (ValueError,KeyError):
                pass
        for path in image_jobs_root().glob('*/job.json'):
            try:
                row=json.loads(path.read_text(encoding='utf-8'))
                if row['status']=='running':
                    row.update(status='interrupted',message='Studio stopped before this image finished.')
                    write_json(path,row)
            except (ValueError,KeyError):pass

    def images(self):
        rows=[]
        for path in sorted(image_jobs_root().glob('*/job.json'),reverse=True)[:50]:
            try:
                row=json.loads(path.read_text(encoding='utf-8'))
                if not row.get('hidden'):rows.append(self.image_states.get(row['id'],row) if self.image_states.get(row['id'],{}).get('persistence_error') else row)
            except (OSError,ValueError):pass
        return rows

    def export_frame(self,identifier):
        with self.lock:
            if self.current or self.image_current or self.voice.current:raise ValueError('Wait for the current generation before extracting a frame.')
            folder,_=completed_job(identifier)
            name=uuid.uuid4().hex+'.png';last_frame(folder/'video.mp4',uploads_root()/name)
            return dict(image=name)

    def attach(self,options):
        with self.lock:
            if self.current or self.image_current or self.voice.current:raise ValueError('Wait for the current job before joining videos.')
            clips=options.get('clips')
            if not isinstance(clips,list) or not 2<=len(clips)<=32:raise ValueError('Choose between two and 32 videos in playback order.')
            paths=[];settings=None
            for clip in clips:
                if not isinstance(clip,dict):raise ValueError('Invalid video selection')
                if clip.get('kind')=='job':
                    source,row=completed_job(clip.get('id'))
                    paths.append(source/'combined.mp4' if clip.get('chain') and (source/'combined.mp4').is_file() else source/'video.mp4')
                    if settings is None:settings=dict(row.get('settings',{}))
                elif clip.get('kind')=='upload':
                    path=asset(clip.get('id'),'video')
                    if not path:raise ValueError('Select a video file')
                    paths.append(path)
                else:raise ValueError('Invalid video selection')
            identifier=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
            folder=jobs_root()/identifier;folder.mkdir(parents=True)
            settings=dict(settings or {})
            settings.pop('imported_asset',None)
            settings.update(prompt='Manually joined video',quality='joined',seconds=0,resolution=[0,0],size=settings.get('size','source'),seed=settings.get('seed',0),joined_from=clips,continue_from=None)
            row=dict(id=identifier,status='running',started=time.time(),settings=settings,phase='Joining clips locally')
            write_json(folder/'job.json',row);self.current=identifier
            threading.Thread(target=self.finish_attach,args=(folder,row,paths),daemon=True).start()
            return row

    def finish_attach(self,folder,row,paths):
        try:
            row['settings']['resolution']=join_clips(paths,folder/'video.mp4')
            row['settings']['seconds']=video_seconds(folder/'video.mp4')
            try:os.link(folder/'video.mp4',folder/'combined.mp4')
            except OSError:shutil.copyfile(folder/'video.mp4',folder/'combined.mp4')
            row.update(status='completed',combined=True)
        except Exception as exc:row.update(status='failed',message=str(exc))
        finally:
            row['elapsed']=row.get('elapsed_base',0)+round(time.time()-row['started']);row.pop('phase',None)
            write_json(folder/'job.json',row)
            with self.lock:self.current=None

    def image_info(self):
        from freevideo_engine.image_gen import image_pack
        machine=json.loads((ROOT/'runtime/machine.json').read_text(encoding='utf-8'))
        status={}
        try:status=json.loads((DATA/'image-install.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        return dict(ready=image_pack.ready(machine['model_root']),model=image_pack.catalog()['repo'],install=status)

    def start_image(self, options):
        with self.lock:
            if self.current or self.image_current or self.voice.current:raise ValueError('Wait for the current image or video to finish first.')
            resuming=options.get('_resume',False)
            previous=json.loads((image_jobs_root()/options['_queued_id']/'job.json').read_text(encoding='utf-8')) if resuming else {}
            if resuming:options=dict(previous['settings'],_queued_id=options['_queued_id'],_resume=True)
            references=options.get('images',[])
            if not isinstance(references,list) or len(references)>4:raise ValueError('Choose up to four reference images, in order A–D.')
            for reference in references:asset(reference,'image')
            if not self.image_info()['ready']:raise ValueError('Image model is still downloading or needs repair.')
            from freevideo_engine.image_gen.service import Service
            if self.image_service is None:
                machine=json.loads((ROOT/'runtime/machine.json').read_text(encoding='utf-8'))
                upload_directory=uploads_root().resolve()
                self.image_service=Service(lambda:(ROOT/'runtime',machine),lambda:str(upload_directory),video_busy=lambda:bool(self.current),idle_seconds=30)
            value=dict(prompt=options.get('prompt'),width=options.get('width',768),height=options.get('height',768),images=references,seed=options.get('seed') if options.get('seed') is not None else secrets.randbelow(2147483647))
            identifier=options.get('_queued_id') or time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
            folder=image_jobs_root()/identifier;folder.mkdir(parents=True,exist_ok=True)
            row=dict(id=identifier,status='running',checkpoint_capable=True,elapsed_base=previous.get('elapsed',0) if resuming else 0,started=time.time(),settings=dict(value,context_snapshot=options.get('context_snapshot'),workspace_id=options.get('workspace_id'),user_prompt=options.get('user_prompt'),model_spec=options.get('model_spec'),character_snapshot=options.get('character_snapshot')))
            # Establish writable durable metadata before launching any GPU work.
            write_json(folder/'job.json',row)
            checkpoint=folder/'checkpoint';checkpoint.mkdir(exist_ok=True);(checkpoint/'pause.request').unlink(missing_ok=True)
            try:started=self.image_service.start('generate',value,checkpoint_directory=checkpoint)
            except Exception as exc:
                row.update(status='failed',message=str(exc));write_json(folder/'job.json',row);raise
            self.image_current=identifier;self.image_states[identifier]=row
            LOG.record('info','image','Image generation started',options.get('workspace_id'),identifier)
            threading.Thread(target=self.finish_image,args=(folder,row,started['job']),daemon=True).start()
            return row

    def finish_image(self,folder,row,key):
        last_phase=None
        try:
            while True:
                state=self.image_service.status(key)
                row.update(phase=state.get('stage',state.get('phase')),progress=state.get('fraction'),elapsed=row.get('elapsed_base',0)+round(time.time()-row['started']))
                if row.get('phase')!=last_phase:
                    last_phase=row.get('phase');LOG.record('info','image','Image stage: '+str(last_phase),row['settings'].get('workspace_id'),row['id'])
                if state['phase']=='paused':
                    self.image_service.stop_for_generation()
                    from freevideo_engine.studio_checkpoint import ready
                    if not ready(folder/'checkpoint'):raise ValueError('Image worker exited without a valid checkpoint')
                    row.update(status='paused',phase='Paused · GPU released',message='Saved image sampling step');break
                if (folder/'checkpoint/pause.request').is_file():row.update(status='pausing',phase='Pausing at next image step')
                if state['phase']=='complete':
                    source=(uploads_root()/state['file']).resolve()
                    if not source.is_relative_to(uploads_root().resolve()):raise ValueError('Invalid result path')
                    name=uuid.uuid4().hex+'.png';shutil.copyfile(source,uploads_root()/name)
                    row.update(status='completed',image=name);break
                if state['phase'] in ('failed','cancelled'):
                    row.update(status=state['phase'],message=state.get('error','Image cancelled'));break
                try:write_json(folder/'job.json',row)
                except PermissionError as exc:LOG.record('warning','image','Progress-file update delayed by Windows',row['settings'].get('workspace_id'),row['id'],str(exc))
                time.sleep(.4)
        except Exception as exc:
            row.update(status='failed',message=str(exc))
            if self.image_service and self.image_service.busy():
                try:self.image_service.cancel(key);self.image_service.stop_for_generation()
                except Exception as stop_error:LOG.record('error','image','Could not stop failed image worker',row['settings'].get('workspace_id'),row['id'],str(stop_error))
        finally:
            LOG.record('error' if row.get('status')=='failed' else 'info','image','Image generation '+row.get('status','stopped'),row['settings'].get('workspace_id'),row['id'],row.get('message'))
            try:write_json(folder/'job.json',row)
            except OSError as exc:
                row['persistence_error']=str(exc);LOG.record('error','image','Could not save final image-job status',row['settings'].get('workspace_id'),row['id'],str(exc))
            finally:
                with self.lock:self.image_current=None

    def cancel_image(self):
        if self.image_current and self.image_service:self.image_service.cancel(self.image_service.key)

    def history(self):
        rows=[]
        for path in sorted(jobs_root().glob('*/job.json'),reverse=True)[:50]:
            try:
                row=json.loads(path.read_text(encoding='utf-8'))
                if row['status'] in ('running','cancelling','pausing'):
                    row['elapsed']=row.get('elapsed_base',0)+round(time.time()-row['started'])
                    if not row.get('phase'):row['phase'],row['progress']=phase(path.parent)
                if row.get('status')=='completed' and not (path.parent/'video.mp4').is_file():continue
                if row.get('hidden'):continue
                rows.append(row)
            except ValueError:
                pass
        return rows

    def start(self, options):
        with self.lock:
            if self.current or self.image_current or self.voice.current:
                raise ValueError('A generation is already running. Wait or cancel it first.')
            if self.image_service:self.image_service.stop_for_generation()
            identifier=options.get('_queued_id') or time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
            folder=jobs_root()/identifier
            resuming=options.get('_resume',False);previous={}
            if resuming:
                previous=json.loads((folder/'job.json').read_text(encoding='utf-8'));settings=previous['settings']
                command=[str(ROOT/'runtime/envs/unified/Scripts/python.exe'),'-B','-u',str(ROOT/'studio_video_resume.py'),str(folder/'checkpoint')]
            else:command,settings=prepare(options,folder)
            checkpoint=folder/'checkpoint';checkpoint.mkdir(exist_ok=True);(checkpoint/'pause.request').unlink(missing_ok=True)
            row=dict(id=identifier,status='running',checkpoint_capable=True,elapsed_base=previous.get('elapsed',0),started=time.time(),settings=settings)
            write_json(folder/'job.json',row)
            self.current=identifier
            try:
                out=(folder/'render.log').open('a' if resuming else 'w',encoding='utf-8')
                err=(folder/'error.log').open('w',encoding='utf-8')
                self.process=subprocess.Popen(command,cwd=ROOT,stdout=out,stderr=err,env=dict(os.environ,STUDIO_CHECKPOINT_DIR=str(checkpoint)),creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception as exc:
                row.update(status='failed',message=str(exc))
                write_json(folder/'job.json',row)
                self.current=None
                raise
            finally:
                if 'out' in locals(): out.close()
                if 'err' in locals(): err.close()
            threading.Thread(target=self.finish,args=(folder,row,self.process),daemon=True).start()
            return row

    def finish(self,folder,row,process):
        code=process.wait()
        with self.lock:
            previous=json.loads((folder/'job.json').read_text(encoding='utf-8'))
            cancelled=previous['status']=='cancelling'
            from freevideo_engine.studio_checkpoint import ready
            paused=not cancelled and (folder/'checkpoint/pause.request').exists() and ready(folder/'checkpoint',fresh=True) and not (code==0 and (folder/'video.mp4').is_file())
            row.update(status='cancelled' if cancelled else 'paused' if paused else 'completed' if code==0 and (folder/'video.mp4').is_file() else 'failed',
                       elapsed=row.get('elapsed_base',0)+round(time.time()-row['started']),exit_code=code)
            if paused:row.update(phase='Paused · GPU released',message='Saved video stage; sampling completes before pausing')
            if row['status']=='failed':
                row['message']=tail(folder/'error.log',5000) or tail(folder/'render.log',5000) or 'Engine exited without a video.'
            if row['status']=='completed' and row.get('settings',{}).get('audio_mode')=='silent':
                try:silent_video_output(folder/'video.mp4')
                except (ValueError,OSError,subprocess.TimeoutExpired) as exc:row.update(status='failed',message='Video rendered, but silent output could not be finalized: '+str(exc))
            if row['status']=='completed' and row.get('settings',{}).get('continue_from'):
                try:
                    join_continuation(folder,row['settings']['continue_from'])
                    row['combined']=True
                except (ValueError,OSError,subprocess.TimeoutExpired) as exc:
                    row['message']='New segment is ready, but joining failed: '+str(exc)
            write_json(folder/'job.json',row)
            self.current=None
            self.process=None

    def cancel(self):
        with self.lock:
            if not self.current or not self.process or self.process.poll() is not None:
                return
            folder=jobs_root()/self.current
            row=json.loads((folder/'job.json').read_text(encoding='utf-8'))
            # Only the process created by this server and its descendants are targeted.
            result=subprocess.run(['taskkill.exe','/PID',str(self.process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode and self.process.poll() is None:
                raise ValueError('Could not stop the render; check the local logs.')
            row['status']='cancelling'
            write_json(folder/'job.json',row)

# Worker threads re-enter their owning workspace, independent of request/UI selection.
for _name,_method in list(Studio.__dict__.items()):
    if callable(_method) and _name not in ('__init__','_initialize'):setattr(Studio,_name,scoped_method(_method))

class Handler(BaseHTTPRequestHandler):
    @property
    def studio(self):
        hub=getattr(self.server,'hub',None)
        if not hub:return self.server.studio
        from urllib.parse import parse_qs
        workspace=self.headers.get('X-Studio-Workspace') or parse_qs(urlparse(self.path).query).get('workspace',['free-work'])[0]
        return hub.studio(workspace)

    def handle(self):
        # Browsers routinely abandon an MP4 range when seeking or reloading.
        try:
            super().handle()
        except (ConnectionError, TimeoutError):
            pass

    def setup(self):
        super().setup()
        self.connection.settimeout(120)

    def log_message(self,*args):
        pass

    def valid_host(self):
        return self.headers.get('Host')==f'127.0.0.1:{PORT}'

    def json(self,value,status=200):
        if status>=400 and isinstance(value,dict) and value.get('error'):
            route=urlparse(self.path).path
            component='image' if '/image/' in route else 'voice' if '/voice/' in route else 'chat' if '/chat/' in route else 'http'
            details=traceback.format_exc() if sys.exc_info()[0] else None
            value=dict(value,error_id=LOG.record('error',component,value['error'],self.headers.get('X-Studio-Workspace','free-work'),details=details))
        if status==202 and isinstance(value,dict) and value.get('id'):
            LOG.record('info','http','Creation request accepted',self.headers.get('X-Studio-Workspace','free-work'),value['id'])
        data=json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            with workspace_scope(self.studio.directory):return self.workspace_GET()
        except (ValueError,OSError) as exc:return self.json({'error':str(exc)},400)
        except Exception:return self.json({'error':'Unexpected application error. Open Settings → Activity & logs.'},500)
    def workspace_GET(self):
        if not self.valid_host():
            return self.json({'error':'Invalid host'},403)
        path=urlparse(self.path).path
        if path in ('/studio-scene.js','/studio-scene.css','/studio-characters.js','/studio-queue.js','/studio-images.js','/studio-video-tools.js','/studio-voice.js','/studio-chat.js','/studio-settings-view.js','/studio-settings-view.css','/studio-instructions.js','/studio-chat-layout.js','/studio-chat-layout.css','/studio-work-models.js','/studio-admin.js','/studio-projects.js','/studio-tree.js','/studio-chat-cards.js','/studio-diagnostics.js'):
            data=(ROOT/path[1:]).read_bytes();self.send_response(200);self.send_header('Content-Type','text/css; charset=utf-8' if path.endswith('.css') else 'text/javascript; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();return self.wfile.write(data)
        if path=='/api/logs':
            return self.json(LOG.view(getattr(self.server,'hub',None).store if getattr(self.server,'hub',None) else None,parse_qs(urlparse(self.path).query).get('source',['events'])[0]))
        if path=='/api/job/status':
            kind=parse_qs(urlparse(self.path).query).get('kind',[''])[0];id=parse_qs(urlparse(self.path).query).get('id',[''])[0]
            if not re.fullmatch(r'[0-9a-f]{32}|[0-9]{8}-[0-9]{6}-[0-9a-f]{8}',id):raise ValueError('Invalid job ID')
            root={'image':image_jobs_root(),'video':jobs_root(),'voice':self.studio.voice.jobs}.get(kind)
            if root is None:raise ValueError('Invalid job kind')
            cached=getattr(self.studio,'image_states',{}).get(id) if kind=='image' else None
            return self.json(cached if cached and cached.get('persistence_error') else json.loads((root/id/'job.json').read_text(encoding='utf-8')))
        if path=='/api/characters':return self.json({'characters':list(self.server.hub.store.get(self.studio.workspace_id).get('characters',{}).values())})
        if path=='/api/tree':
            hub=self.server.hub
            return self.json(hub.tree_state())
        if path=='/api/settings/instructions':
            return self.json(self.server.hub.instructions.state(self.studio.workspace_id))
        if path=='/api/chat/runtime':
            from studio_chat import StudioChat
            return self.json(StudioChat.runtime_state())
        if path=='/api/queue':return self.json(self.server.hub.queue.state())
        if path=='/api/chat/state':
            hub=self.server.hub;id=self.headers.get('X-Studio-Chat')
            return self.json({'chat':hub.conversations.instance(self.studio.workspace_id,id).state() if id else {'messages':[],'busy':False},'active':hub.active()})
        if path=='/api/settings':return self.json(self.server.hub.models.info())
        if path.startswith('/project-export/'):
            hub=getattr(self.server,'hub',None);name=path.split('/')[-1]
            from workspace_store import identifier
            identifier(Path(name).stem)
            if not hub or Path(name).suffix!='.zip' or Path(name).name!=name:raise ValueError('Invalid project export')
            return self.send_file(hub.portable.exports/name,'application/zip')
        if path.startswith('/asset/'):
            hub=getattr(self.server,'hub',None)
            if not hub:return self.json({'error':'Projects unavailable'},404)
            w=self.studio.workspace_id
            if hub.store.get(w).get('archive_reclaimed'):
                from workspace_archive import restore_assets
                restore_assets(hub.store,hub.portable.exports,w,path.split('/')[-1])
            row,file=hub.store.asset(w,path.split('/')[-1])
            import mimetypes
            return self.send_file(file,mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
        if path=='/api/state':
            hub=getattr(self.server,'hub',None)
            extra=hub.workspace_state(self.headers.get('X-Studio-Workspace') or self.studio.workspace_id) if hub else {}
            return self.json({'jobs':self.studio.history(),'images':self.studio.images(),'image_model':self.studio.image_info(),'voices':self.studio.voice.state(),'active':self.studio.current or self.studio.image_current or self.studio.voice.current or (hub.active()['id'] if hub and hub.active() else None),'video_active':self.studio.current,'image_active':self.studio.image_current,'chat':(hub.conversations.instance(self.studio.workspace_id,self.headers.get('X-Studio-Chat')).state() if hub and self.headers.get('X-Studio-Chat') else self.studio.chat.state()),'version':52,**extra})
        if path.startswith('/audio/') or path.startswith('/audio-chain/') or path.startswith('/voice-reference/'):
            parts=path.split('/')
            try:file=self.studio.voice.file('profiles',parts[2],'reference.wav') if path.startswith('/voice-reference/') and len(parts)==3 else self.studio.voice.file('jobs',parts[2],'combined.wav' if path.startswith('/audio-chain/') else 'audio.wav') if len(parts)==3 else None
            except ValueError:return self.json({'error':'Audio not found'},404)
            if file is None:return self.json({'error':'Audio not found'},404)
            length=file.stat().st_size;start,end=0,length-1;ranged=self.headers.get('Range')
            if ranged:
                try:
                    values=ranged.removeprefix('bytes=').split('-');start=int(values[0]);end=min(int(values[1]) if values[1] else end,end)
                    if not 0<=start<=end:raise ValueError()
                except (ValueError,IndexError):
                    self.send_response(416);self.send_header('Content-Range',f'bytes */{length}');self.end_headers();return
            self.send_response(206 if ranged else 200);self.send_header('Content-Type','audio/wav');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
            if ranged:self.send_header('Content-Range',f'bytes {start}-{end}/{length}')
            self.end_headers()
            with file.open('rb') as stream:
                stream.seek(start);remaining=end-start+1
                while remaining:
                    block=stream.read(min(1024*1024,remaining))
                    if not block:break
                    self.wfile.write(block);remaining-=len(block)
            return
        if path.startswith('/image/'):
            name=path[len('/image/'):]
            try:file=asset(name,'image')
            except ValueError:return self.json({'error':'Image not found'},404)
            if not file:return self.json({'error':'Image not found'},404)
            data=file.read_bytes();self.send_response(200);self.send_header('Content-Type','image/png' if file.suffix=='.png' else 'application/octet-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();return self.wfile.write(data)
        if path=='/':
            data=(ROOT/'studio.html').read_text(encoding='utf-8').replace('__TOKEN__',TOKEN).encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            return self.wfile.write(data)
        if path.startswith('/video/') or path.startswith('/combined/'):
            combined=path.startswith('/combined/')
            identifier=path.split('/',2)[2]
            if not identifier or Path(identifier).name!=identifier:
                return self.json({'error':'Invalid video'},404)
            file=(jobs_root()/identifier/('combined.mp4' if combined else 'video.mp4')).resolve()
            if not file.is_relative_to(jobs_root().resolve()) or not file.is_file():
                return self.json({'error':'Video not found'},404)
            length=file.stat().st_size
            start,end=0,length-1
            ranged=self.headers.get('Range')
            if ranged:
                try:
                    spec=ranged.removeprefix('bytes=').split('-')
                    start=int(spec[0]);end=min(int(spec[1]) if spec[1] else end,end)
                    if not 0<=start<=end: raise ValueError()
                except (ValueError,IndexError):
                    self.send_response(416);self.send_header('Content-Range',f'bytes */{length}');self.end_headers();return
            self.send_response(206 if ranged else 200)
            self.send_header('Content-Type','video/mp4')
            self.send_header('Accept-Ranges','bytes')
            self.send_header('Content-Length',str(end-start+1))
            if ranged:self.send_header('Content-Range',f'bytes {start}-{end}/{length}')
            self.end_headers()
            with file.open('rb') as source:
                source.seek(start);remaining=end-start+1
                while remaining:
                    block=source.read(min(1024*1024,remaining))
                    if not block:break
                    self.wfile.write(block);remaining-=len(block)
            return
        self.json({'error':'Not found'},404)

    def send_file(self,file,mime):
        length=file.stat().st_size;start,end=0,length-1;ranged=self.headers.get('Range')
        if ranged:
            try:
                if not ranged.startswith('bytes=') or ',' in ranged:raise ValueError()
                left,right=ranged[6:].split('-',1)
                if not left:start=max(0,length-int(right))
                else:start=int(left)
                if right and left:end=min(int(right),end)
                if not 0<=start<=end:raise ValueError()
            except (ValueError,IndexError):
                self.send_response(416);self.send_header('Content-Range',f'bytes */{length}');self.end_headers();return
        self.send_response(206 if ranged else 200);self.send_header('Content-Type',mime);self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1));self.send_header('X-Content-Type-Options','nosniff')
        if ranged:self.send_header('Content-Range',f'bytes {start}-{end}/{length}')
        self.end_headers()
        with file.open('rb') as stream:
            stream.seek(start);remaining=end-start+1
            while remaining:
                chunk=stream.read(min(1024*1024,remaining))
                if not chunk:break
                self.wfile.write(chunk);remaining-=len(chunk)

    def do_POST(self):
        try:
            hub=getattr(self.server,'hub',None)
            if hub:
                with hub.admission(urlparse(self.path).path,self.studio.workspace_id):
                    with workspace_scope(self.studio.directory):return self.workspace_POST()
            with workspace_scope(self.studio.directory):return self.workspace_POST()
        except (ValueError,OSError) as exc:return self.json({'error':str(exc)},400)
        except Exception:return self.json({'error':'Unexpected application error. Open Settings → Activity & logs.'},500)
    def workspace_POST(self):
        if not self.valid_host() or self.headers.get('X-Studio-Token')!=TOKEN or self.headers.get('Origin')!=f'http://127.0.0.1:{PORT}':
            # Drain small rejected requests so Windows sends the JSON error
            # instead of resetting the socket with an unread request body.
            try:
                rejected_length=int(self.headers.get('Content-Length','0'))
                if 0<rejected_length<=20000:self.rfile.read(rejected_length)
            except ValueError:
                pass
            return self.json({'error':'Invalid local request'},403)
        try:
            path=urlparse(self.path).path
            length=int(self.headers.get('Content-Length','0'))
            if path in ('/api/upload','/api/assets/upload','/api/chat/upload'):
                kind=self.headers.get('X-Media-Kind')
                suffix=self.headers.get('X-File-Extension','').lower()
                formats={'image':IMAGE,'video':VIDEO,'audio':{'.wav','.mp3','.flac','.ogg','.m4a'},'document':TEXT_FORMATS,'project':{'.zip'},'model':{'.gguf'}}
                if kind not in (formats if path in ('/api/assets/upload','/api/chat/upload') else ('image','video')) or suffix not in formats[kind]:
                    raise ValueError('Unsupported media type')
                limit=32*1024**3 if kind in ('project','model') else (32 if kind=='image' else 256)*1024*1024
                if not 0<length<=limit:
                    raise ValueError('Image limit is 32 MiB; video limit is 256 MiB')
                if path=='/api/chat/upload' and kind not in ('document','image','video'):raise ValueError('Unsupported chat attachment')
                if kind=='document' and length>(32 if suffix=='.pdf' else 2)*1024*1024:raise ValueError('PDF limit is 32 MiB; text attachment limit is 2 MiB')
                identifier=uuid.uuid4().hex+suffix
                final_target=uploads_root()/identifier
                target=uploads_root()/(identifier+'.partial')
                try:
                    with target.open('xb') as file:
                        remaining=length
                        while remaining:
                            block=self.rfile.read(min(1024*1024,remaining))
                            if not block:raise ValueError('Incomplete upload')
                            file.write(block);remaining-=len(block)
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                if path in ('/api/assets/upload','/api/chat/upload'):
                    try:
                        if kind=='image':
                            from PIL import Image
                            with Image.open(target) as img:img.verify()
                        elif kind=='document':
                            if suffix=='.pdf':__import__('studio_pdf').process_pdf(target,validate=True)
                            else:__import__('studio_attachments').decode_text(target.read_bytes())
                        elif kind not in ('project','model'):
                            probe=subprocess.run([str(FFMPEG),'-hide_banner','-i',str(target)],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
                            if b'Stream #' not in probe.stderr:raise ValueError('File is not valid playable media')
                    except Exception as exc:
                        target.unlink(missing_ok=True);raise ValueError(str(exc) if kind=='document' else 'Invalid uploaded asset')
                os.replace(target,final_target)
                if path=='/api/chat/upload':
                    hub=self.server.hub
                    row=hub.store.import_file(self.studio.workspace_id,final_target,name=__import__('urllib.parse',fromlist=['unquote']).unquote(self.headers.get('X-Attachment-Name',identifier)))
                    final_target.unlink(missing_ok=True)
                    return self.json({'asset':row['id'],'name':row['name'],'kind':row['kind']})
                return self.json({'id':identifier})
            if length>(128*1024 if path=='/api/settings/instructions' else 20000):raise ValueError('Request too large')
            value=json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(value,dict):raise ValueError('Request must be a JSON object')
            request_hub=getattr(self.server,'hub',None)
            if request_hub:
                request_hub.store.pins=request_hub.queue.protected_owners()|{owner for owner,instance in request_hub.instances.items() if instance.current or instance.image_current or instance.voice.current or instance.chat.busy or request_hub.conversations.busy(owner)}
                document=request_hub.store.get(self.studio.workspace_id)
                if document.get('archived') and path not in ('/api/workspace/update','/api/workspace/export','/api/workspace/portable-plan','/api/workspace/reclaim','/api/logs/client','/api/settings/instructions'):raise ValueError('Restore the archived project before making changes')
            hub=getattr(self.server,'hub',None)
            if path=='/api/logs/client':
                message=value.get('message');details=value.get('details','')
                if not isinstance(message,str) or len(message)>4000 or not isinstance(details,str) or len(details)>12000:raise ValueError('Invalid diagnostic event')
                return self.json({'id':LOG.record('error','ui',message,self.headers.get('X-Studio-Workspace','free-work'),details=details)})
            if hub and path=='/api/queue/action':return self.json(hub.queue.action(value))
            if path=='/api/voice/plan':
                from sound_script import parse_script
                text=value.get('text','')
                if not isinstance(text,str) or len(text)>12000:raise ValueError('Script limit: 12,000 characters')
                return self.json({'plan':parse_script(text)})
            if hub and path=='/api/settings/instructions':return self.json(hub.instructions.save(self.studio.workspace_id,value.get('scope'),value))
            if hub and path=='/api/chat/preload':
                from studio_chat import StudioChat
                with hub.gate:
                    if StudioChat._warming:return self.json(StudioChat.runtime_state())
                    if hub.reserved or hub.busy():return self.json(dict(status='deferred',message='Waiting for active Studio work to finish'))
                    mode=value.get('mode')
                    if mode is None:
                        try:mode=json.loads((ROOT/'studio-data/chat-runtime/settings.json').read_text(encoding='utf-8')).get('mode','cpu')
                        except (OSError,ValueError):mode='cpu'
                    def prepare():
                        for instance in list(hub.instances.values()):
                            if instance.image_service:instance.image_service.stop_for_generation()
                    return self.json(self.studio.chat.preload(mode,hub.models.selected('writing'),prepare),202)
            if hub and path=='/api/settings/models/plan':return self.json(hub.models.plan(value.get('id')))
            if hub and path=='/api/settings/models/select':
                from studio_models import CATALOG
                if CATALOG.get(value.get('id'),{}).get('engine') in ('writing','vision'):self.studio.chat.stop()
                result=hub.models.select(value.get('id'));return self.json(result)
            if hub and path=='/api/settings/models/download':
                plan=hub.models.plan(value.get('id'));return self.json(hub.models.install(plan),202)
            if hub and path=='/api/settings/models/import':
                name=value.get('upload')
                if not isinstance(name,str) or Path(name).name!=name or Path(name).suffix!='.gguf':raise ValueError('Choose an uploaded official GGUF')
                return self.json(hub.models.install(hub.models.plan(value.get('id')),source=uploads_root()/name,cleanup_source=True,workspace=self.studio.workspace_id),202)
            if hub and path=='/api/settings/models/remove':return self.json(hub.models.remove(value.get('id')))
            if hub and path=='/api/settings/models/clear-partial':return self.json(hub.models.clear_partial())
            if hub and path=='/api/settings/models/cancel':return self.json(hub.models.cancel_download())
            if hub and path in ('/api/generate','/api/image/generate','/api/voice/start','/api/chat/send'):
                engine={'/api/generate':'video','/api/image/generate':'image','/api/voice/start':'voice','/api/chat/send':'chat'}[path]
                value=hub.capture(self.studio.workspace_id,engine,value)
                if engine!='chat':return self.json(hub.queue.enqueue(self.studio.workspace_id,engine,value),202)
            if hub and path=='/api/jobs/hide':
                from workspace_store import identifier,atomic
                if self.studio.workspace_id in hub.queue.owners():raise ValueError('Remove pending jobs from Job queue first')
                if hub.active() and hub.active()['workspace']==self.studio.workspace_id:raise ValueError('Wait for the project job')
                sub={'videos':'jobs','images':'image-jobs','audio':'voices/jobs'}.get(value.get('kind'))
                if not sub:raise ValueError('Invalid job kind')
                job_id=value.get('id')
                if not isinstance(job_id,str) or not re.fullmatch(r'[0-9a-f]{32}|[0-9]{8}-[0-9]{6}-[0-9a-f]{8}',job_id):raise ValueError('Invalid job ID')
                file=hub.store.folder(self.studio.workspace_id)/sub/job_id/'job.json'
                row=json.loads(file.read_text(encoding='utf-8'))
                if row.get('status') in ('running','cancelling','pausing','paused','queued'):raise ValueError('Cancel the active or paused job before hiding it')
                row['hidden']=True;atomic(file,row);return self.json({'ok':True})
            if hub and path=='/api/chats/action':return self.json(hub.conversations.action(self.studio.workspace_id,value))
            if hub and path=='/api/workspace/reclaim':
                from workspace_archive import reclaim
                return self.json(reclaim(hub.store,hub.portable.exports,self.studio.workspace_id))
            if hub and path=='/api/workspace/archive':
                w=self.studio.workspace_id
                if hub.conversations.busy(w) or hub.active() and hub.active()['workspace']==w:raise ValueError('Wait for active project jobs')
                hub.conversations.rows(w)
                output=hub.portable.export(w,chat=True)
                from workspace_store import digest
                result=hub.store.update(w,{'archived':True})
                result['archive_file']=output['file'];result['archive_sha256']=digest(hub.portable.exports/output['file']);hub.store.save(result)
                return self.json(result)
            if hub and path=='/api/workspace/preview':return self.json(hub.capture(self.studio.workspace_id,value.get('engine'),value.get('settings',{})))
            if hub and path.startswith('/api/workspace'):
                w=self.studio.workspace_id;store=hub.store
                store.pins=hub.queue.protected_owners()|{owner for owner,instance in hub.instances.items() if instance.current or instance.image_current or instance.voice.current or instance.chat.busy or hub.conversations.busy(owner)}
                if hub.models.download and hub.models.download.get('state')=='downloading' and hub.models.download.get('workspace'):store.pins.add(hub.models.download['workspace'])
                if path=='/api/workspace/portable-plan':return self.json(hub.portable.estimate(w,value.get('snapshot')))
                if path=='/api/workspace/snapshot':return self.json(store.snapshot(w,value.get('name'),include_chat=bool(value.get('chat'))))
                if path=='/api/workspace/snapshot/delete':store.remove_snapshot(w,value.get('id'));return self.json({'ok':True})
                if path=='/api/workspace/branch':hub.conversations.rows(w);return self.json(hub.portable.branch(w,value.get('name'),value.get('snapshot'),bool(value.get('chat'))))
                if path=='/api/workspace/export' and store.get(w).get('archived') and store.get(w).get('archive_file'):return self.json({'file':store.get(w)['archive_file']})
                if path=='/api/workspace/export':hub.conversations.rows(w);return self.json(hub.portable.export(w,value.get('snapshot'),bool(value.get('chat'))))
                if path=='/api/workspaces/import':
                    name=value.get('upload')
                    if not isinstance(name,str) or Path(name).name!=name or Path(name).suffix!='.zip':raise ValueError('Choose an uploaded project ZIP')
                    try:result=hub.portable.import_zip(uploads_root()/name,value.get('name'))
                    except Exception as exc:raise ValueError('Project import failed: '+str(exc))
                    (uploads_root()/name).unlink(missing_ok=True);return self.json(result)
                if path=='/api/workspaces/purge':store.purge_workspace(value.get('id'));hub.instances.pop(value['id'],None);return self.json({'ok':True})
                if path=='/api/workspaces/restore':return self.json(store.update(value.get('id'),{'deleted':False}))
                if path=='/api/workspaces/create':return self.json(store.create(value.get('name')),201)
                if path=='/api/workspace/update':
                    if value.get('archived') is False and store.get(w).get('archive_reclaimed'):
                        from workspace_archive import restore_assets
                        restore_assets(store,hub.portable.exports,w)
                    return self.json(store.update(w,value))
                if path=='/api/workspace/context':
                    if value.get('voice'):self.studio.voice.file('profiles',value['voice'],'profile.json')
                    return self.json(store.context(w,value))
            if hub and path=='/api/operations/cancel':
                result=hub.store.cancel_operation(value.get('id'),self.studio.workspace_id)
                operation=json.loads((hub.store.root/'operations'/(value['id']+'.json')).read_text(encoding='utf-8'))
                if operation.get('kind')=='portable' and value['id'] not in hub.store.active_operations:hub.portable.abort(value['id'])
                return self.json(result)
            if hub and path=='/api/operations/recover':hub.store.recover();hub.portable.recover();return self.json({'ok':True})
            if hub and path=='/api/assets/plan':return self.json(hub.store.transfer_plan(self.studio.workspace_id,value.get('id'),value.get('include',True)))
            if hub and path=='/api/assets/action':return self.json(hub.mutate_asset(self.studio.workspace_id,value))
            if hub and path=='/api/assets/import':
                w=self.studio.workspace_id;name=value.get('upload')
                if not isinstance(name,str) or Path(name).name!=name:raise ValueError('Invalid upload')
                items=hub.publish(w);row=next((a for a in items if a['metadata'].get('legacy_name')==name),None)
                if not row:raise ValueError('Uploaded asset not found')
                return self.json(hub.store.edit_asset(w,row['id'],{'name':value.get('name',name)}))
            if path=='/api/delete' and hub:
                w=self.studio.workspace_id;hub.publish(w)
                engine='video' if value.get('kind')=='video' else 'voice'
                matches=[a for a in hub.store.assets(w) if a['metadata'].get('job')==value.get('id') and a['metadata'].get('engine')==engine]
                if not matches:
                    base=jobs_root() if engine=='video' else self.studio.voice.jobs
                    record=json.loads((base/value['id']/'job.json').read_text(encoding='utf-8'));id=record.get('settings',{}).get('imported_asset')
                    if id:matches=[hub.store.asset(w,id)[0]]
                if not matches:raise ValueError('No active outputs found for this job')
                for item in matches:hub.mutate_asset(w,{'action':'trash','id':item['id']})
                jobfile=(jobs_root() if engine=='video' else self.studio.voice.jobs)/value['id']/'job.json'
                row=json.loads(jobfile.read_text(encoding='utf-8'));row['hidden']=True;write_json(jobfile,row)
                return self.json({'ok':True,'trashed':len(matches)})
            if path=='/api/delete':
                with self.studio.lock:
                    st=self.studio
                    if st.current or st.image_current or st.voice.current:raise ValueError('Wait for the active media job before deleting files.')
                    from studio_admin import delete_job
                    kind=value.get('kind')
                    if kind not in ('video','audio'):raise ValueError('Choose video or audio')
                    with st.voice.lock:
                        return self.json(delete_job(jobs_root() if kind=='video' else st.voice.jobs,value.get('id')))
            if path=='/api/chat/send':
                with self.studio.lock:
                    st=self.studio
                    if st.current or st.image_current or st.voice.current:raise ValueError('Wait for media generation to finish before chatting.')
                    if st.image_service:st.image_service.stop_for_generation()
                    if value.get('attachments'):
                        from studio_attachments import prepare
                        rows,notes,visual=prepare(hub,st.workspace_id,value['attachments'],value.get('text',''))
                        value.update(attachment_rows=rows,attachment_notes=notes,visual=visual)
                        if visual:
                            if 'vision' not in hub.models.state['selected']:raise ValueError('Install and select a local vision model in Settings before analyzing pictures or videos')
                            value['vision_model']=hub.models.selected('vision')
                    return self.json((hub.conversations.instance(st.workspace_id,self.headers.get('X-Studio-Chat')) if hub and self.headers.get('X-Studio-Chat') else st.chat).reply(value,st.voice.state().get('profiles',[])))
            if path=='/api/chat/stop':
                return self.json((hub.conversations.instance(self.studio.workspace_id,self.headers.get('X-Studio-Chat')) if self.headers.get('X-Studio-Chat') else self.studio.chat).cancel_reply(value.get('request_id')))
            if path=='/api/chat/unload':self.studio.chat.stop();return self.json({'ok':True})
            if path=='/api/chat/clear':(hub.conversations.instance(self.studio.workspace_id,self.headers.get('X-Studio-Chat')) if hub and self.headers.get('X-Studio-Chat') else self.studio.chat).clear();return self.json({'ok':True})
            if path in ('/api/generate','/api/image/generate','/api/voice/start'):
                self.studio.chat.stop()
            if path=='/api/voice/join':
                with self.studio.lock:return self.json(self.studio.voice.join(value),202)
            if path=='/api/voice/start':
                with self.studio.lock:return self.json(self.studio.voice.start(value),202)
            if hub and path=='/api/characters/action':
                from studio_characters import action
                return self.json(action(hub,self.studio.workspace_id,value))
            if hub and path=='/api/voices/action' and value.get('action') in ('copy','move'):
                from studio_voice_transfer import transfer
                return self.json(transfer(hub,self.studio.workspace_id,value))
            if hub and path=='/api/voices/action':
                w=self.studio.workspace_id
                with hub.gate,hub.store.lock:
                    if w in hub.queue.protected_owners() or hub.active() and hub.active()['workspace']==w or hub.conversations.busy(w) or w in hub.store.operation_pins:raise ValueError('Wait for active project work before changing saved voices')
                    doc=hub.store.get(w);result=self.studio.voice.profile_action(value,doc)
                    if value.get('action')=='trash' and doc['context'].get('voice')==value.get('id'):
                        doc['context']['voice']=None;doc['context']['revision']+=1;hub.store.save(doc)
                    return self.json(result)
            if path=='/api/voice/save':return self.json(self.studio.voice.save_profile(value.get('id'),value.get('name'),value.get('scope','workspace')))
            if path=='/api/voice/cancel':self.studio.voice.cancel();return self.json({'ok':True})
            if path=='/api/generate':return self.json(self.studio.start(value),202)
            if path=='/api/frame':return self.json(self.studio.export_frame(value.get('id')))
            if path=='/api/join':return self.json(self.studio.attach(value),202)
            if path=='/api/image/generate':return self.json(self.studio.start_image(value),202)
            if path=='/api/image/cancel':self.studio.cancel_image();return self.json({'ok':True})
            if path=='/api/cancel':self.studio.cancel();return self.json({'ok':True})
            if path=='/api/folder':os.startfile(str(jobs_root()));return self.json({'ok':True})
            return self.json({'error':'Not found'},404)
        except (ValueError,TypeError,OSError,subprocess.TimeoutExpired) as exc:
            self.json({'error':str(exc)},400)

if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    from studio_workspaces import StudioHub
    server.hub=StudioHub()
    server.studio=server.hub.studio('free-work')
    server.hub.queue.start()
    print(f'FreeVideo Studio: http://127.0.0.1:{PORT}',flush=True)
    server.serve_forever()
