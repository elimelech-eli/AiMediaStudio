"""Local voice design, reusable profiles, and prepared-script narration jobs."""
import hashlib,json,os,re,shutil,subprocess,threading,time,uuid,secrets,wave
from pathlib import Path

ROOT=Path(__file__).resolve().parent
ENGINE=ROOT.parent/'media-runtime/voice'

def write(path,value):
    from studio_files import atomic_json
    return atomic_json(path,value)

def join_audio(paths,target,gap_ms=250):
    if type(gap_ms) is not int or not 0<=gap_ms<=5000:raise ValueError('Pause must be between 0 and 5,000 milliseconds')
    parameters=None
    with wave.open(str(target),'wb') as output:
        for index,path in enumerate(paths):
            with wave.open(str(path),'rb') as source:
                current=(source.getnchannels(),source.getsampwidth(),source.getframerate(),source.getcomptype())
                if current[3]!='NONE':raise ValueError('Only PCM WAV clips can be joined')
                if parameters is None:parameters=current;output.setnchannels(current[0]);output.setsampwidth(current[1]);output.setframerate(current[2])
                elif parameters!=current:raise ValueError('Audio formats differ. Join clips with the same sample rate and channel format.')
                if index:output.writeframesraw(b'\0'*(round(current[2]*gap_ms/1000)*current[0]*current[1]))
                while True:
                    block=source.readframes(16384)
                    if not block:break
                    output.writeframesraw(block)
    with wave.open(str(target),'rb') as result:return result.getnframes()/result.getframerate()

