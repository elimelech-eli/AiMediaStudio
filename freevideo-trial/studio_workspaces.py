from studio_attachments import DOCUMENTS as TEXT_FORMATS
"""Workspace adapters and compatibility publication for existing media engines."""
import json,os,shutil,threading,time,uuid
from pathlib import Path
from contextlib import contextmanager
from workspace_store import WorkspaceStore,atomic,digest,key,contained
ROOT=Path(__file__).resolve().parent;HOME=ROOT.parent/'media-workspaces'

class StudioHub:
 def __init__(self,root=HOME,allow_migrating=False):
  self.store=WorkspaceStore(root);__import__('studio_voice_transfer').recover(self.store);self.gate=threading.RLock();self.instances={};self.reserved=False;self.profiles=self.store.root/'shared/voices/profiles';self.profiles.mkdir(parents=True,exist_ok=True)
  from studio_conversations import Conversations
  self.conversations=Conversations(self)
  from workspace_portable import PortableProjects
  self.portable=PortableProjects(self.store,self.profiles);self.portable.recover()
  from studio_models import Models
  self.models=Models(self.store.root/'models',busy=lambda:self.busy() or self.reserved or bool(getattr(self,'queue',None) and self.queue.protected_owners()))
  from studio_instructions import Instructions
  self.instructions=Instructions(self.store)
  from studio_queue import JobQueue
  self.queue=JobQueue(self)
  if not (self.store.root/'migration.json').exists() or (not allow_migrating and json.loads((self.store.root/'migration.json').read_text(encoding='utf-8')).get('state')!='complete'):raise ValueError('Run maintenance/migrate_workspaces.py while Studio is idle before starting the upgraded backend')
 @contextmanager
 def admission(self,path,workspace=None):
  uploading=path in ('/api/upload','/api/assets/upload','/api/chat/upload')
  if uploading:
   doc=self.store.get(workspace)
   if doc.get('archived') or doc.get('deleted'):raise ValueError('Restore the project before uploading')
   with self.gate:
    if workspace in self.store.operation_pins:raise ValueError('Workspace has an active file operation')
    self.store.operation_pins.add(workspace)
  generation=path in ('/api/join','/api/voice/join','/api/chat/send')
  if generation:
   with self.gate:
    if workspace in self.store.operation_pins:raise ValueError('A file operation is active in this project')
    if self.reserved or self.busy(include_warmup=path!='/api/chat/send'):raise ValueError('Another project has an active job. Wait for it to finish.')
    self.reserved=True
  try:
   if generation:
    # An idle image service belongs to its workspace but its GPU allocation is global.
    for instance in list(self.instances.values()):
     if instance.image_service:instance.image_service.stop_for_generation()
   yield
  finally:
   if uploading:self.store.operation_pins.discard(workspace)
   if generation:
    with self.gate:self.reserved=False
 def studio(self,w):
  from studio import Studio
  with self.gate:
   doc=self.store.get(w)
   if doc.get('deleted'):raise ValueError('Project is in trash; restore it first')
   if w not in self.instances:
    self.instances[w]=Studio(self.store.folder(w),shared_profiles=self.profiles);self.instances[w].workspace_id=w
   return self.instances[w]
 def active(self):
  for w,s in list(self.instances.items()):
   active=s.current or s.image_current or s.voice.current
   if active:return dict(workspace=w,id=active)
  return None
 def busy(self,include_warmup=True,include_queue=True):
  from studio_chat import StudioChat
  return bool((include_queue and hasattr(self,'queue') and self.queue.owners()) or (include_warmup and StudioChat._warming) or self.active() or self.conversations.busy() or any(s.chat.busy for s in self.instances.values()) or (hasattr(self,'models') and ((self.models.download and self.models.download['state']=='downloading') or self.models.verification)))
 def publish(self,w):
  """Index completed outputs as distinct immutable assets without losing legacy job compatibility."""
  folder=self.store.folder(w);doc=self.store.get(w);original_metadata={a:json.dumps(row['metadata'],sort_keys=True) for a,row in doc['assets'].items()};changed=False
  records=[]
  for p in (folder/'jobs').glob('*/job.json'):
   try:j=json.loads(p.read_text(encoding='utf-8'))
   except (OSError,ValueError):continue
   if j.get('status')=='completed' and not j.get('settings',{}).get('imported_asset'):
    for file,variant in [('video.mp4','segment'),('combined.mp4','chain')]:
     if (p.parent/file).is_file():records.append((p.parent/file,dict(engine='video',job=j['id'],variant=variant,settings=j['settings']),j['settings'].get('prompt','Video')[:100]))
  for p in (folder/'voices/jobs').glob('*/job.json'):
   try:j=json.loads(p.read_text(encoding='utf-8'))
   except (OSError,ValueError):continue
   if j.get('status')=='completed' and not j.get('settings',{}).get('imported_asset'):
    for file,variant in [('audio.wav','segment'),('combined.wav','chain')]:
     if (p.parent/file).is_file():records.append((p.parent/file,dict(engine='voice',job=j['id'],variant=variant,settings=dict(j['settings'],text=j.get('combined_text',j['settings'].get('text',''))) if variant=='chain' else j['settings']),j['settings'].get('text','Audio')[:100]))
  for p in (folder/'image-jobs').glob('*/job.json'):
   try:j=json.loads(p.read_text(encoding='utf-8'))
   except (OSError,ValueError):continue
   if j.get('status')=='completed' and j.get('image') and (folder/'uploads'/j['image']).is_file():records.append((folder/'uploads'/j['image'],dict(engine='image',job=j['id'],variant='image',legacy_name=j['image'],settings=j['settings']),j['settings'].get('prompt','Image')[:100]))
  legacy_sources={'lexi':ROOT.parent/'Lexi-stills/Lexi.png','canonical':ROOT.parent/'references/canonical/Lexi-approved-2026-10-15.png'}
  used_legacy={value for _,meta,_ in records for value in [meta.get('settings',{}).get('image'),meta.get('settings',{}).get('identity_image')] if value in legacy_sources}
  for alias in used_legacy:
   source=legacy_sources[alias];owned=folder/'uploads'/('legacy-reference-'+alias+'.png')
   legacy_id=uuid.uuid5(uuid.NAMESPACE_URL,w+':'+str(owned.relative_to(folder))).hex
   if legacy_id in doc.get('tombstones',[]):continue
   if source.is_file():
    if not owned.exists():shutil.copy2(source,owned)
    records.insert(0,(owned,dict(engine='upload',legacy_name=alias,legacy_alias=owned.name),'Imported legacy reference · '+alias))
  current=self.instances.get(w)
  uploads_writable=bool(current and current.image_current)
  aliases_in_use={a['id']+Path(a['path']).suffix.lower() for a in doc['assets'].values()}
  for p in (folder/'uploads').iterdir():
   if uploads_writable or p.name in aliases_in_use or p.name.startswith('legacy-reference-'):continue
   if p.is_file() and p.suffix.lower() in ({'.png','.jpg','.jpeg','.webp','.mp4','.mov','.webm','.mkv','.wav','.mp3','.flac','.ogg','.m4a'}|TEXT_FORMATS):records.append((p,dict(engine='upload',legacy_name=p.name),p.name))
  for p,meta,name in records:
   a=uuid.uuid5(uuid.NAMESPACE_URL,w+':'+str(p.relative_to(folder))).hex
   if a in doc['assets']:
    existing=doc['assets'][a]
    if meta.get('engine')=='voice' and meta.get('variant')=='chain' and not existing['metadata'].get('copied_from') and existing['metadata'].get('settings')!=meta['settings']:existing['metadata']['settings']=meta['settings'];changed=True
    continue
   if a in doc.get('tombstones',[]):continue
   kind='images' if p.suffix.lower() in ('.png','.jpg','.jpeg','.webp') else 'audio' if p.suffix.lower() in ('.wav','.mp3','.flac','.ogg','.m4a') else 'documents' if p.suffix.lower() in TEXT_FORMATS else 'videos'
   target=folder/'assets'/kind/a/('media'+p.suffix.lower());target.parent.mkdir(parents=True,exist_ok=True)
   if not target.exists():
    try:os.link(p,target)
    except OSError:shutil.copyfile(p,target)
   meta['compat_path']=str(p.relative_to(folder));sha=digest(target)
   if sha!=digest(p):raise ValueError('Asset publication verification failed')
   doc['assets'][a]=dict(id=a,workspace=w,name=name,kind=kind,path=str(target.relative_to(folder)),bytes=target.stat().st_size,sha256=sha,created=time.time(),trashed=False,tags=[],favorite=False,metadata=meta);changed=True
  aliases={a['metadata'].get('legacy_name'):a['id'] for a in doc['assets'].values() if a['metadata'].get('legacy_name')}
  aliases.update({a['metadata']['legacy_alias']:a['id'] for a in doc['assets'].values() if a['metadata'].get('legacy_alias')})
  aliases.update({a['id']+Path(a['path']).suffix.lower():a['id'] for a in doc['assets'].values()})
  for a in doc['assets'].values():
   if a['metadata'].get('copied_from'):continue
   settings=a['metadata'].get('settings',{});required=list((settings.get('context_snapshot') or {}).get('references',[]))
   from studio_characters import asset_ids
   required += [r['speech']['recording'] for r in (settings.get('scene_snapshot') or {}).get('roles',[]) if r.get('speech',{}).get('recording')]
   required += [ref for row in (settings.get('character_snapshot') or {}).get('characters',[]) for ref in asset_ids(row)]
   for reference in [settings.get('image'),settings.get('video'),settings.get('identity_image'),*settings.get('images',[]),*[r['image'] for r in settings.get('character_guidance',[])]]:
    if reference in aliases:required.append(aliases[reference])
   inputs={role:aliases[value] for role in ('image','identity_image','video') if (value:=settings.get(role)) in aliases}
   if settings.get('images'):inputs['images']=[aliases[x] for x in settings['images'] if x in aliases]
   planned_recordings=[r['speech']['recording'] for r in (settings.get('scene_snapshot') or {}).get('roles',[]) if r.get('speech',{}).get('recording')]
   if planned_recordings:inputs['planned_scene_recordings']=planned_recordings
   if settings.get('character_guidance'):inputs['character_guidance']=[aliases[r['image']] for r in settings['character_guidance'] if r['image'] in aliases]
   if inputs and a['metadata'].get('inputs')!=inputs:a['metadata']['inputs']=inputs;changed=True
   required=sorted(set(x for x in required if x!=a['id'] and x not in doc.get('tombstones',[])))
   if a['metadata'].get('required',[])!=required and settings:a['metadata']['required']=required;changed=True
  if changed:
   # File hashing happens outside the commit lock. Merge into the latest manifest:
   # a concurrent context edit, snapshot or purge must never be overwritten by a scan.
   with self.store.lock:
    current=self.store.get(w)
    for a,row in doc['assets'].items():
     if a in current.get('tombstones',[]):continue
     if a not in original_metadata:
      if a not in current['assets'] and (folder/row['path']).is_file():current['assets'][a]=row
     elif a in current['assets'] and json.dumps(current['assets'][a]['metadata'],sort_keys=True)==original_metadata[a]:current['assets'][a]['metadata']=row['metadata']
    self.store.save(current)
  return self.store.assets(w)
 def tree_state(self):
  projects=[]
  for doc in self.store.listing():
   w=doc['id'];jobs=[]
   if not doc.get('archived') and not doc.get('deleted') and w not in self.store.operation_pins:self.publish(w);doc=self.store.get(w)
   for kind,sub in [('videos','jobs'),('images','image-jobs'),('audio','voices/jobs')]:
    for path in (self.store.folder(w)/sub).glob('*/job.json'):
     try:
      row=json.loads(path.read_text(encoding='utf-8'))
      if row.get('status')!='completed' and not row.get('hidden'):jobs.append(dict(id=row['id'],kind=kind,name=str(row.get('settings',{}).get('prompt') or row.get('settings',{}).get('text') or 'Generation')[:80],action=row.get('settings',{}).get('action'),status=row.get('status','unknown'),checkpoint_capable=row.get('checkpoint_capable',False),phase=row.get('phase',''),progress=row.get('progress')))
     except (OSError,ValueError,KeyError):continue
   from voice_studio import VoiceStudio
   reader=VoiceStudio.__new__(VoiceStudio);reader.local_profiles=self.store.folder(w)/'voices/profiles';voices=reader.profile_listing(True) if reader.local_profiles.exists() else []
   projects.append(dict(id=w,name=doc['name'],archived=doc['archived'],deleted=doc['deleted'],archive_file=doc.get('archive_file'),assets=[{k:a[k] for k in ('id','name','kind','bytes','path','trashed','metadata')} for a in self.store.assets(w)+self.store.assets(w,True)],chats=self.conversations.listing(w),voices=voices,characters=list(doc.get('characters',{}).values()),jobs=jobs))
  return dict(projects=projects)
 def workspace_state(self,w):
  self.publish(w);doc=self.store.get(w)
  return dict(workspace={k:v for k,v in doc.items() if k not in ('assets','snapshots')},workspaces=[{k:x[k] for k in ('id','name','type','archived','deleted')} for x in self.store.listing()],assets=self.store.assets(w),trash=self.store.assets(w,True),snapshots=[{k:s[k] for k in ('id','name','created')} for s in doc['snapshots'].values()],global_active=self.active(),global_busy=self.busy(),models=self.models.info(),operations=[{k:j.get(k) for k in ('id','kind','state','cancel_requested')} for p in (self.store.root/'operations').glob('*.json') if (j:=json.loads(p.read_text(encoding='utf-8'))).get('state') not in ('complete','exported','aborted') and w in (j.get('workspace'),j.get('source'),j.get('destination'))])

 def use_asset(self,w,a):
  row,path=self.store.asset(w,a);folder=self.store.folder(w);meta=row.get('metadata',{})
  if row['kind']=='images' or row['kind']=='videos':
   name=a+path.suffix.lower();upload=folder/'uploads'/name
   if not upload.exists():
    try:os.link(path,upload)
    except OSError:shutil.copyfile(path,upload)
   if row['kind']=='images':return dict(image=name)
   from studio import video_seconds
   job=uuid.uuid5(uuid.NAMESPACE_URL,w+':video-compat:'+a).hex;target=folder/'jobs'/job;target.mkdir(exist_ok=True)
   if not (target/'video.mp4').exists():
    try:os.link(path,target/'video.mp4')
    except OSError:shutil.copy2(path,target/'video.mp4')
   settings=dict(prompt=row['name'],quality='imported',size='source',seed=0,seconds=video_seconds(path),resolution=meta.get('settings',{}).get('resolution',[640,576]),imported_asset=a,**{k:v for k,v in meta.get('settings',{}).items() if k in ('appearance','identity_mode','character_snapshot','audio_mode','scene_snapshot')})
   inputs=meta.get('inputs',{});identity=inputs.get('identity_image') or inputs.get('image')
   if identity and self.store.get(w)['assets'].get(identity,{}).get('kind')=='images':settings['identity_image']=self.use_asset(w,identity)['image']
   elif settings.get('identity_mode'):settings['identity_mode']=False
   atomic(target/'job.json',dict(id=job,status='completed',settings=settings,elapsed=0))
   return dict(video=name,job=job)
  if row['kind']=='audio':
   from studio import run_media
   job=uuid.uuid5(uuid.NAMESPACE_URL,w+':audio-compat:'+a).hex;target=folder/'voices/jobs'/job;target.mkdir(exist_ok=True)
   if not (target/'audio.wav').exists():run_media(['-i',str(path),'-ac','1','-ar','24000','-c:a','pcm_s16le',str(target/'audio.wav')])
   settings=dict(meta.get('settings',dict(action='join',text=row['name'],profile=None)),imported_asset=a);atomic(target/'job.json',dict(id=job,status='completed',settings=settings,elapsed=0))
   return dict(audio=job)
  if path.suffix.lower()=='.pdf':
   from studio_pdf import extract_pdf
   pdf=extract_pdf(path,folder/'context/pdf-cache'/(row['sha256']+'-v1.json'));return dict(text='PDF extracted text (charts/layout not analyzed):\n'+pdf['text'])
  return dict(text=path.read_text(encoding='utf-8'))
 def mutate_asset(self,w,value):
  self.store.pins=self.queue.protected_owners()|{x for x,s in self.instances.items() if s.current or s.image_current or s.voice.current or s.chat.busy or self.conversations.busy(x)}
  if self.models.download and self.models.download.get('state')=='downloading' and self.models.download.get('workspace'):self.store.pins.add(self.models.download['workspace'])
  action=value.get('action');a=value.get('id')
  if w in self.store.pins and value.get('action')!='use':raise ValueError('Wait for the active workspace job')
  if action in ('batch-trash','batch-restore'):
   result=self.store.batch_trash(w,value.get('ids'),action=='batch-restore')
   for id in value['ids']:self.sync_compatibility(w,self.store.get(w)['assets'][id])
   return result
  if action=='duplicate':
   row,path=self.store.asset(w,a);meta=json.loads(json.dumps(row['metadata']))
   for field in ('job','compat_path','legacy_name','legacy_alias'):meta.pop(field,None)
   return self.store.import_file(w,path,value.get('name') or row['name']+' copy',meta)
  if action=='edit':return self.store.edit_asset(w,a,value)
  if action in ('trash','restore'):
   row=self.store.trash(w,a,action=='restore');self.sync_compatibility(w,row);return row
  if action=='purge':self.store.purge(w,a);return {'ok':True}
  if action in ('copy','move'):
   return self.store.transfer(w,a,value.get('destination'),action=='move',include=value.get('include',True),operation_id=value.get('operation'))
  if action=='use':return self.use_asset(w,a)
  raise ValueError('Unknown asset action')

 def capture(self,w,engine,value):
  if engine=='video':
   from studio_scene import capture
   value=dict(value);value.pop('scene_snapshot',None)
   value=capture(self,w,value)
  doc=self.store.get(w);context=doc['context'];result=dict(value)
  result.pop('character_snapshot',None);result.pop('character_guidance',None)
  if engine=='video' and 'scene' not in value:result.pop('scene_snapshot',None)
  if engine in ('image','video'):result['user_prompt']=value.get('prompt','')
  if engine=='video':
   result['audio_mode']=value.get('audio_mode','silent')
   if result['audio_mode'] not in ('silent','generated'):raise ValueError('Choose Silent or Generated sound')
  if value.get('proposal_workspace',w)!=w:raise ValueError('Proposal belongs to another workspace; reopen it there')
  if value.get('context_revision',context['revision'])!=context['revision']:raise ValueError('Project context changed; preview the request again')
  if engine in ('video','image'):
   legacy={'lexi':ROOT.parent/'Lexi-stills/Lexi.png','canonical':ROOT.parent/'references/canonical/Lexi-approved-2026-10-15.png'}
   for field in ('image','identity_image'):
    if result.get(field) in legacy:
     imported=self.store.import_file(w,legacy[result[field]],name='Imported reference');result[field]=self.use_asset(w,imported['id'])['image']
  enabled=value.get('use_context',True)
  if type(enabled) is not bool:raise ValueError('Invalid context choice')
  refs=[]
  if enabled:
   refs=context['references']
   if engine in ('video','image'):
    prompt=value.get('prompt','')
    extra='\n'.join(x for x in [('Project brief: '+context['brief']) if context['brief'] else '',('Style: '+context['style']) if context['style'] else ''] if x)
    result['user_prompt']=prompt;result['prompt']=(extra+'\n'+prompt).strip()
    images=[self.use_asset(w,a)['image'] for a in refs]
    if engine=='image':
     result['images']=list(dict.fromkeys([*value.get('images',[]),*images]))
     if len(result['images'])>4:raise ValueError('Combined project and explicit references exceed four; disable project context or choose fewer references')
    elif images and not result.get('image') and not value.get('continue_from'):result['image']=images[0]
   elif engine=='voice' and not value.get('profile') and context.get('voice'):result['profile']=context['voice']
  from studio_characters import enrich
  result=enrich(self,w,engine,result,value)
  slot=('voice-design' if value.get('action')=='design' else 'voice-read') if engine=='voice' else 'writing' if engine=='chat' else engine
  if slot in self.models.state['selected']:result['model_spec']=self.models.selected(slot)
  if engine=='voice' and value.get('action')=='read':
   from sound_script import parse_script,sound_cues
   result['sound_plan']=parse_script(value.get('text',''))
   if sound_cues(result['sound_plan']):
    if 'sound-effects' not in self.models.state['selected']:raise ValueError('Install and select the local sound-effects model in Settings → Audio first')
    result['sound_model_spec']=self.models.selected('sound-effects')
   else:result['sound_model_spec']=None
  if engine=='chat':result['behavior_layers']=self.instructions.capture(w)
  result['workspace_id']=w;result['context_snapshot']=dict(revision=context['revision'],brief=context['brief'] if enabled else '',style=context['style'] if enabled else '',references=refs,voice=context.get('voice'),enabled=enabled)
  if result.get('character_snapshot'):result['context_snapshot']['character_snapshot']=result['character_snapshot']
  return result

 def sync_compatibility(self,w,asset):
  meta=asset.get('metadata',{});folder=self.store.folder(w)
  for base in (folder/'jobs',folder/'voices/jobs',folder/'image-jobs'):
   for file in base.glob('*/job.json'):
    job=json.loads(file.read_text(encoding='utf-8'));imported=job.get('settings',{}).get('imported_asset')==asset['id'];original=job['id']==meta.get('job')
    if not imported and not original:continue
    if imported:job['hidden']=asset.get('trashed',False)
    elif meta.get('variant')=='chain':
     if asset.get('trashed'):job['combined']=False;job.pop('combined_text',None)
     else:
      job['combined']=True
      if meta.get('engine')=='voice':job['combined_text']=meta.get('settings',{}).get('text','')
    else:job['hidden']=asset.get('trashed',False)
    atomic(file,job)