class VoiceStudio:
    def __init__(self,directory,profiles=None,busy=lambda:False,release=lambda:None):
        self.root=Path(directory);self.jobs=self.root/'jobs';self.profiles=Path(profiles) if profiles else self.root/'profiles'
        for folder in (self.jobs,self.profiles):folder.mkdir(parents=True,exist_ok=True)
        self.local_profiles=self.root/'profiles';self.local_profiles.mkdir(parents=True,exist_ok=True)
        self.current=None;self.process=None;self.lock=threading.RLock();self.other_busy=busy;self.release=release
        for path in self.jobs.glob('*/job.json'):
            row=json.loads(path.read_text(encoding='utf-8'))
            if row['status']=='running':row.update(status='interrupted',message='Studio stopped before speech finished.');write(path,row)
    def valid_profile(self,folder,include_trashed=False):
        try:
            folder=Path(folder)
            if not folder.resolve().is_relative_to(self.local_profiles.resolve()) or not re.fullmatch('[0-9a-f]{32}',folder.name):return None
            metadata=(folder/'profile.json').resolve()
            if not metadata.is_relative_to(self.local_profiles.resolve()):return None
            row=json.loads(metadata.read_text(encoding='utf-8'))
            if not isinstance(row,dict) or ((row.get('hidden') or row.get('trashed')) and not include_trashed):return None
            if row.get('id')!=folder.name or not isinstance(row.get('name'),str) or not row['name'].strip():return None
            audio=(folder/'reference.wav').resolve()
            if not audio.is_relative_to(self.local_profiles.resolve()):return None
            with wave.open(str(audio),'rb') as source:
                if source.getnframes()<1:return None
            return row
        except (OSError,ValueError,TypeError,wave.Error,EOFError):return None
    def profile_listing(self,include_trashed=False):
        return [row for folder in self.local_profiles.iterdir() if folder.is_dir() and (row:=self.valid_profile(folder,include_trashed)) is not None and not row.get('hidden') and not row.get('library_hidden')]
    def profile_action(self,value,document):
        identifier=value.get('id');action=value.get('action')
        if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):raise ValueError('Invalid saved voice')
        folder=self.local_profiles/identifier;row=self.valid_profile(folder,True)
        if not row:raise ValueError('Saved voice not found in this project')
        if action=='rename':
            name=value.get('name','').strip()
            if not 1<=len(name)<=80:raise ValueError('Voice name must be 1–80 characters')
            row['name']=name
        elif action in ('trash','restore'):
            if action=='trash' and any(v.get('voice')==identifier for c in document.get('characters',{}).values() for v in [c,*c.get('history',[])]):raise ValueError('Character versions retain this voice; keep it or remove those character definitions before deleting it')
            row['trashed']=action=='trash'
        elif action=='duplicate':
            key=uuid.uuid4().hex;target=self.local_profiles/key;target.mkdir();shutil.copyfile(folder/'reference.wav',target/'reference.wav');row=dict(row,id=key,name=(value.get('name') or row['name']+' copy')[:80],trashed=False);folder=target
        elif action=='purge':
            if not row.get('trashed'):raise ValueError('Delete the voice first')
            if any(v.get('voice')==identifier for c in document.get('characters',{}).values() for v in [c,*c.get('history',[])]):raise ValueError('This voice is retained by a project character')
            if any(identifier in snap.get('voice_profiles',[]) for snap in document.get('snapshots',{}).values()):raise ValueError('This voice is retained by a snapshot; remove that snapshot first')
            shutil.rmtree(folder);return {'ok':True}
        else:raise ValueError('Unknown saved voice action')
        write(folder/'profile.json',row);return row
    def file(self,kind,identifier,name):
        if kind not in ('jobs','profiles') or not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):raise ValueError('Invalid voice item')
        base=self.local_profiles if kind=='profiles' else self.jobs
        if kind=='profiles' and not self.valid_profile(base/identifier):raise ValueError('Saved voice is unavailable in this project. Create and save a voice here first.')
        path=(base/identifier/name).resolve()
        if not path.is_relative_to(base.resolve()) or not path.is_file():raise ValueError('Voice item not found')
        return path
    def state(self):
        def rows(folder,filename):
            result=[]
            for path in sorted(folder.glob('*/'+filename),key=lambda p:p.stat().st_mtime,reverse=True)[:100]:
                try:
                    row=json.loads(path.read_text(encoding='utf-8'))
                    if not isinstance(row,dict):continue
                    if row.get('hidden') or (filename=='job.json' and row.get('status')=='completed' and not (path.parent/'audio.wav').is_file()):continue
                    if filename=='profile.json':
                        row=self.valid_profile(path.parent)
                        if row is None or row.get('library_hidden'):continue
                    result.append(row)
                except (OSError,ValueError):pass
            return result
        return dict(active=self.current,jobs=rows(self.jobs,'job.json'),profiles=rows(self.local_profiles,'profile.json'),retained_profiles=[row['id'] for folder in self.local_profiles.iterdir() if folder.is_dir() and (row:=self.valid_profile(folder)) and row.get('library_hidden')])
    def completed(self,identifier,chain=False):
        row=json.loads(self.file('jobs',identifier,'job.json').read_text(encoding='utf-8'))
        if row['status']!='completed':raise ValueError('Choose a completed audio clip')
        return row,self.file('jobs',identifier,'combined.wav' if chain and row.get('combined') else 'audio.wav')
    def join(self,value):
        with self.lock:
            if self.current or self.other_busy():raise ValueError('Wait for the current media job to finish first')
            clips=value.get('clips');gap=value.get('gap_ms',250)
            if not isinstance(clips,list) or not 2<=len(clips)<=32:raise ValueError('Choose 2–32 audio clips in order')
            if type(gap) is not int or not 0<=gap<=5000:raise ValueError('Pause must be between 0 and 5,000 milliseconds')
            sources=[];rows=[];texts=[]
            for clip in clips:
                if not isinstance(clip,dict):raise ValueError('Invalid audio selection')
                row,path=self.completed(clip.get('id'),bool(clip.get('chain')));sources.append(path);rows.append(row)
                texts.append(row.get('combined_text',row['settings']['text']) if clip.get('chain') else row['settings']['text'])
            key=uuid.uuid4().hex;folder=self.jobs/key;folder.mkdir()
            profiles={row['settings'].get('profile') for row in rows};profile=profiles.pop() if len(profiles)==1 else None
            row=dict(id=key,status='running',phase='Joining audio',started=time.time(),settings=dict(action='join',text='\n\n'.join(texts),profile=profile,description='',clips=clips,gap_ms=gap))
            write(folder/'job.json',row);self.current=key
            threading.Thread(target=self.finish_join,args=(folder,row,sources,gap),daemon=True).start();return row
    def finish_join(self,folder,row,sources,gap):
        try:
            seconds=join_audio(sources,folder/'audio.wav',gap)
            try:os.link(folder/'audio.wav',folder/'combined.wav')
            except OSError:shutil.copyfile(folder/'audio.wav',folder/'combined.wav')
            row.update(status='completed',combined=True,seconds=seconds,combined_seconds=seconds,phase='Joined audio ready')
        except Exception as exc:row.update(status='failed',message=str(exc))
        finally:
            row['elapsed']=row.get('elapsed_base',0)+round(time.time()-row['started']);write(folder/'job.json',row)
            with self.lock:self.current=None
    def save_profile(self,identifier,name,scope='workspace'):
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise ValueError('Enter a voice name of up to 80 characters')
        row=json.loads(self.file('jobs',identifier,'job.json').read_text(encoding='utf-8'))
        if row['status']!='completed' or row['settings']['action']!='design':raise ValueError('Select a completed voice-design sample')
        if scope!='workspace':raise ValueError('Save voices in the current project; shared voice saving is no longer supported')
        source=self.file('jobs',identifier,'audio.wav');key=uuid.uuid4().hex;folder=self.local_profiles/key;folder.mkdir()
        shutil.copyfile(source,folder/'reference.wav')
        profile=dict(id=key,name=name.strip(),description=row['settings']['description'],reference_text=row['settings']['text'],sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        write(folder/'profile.json',profile);return profile
    def start(self,value):
        with self.lock:
            if self.current or self.other_busy():raise ValueError('Wait for the current media job to finish first')
            resuming=value.get('_resume',False);previous={}
            if resuming:
                previous=json.loads((self.jobs/value['_queued_id']/'job.json').read_text(encoding='utf-8'));value=dict(previous['settings'],_queued_id=value['_queued_id'],_resume=True)
            action=value.get('action');text=value.get('text');description=value.get('description','')
            if action not in ('design','read'):raise ValueError('Choose voice design or read script')
            if not isinstance(text,str) or not text.strip() or len(text)>(600 if action=='design' else 12000):raise ValueError('Sample limit: 600 characters. Script limit: 12,000 characters.')
            from voice_text import speech_text
            from sound_script import parse_script,sound_cues
            plan=parse_script(text)
            needs_speech=any(p['kind']=='speech' and speech_text(p['text']).strip() for p in plan)
            if not needs_speech and not sound_cues(plan):raise ValueError('Enter words to speak or sound descriptions')
            if action=='design' and any(p['kind']!='speech' for p in plan):raise ValueError('Use plain audition text for voice design; sound cues belong in prepared scripts')
            if sound_cues(plan) and not (value.get('sound_model_spec') or {}).get('verified'):raise ValueError('Install and select a verified sound-effects model in Settings → Audio')
            if action=='design' and (not isinstance(description,str) or not description.strip() or len(description)>2000):raise ValueError('Describe the voice in up to 2,000 characters')
            seed=value.get('seed',secrets.randbelow(2147483647))
            if type(seed) is not int or not 0<=seed<=2147483647:raise ValueError('Invalid seed')
            profile=None
            parent=value.get('continue_from');base=None
            gap=value.get('gap_ms',250)
            if type(gap) is not int or not 0<=gap<=5000:raise ValueError('Pause must be between 0 and 5,000 milliseconds')
            if parent:
                if action!='read':raise ValueError('Only prepared narration can continue an audio chain')
                base,_=self.completed(parent,True)
                if not base['settings'].get('profile'):raise ValueError('This clip has no single saved voice. Generate a narration with a saved voice first.')
            if action=='read' and needs_speech:profile=json.loads(self.file('profiles',base['settings']['profile'] if base else value.get('profile'),'profile.json').read_text(encoding='utf-8'))
            self.release()
            gpu=subprocess.run(['nvidia-smi','--query-gpu=memory.total,memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
            try:total,used,util=map(float,gpu.stdout.strip().splitlines()[0].split(','))
            except (ValueError,IndexError):raise ValueError('Could not verify free GPU memory')
            needed=max((value.get('model_spec') or {}).get('gpu_mib') or (4300 if action=='design' else 2800),(value.get('sound_model_spec') or {}).get('gpu_mib',0) or 0)
            if util>30 or total-used<needed:raise ValueError('GPU is busy. Unload other GPU models before creating speech.')
            key=value.get('_queued_id') or uuid.uuid4().hex;folder=self.jobs/key;folder.mkdir(exist_ok=True)
            settings=dict(action=action,text=text.strip(),description=description if action=='design' else profile['description'] if profile else '',profile=profile['id'] if profile else None,context_snapshot=value.get('context_snapshot'),model_spec=value.get('model_spec'),workspace_id=value.get('workspace_id'),seed=seed,continue_from=parent,gap_ms=gap,sound_plan=plan,sound_model_spec=value.get('sound_model_spec'),character_snapshot=value.get('character_snapshot'))
            write(folder/'request.json',dict(**settings,profile_data=profile,profile_root=str(self.file('profiles',profile['id'],'profile.json').parent.parent) if profile else str(self.profiles)))
            checkpoint=folder/'checkpoint';checkpoint.mkdir(exist_ok=True);(checkpoint/'pause.request').unlink(missing_ok=True)
            row=dict(id=key,status='running',checkpoint_capable=True,elapsed_base=previous.get('elapsed',0),phase='Loading local voice model',started=time.time(),settings=settings);write(folder/'job.json',row)
            env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONPATH=str(ENGINE))
            for name,sub in {'TEMP':'tmp','TMP':'tmp','TORCH_HOME':'cache/torch','HF_HOME':'cache/huggingface','XDG_CACHE_HOME':'cache','PYTHONPYCACHEPREFIX':'cache/pycache','CUDA_CACHE_PATH':'cache/cuda'}.items():env[name]=str(ENGINE/sub)
            out=(folder/'worker.log').open('w');err=(folder/'error.log').open('w')
            try:self.process=subprocess.Popen([str(ENGINE/'.venv/Scripts/python.exe'),'-B','-u',str(ROOT/'voice_job.py'),str(folder)],env=env,cwd=ENGINE,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception as exc:row.update(status='failed',message=str(exc));write(folder/'job.json',row);raise
            finally:out.close();err.close()
            self.current=key;threading.Thread(target=self.finish,args=(folder,row,self.process),daemon=True).start();return row
    def finish(self,folder,row,process):
        try:
            deadline=time.time()+3600
            while process.poll() is None:
                if time.time()>deadline:raise subprocess.TimeoutExpired('voice',3600)
                try:
                    lines=(folder/'worker.log').read_text(errors='replace').splitlines()
                    if lines:
                        progress=json.loads(lines[-1]);row['phase']=progress.get('phase',row['phase'])
                        if progress.get('total'):row['phase']+=f" · section {progress['chunk']}/{progress['total']}"
                except (OSError,ValueError):pass
                row['elapsed']=row.get('elapsed_base',0)+round(time.time()-row['started'])
                with self.lock:
                    if json.loads((folder/'job.json').read_text()).get('cancelled'):row['cancelled']=True
                    if (folder/'checkpoint/pause.request').exists():row.update(status='pausing',phase='Pausing after current speech section or sound effect')
                    write(folder/'job.json',row)
                time.sleep(.5)
            code=process.returncode
            if json.loads((folder/'job.json').read_text()).get('cancelled'):row.update(status='cancelled')
            elif (folder/'checkpoint/pause.request').is_file() and __import__('freevideo_engine.studio_checkpoint',fromlist=['ready']).ready(folder/'checkpoint',fresh=True):
                row.update(status='paused',phase='Paused · GPU released',message='Completed speech sections and sound effects saved')
            elif code==0 and (folder/'audio.wav').is_file():row.update(status='completed',phase='Audio ready',**json.loads((folder/'result.json').read_text()))
            else:row.update(status='failed',message='Speech generation failed. See this job’s error.log for technical details.')
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill.exe','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW);row.update(status='failed',message='Speech generation timed out')
        except Exception as exc:row.update(status='failed',message=str(exc))
        finally:
            if row['status']=='completed' and row['settings'].get('continue_from'):
                try:
                    parent,path=self.completed(row['settings']['continue_from'],True)
                    row['combined_seconds']=join_audio([path,folder/'audio.wav'],folder/'combined.wav',row['settings']['gap_ms'])
                    row.update(combined=True,combined_text=parent.get('combined_text',parent['settings']['text'])+'\n\n'+row['settings']['text'])
                except Exception as exc:row['message']='New audio is ready, but joining failed: '+str(exc)
            row.update(elapsed=row.get('elapsed_base',0)+round(time.time()-row['started']));write(folder/'job.json',row)
            with self.lock:self.current=None;self.process=None
    def cancel(self):
        with self.lock:
            if not self.current or not self.process:return
            path=self.jobs/self.current/'job.json';row=json.loads(path.read_text());row['cancelled']=True;write(path,row)
            # The finisher reads cancellation from disk after the owned process exits.
            subprocess.run(['taskkill.exe','/PID',str(self.process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
