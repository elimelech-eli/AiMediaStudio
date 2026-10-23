from studio_attachments import DOCUMENTS as TEXT_FORMATS
"""Independent project branches and checksum-verified portable ZIP projects."""
import json,os,shutil,time,uuid,zipfile
from pathlib import Path
from workspace_store import atomic,digest,key,contained,identifier,OperationCancelled

class PortableProjects:
 def __init__(self,store,profiles):self.store=store;self.profiles=Path(profiles);self.exports=store.root/'exports';self.exports.mkdir(exist_ok=True)
 def build(self,w,name,snapshot=None,chat=False,intent='branch'):
  operation=key();self.store.active_operations.add(operation)
  try:return self._build(w,name,snapshot,chat,intent,operation)
  except Exception:
   path=self.store.root/'operations'/f'{operation}.json'
   if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('state')=='copying':self.abort(operation)
   raise
  finally:self.store.active_operations.discard(operation)
 def _build(self,w,name,snapshot=None,chat=False,intent='branch',operation=None):
  store=self.store
  if w in store.operation_pins:raise ValueError('A file operation is already active in this workspace')
  source=store.get(w)
  anchor=source['snapshots'].get(snapshot) if snapshot else store.snapshot(w,'Temporary portable operation',include_chat=chat)
  if not anchor:raise ValueError('Snapshot not found')
  total=self.estimate(w,anchor['id'])['bytes']
  if shutil.disk_usage(store.root).free<total*(2 if intent=='export' else 1)+64*1024**2:
   if not snapshot:store.remove_snapshot(w,anchor['id'])
   raise ValueError('Insufficient disk space for a verified portable copy')
  op=operation or key();new=key();stage=store.root/'operations'/op/'portable';stage.mkdir(parents=True)
  journal=dict(id=op,kind='portable',intent=intent,state='copying',workspace=w,destination=new,name=name,anchor=anchor['id'],temporary_anchor=not bool(snapshot),chat=chat);atomic(store.root/'operations'/f'{op}.json',journal)
  store.operation_pins.add(w)
  doc=dict(source,id=new,type='project',name=str(name or source['name'])[:100],archived=False,deleted=False,created=time.time(),assets={},snapshots={},context=json.loads(json.dumps(anchor['context'])),lineage=dict(workspace=w,snapshot=anchor['id']))
  doc['chats']={key():dict(row) for row in anchor.get('chats',{}).values() if not row.get('trashed')} if chat else {}
  for chat_id,row in doc['chats'].items():row['id']=chat_id
  doc['chat_behavior']=json.loads(json.dumps(anchor.get('chat_behavior',dict(text='',name='',enabled=True,revision=0))))
  doc.pop('archive_file',None);doc.pop('archive_sha256',None)
  doc.pop('tombstones',None);doc.pop('_temporary',None);mapping={a:key() for a in anchor['assets']};voices={}
  for row in anchor['assets'].values():
   metadata=row.get('metadata',{});profile=metadata.get('settings',{}).get('profile')
   if profile:voices[profile]=key()
  if doc['context'].get('voice'):voices.setdefault(doc['context']['voice'],key())
  for profile in anchor.get('voice_profiles',[]):voices.setdefault(profile,key())
  from studio_characters import remap_character,remap_settings,voice_ids
  for asset in anchor['assets'].values():
   for profile in voice_ids(asset.get('metadata',{}).get('settings',{})):voices.setdefault(profile,key())
  for row in anchor.get('characters',{}).values():
   for version in [row,*row.get('history',[])]:
    if version.get('voice'):voices.setdefault(version['voice'],key())
  # Historical completed recipes may reference a voice the user has permanently deleted.
  voices={old:new for old,new in voices.items() if (store.folder(w)/'voices/profiles'/old/'profile.json').is_file() or (self.profiles/old/'profile.json').is_file()}
  doc['characters']={id:remap_character(row,mapping,voices) for id,row in anchor.get('characters',{}).items()}
  for a,row in anchor['assets'].items():
   path=contained(store.folder(w),store.folder(w)/row['path']);asset_id=mapping[a];relative=f"assets/{row['kind']}/{asset_id}/media{path.suffix.lower()}";out=stage/relative;out.parent.mkdir(parents=True,exist_ok=True)
   if digest(path)!=row['sha256']:raise ValueError('Source asset changed or is missing; no project published')
   store.copy_file(path,out,op)
   if digest(out)!=row['sha256']:raise ValueError('Branch verification failed')
   metadata=json.loads(json.dumps(row.get('metadata',{})));metadata.pop('compat_path',None);metadata.pop('legacy_name',None);metadata.pop('legacy_alias',None);metadata['copied_from']=dict(workspace=w,asset=a);metadata['required']=[mapping[x] for x in metadata.get('required',[]) if x in mapping]
   metadata['inputs']={role:([mapping[x] for x in value if x in mapping] if isinstance(value,list) else mapping.get(value)) for role,value in metadata.get('inputs',{}).items()}
   settings=metadata.get('settings',{})
   if settings.get('profile') in voices:settings['profile']=voices[settings['profile']]
   remap_settings(settings,mapping,voices)
   settings['workspace_id']=new
   captured=settings.get('context_snapshot')
   if captured:captured['references']=[mapping[x] for x in captured.get('references',[]) if x in mapping]
   doc['assets'][asset_id]=dict(row,id=asset_id,workspace=new,path=relative,metadata=metadata,trashed=False)
  doc['context']['references']=[mapping[a] for a in doc['context']['references'] if a in mapping]
  if doc['context'].get('voice') in voices:doc['context']['voice']=voices[doc['context']['voice']]
  for old,new_voice in voices.items():
   profile_root=store.folder(w)/'voices/profiles'/identifier(old)
   if not (profile_root/'profile.json').is_file():profile_root=self.profiles/identifier(old)
   profile=json.loads((profile_root/'profile.json').read_text(encoding='utf-8'));audio=profile_root/'reference.wav'
   if digest(audio)!=profile['sha256']:raise ValueError('Voice profile reference checksum mismatch')
   target=stage/'voices/profiles'/new_voice;target.mkdir(parents=True);shutil.copyfile(audio,target/'reference.wav');profile['id']=new_voice;atomic(target/'profile.json',profile)
  for sub in ('jobs','image-jobs','uploads','voices/jobs','context','conversations','snapshots','trash'):(stage/sub).mkdir(parents=True,exist_ok=True)
  if chat and anchor.get('chat') is not None:atomic(stage/'conversations/chat.json',anchor['chat'])
  atomic(stage/'workspace.json',doc);atomic(stage/'requirements.json',dict(models_bundled=False,engines=['video','image','voice','writing'],note='Install compatible engines/models on the receiving machine. Saved recipes are historical; imports do not run jobs.'))
  journal['state']='verified';atomic(store.root/'operations'/f'{op}.json',journal);store.failpoint('portable_verified');return journal,stage,doc
 def publish(self,journal,stage,doc):
  store=self.store;target=store.folder(doc['id'])
  if not target.exists():os.replace(stage,target)
  store.index(doc);journal['state']='complete';atomic(store.root/'operations'/f"{journal['id']}.json",journal)
  if journal.get('temporary_anchor'):store.remove_snapshot(journal['workspace'],journal['anchor'])
  store.operation_pins.discard(journal['workspace']);return doc
 def branch(self,w,name,snapshot=None,chat=False):
  try:
   journal,stage,doc=self.build(w,name,snapshot,chat);return self.publish(journal,stage,doc)
  except OperationCancelled:raise
 def export(self,w,snapshot=None,chat=False):
  try:
   journal,stage,doc=self.build(w,self.store.get(w)['name'],snapshot,chat,intent='export');return self.finish_export(journal,stage)
  except OperationCancelled:raise
 def finish_export(self,journal,stage):
  self.store.active_operations.add(journal['id'])
  try:return self._finish_export(journal,stage)
  finally:self.store.active_operations.discard(journal['id'])
 def _finish_export(self,journal,stage):
  w=journal['workspace'];target=self.exports/(journal['id']+'.zip');temporary=target.with_suffix('.partial')
  with zipfile.ZipFile(temporary,'w',zipfile.ZIP_STORED,allowZip64=True) as archive:
   for file in stage.rglob('*'):
    if file.is_file():archive.write(file,file.relative_to(stage).as_posix())
  with zipfile.ZipFile(temporary) as archive:
   if archive.testzip():raise ValueError('ZIP verification failed; source remains unchanged')
   import hashlib
   for row in json.loads((stage/'workspace.json').read_text(encoding='utf-8'))['assets'].values():
    with archive.open(row['path']) as stream:
     h=hashlib.sha256()
     for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    if h.hexdigest()!=row['sha256']:raise ValueError('Archived asset checksum mismatch')
  os.replace(temporary,target);journal.update(state='exported',export=target.name);atomic(self.store.root/'operations'/f"{journal['id']}.json",journal)
  if journal.get('temporary_anchor'):self.store.remove_snapshot(w,journal['anchor'])
  size=target.stat().st_size
  shutil.rmtree(contained(self.store.root,stage))
  self.store.operation_pins.discard(w);return dict(file=target.name,bytes=size)
 def import_zip(self,source,name=None):
  source=Path(source);op=key();stage=self.store.root/'operations'/op/'incoming';stage.mkdir(parents=True)
  with zipfile.ZipFile(source) as archive:
   entries=archive.infolist();total=sum(x.file_size for x in entries)
   if len(entries)>50000 or total>40*1024**3 or shutil.disk_usage(self.store.root).free<total+64*1024**2:raise ValueError('Project archive exceeds safe import size or available disk space')
   names=set()
   for entry in entries:
    normalized=Path(entry.filename).as_posix().casefold()
    if normalized in names:raise ValueError('Duplicate archive path')
    names.add(normalized)
    if '\\' in entry.filename or ':' in entry.filename or entry.filename.startswith('/') or '..' in Path(entry.filename).parts or (entry.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe project archive path')
    if any(part.endswith(('.', ' ')) or part.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]} for part in Path(entry.filename).parts):raise ValueError('Unsafe Windows archive filename')
    path=contained(stage,stage/entry.filename)
    if entry.is_dir():path.mkdir(parents=True,exist_ok=True);continue
    path.parent.mkdir(parents=True,exist_ok=True)
    with archive.open(entry) as incoming,path.open('wb') as outgoing:shutil.copyfileobj(incoming,outgoing,1024*1024)
  doc=json.loads((stage/'workspace.json').read_text(encoding='utf-8'))
  if doc.get('version')!=1 or not isinstance(doc.get('assets'),dict):raise ValueError('Unsupported project format')
  identifier(doc['id'])
  if 'chat_behavior' in doc:
   from studio_instructions import validate
   layer=validate(doc['chat_behavior'])
   revision=doc['chat_behavior'].get('revision',0)
   if type(revision) is not int or revision<0:raise ValueError('Invalid instruction revision')
   doc['chat_behavior']=dict(layer,revision=revision)
  context=doc.get('context',{})
  if not isinstance(context.get('brief'),str) or len(context['brief'])>8000 or not isinstance(context.get('style'),str) or len(context['style'])>2000 or not isinstance(context.get('references'),list) or len(context['references'])>4:raise ValueError('Invalid imported project context')
  identifier(context.get('voice')) if context.get('voice') else None
  for a,row in doc['assets'].items():
   identifier(a)
   if row.get('id')!=a or row.get('kind') not in ('images','videos','audio','documents') or not isinstance(row.get('name'),str) or not isinstance(row.get('metadata'),dict):raise ValueError('Invalid imported asset record')
   path=contained(stage,stage/row['path'])
   formats={'images':{'.png','.jpg','.jpeg','.webp'},'videos':{'.mp4','.mov','.webm','.mkv'},'audio':{'.wav','.mp3','.flac','.ogg','.m4a'},'documents':TEXT_FORMATS}
   if path.suffix.lower() not in formats[row['kind']]:raise ValueError('Unsupported imported media extension')
   if not path.is_relative_to(stage/'assets') or not path.is_file() or path.stat().st_size!=row['bytes'] or digest(path)!=row['sha256']:raise ValueError('Project asset verification failed')
   if any(x not in doc['assets'] for x in row.get('metadata',{}).get('required',[])):raise ValueError('Missing required project dependency')
  if any(x not in doc['assets'] for x in doc['context']['references']):raise ValueError('Missing project context reference')
  for profile_file in (stage/'voices/profiles').glob('*/profile.json'):
   profile=json.loads(profile_file.read_text(encoding='utf-8'));identifier(profile['id'])
   if profile_file.parent.name!=profile['id'] or digest(profile_file.parent/'reference.wav')!=profile['sha256']:raise ValueError('Invalid embedded voice profile')
  from studio_characters import validate
  characters=doc.get('characters',{})
  if not isinstance(characters,dict) or len(characters)>1000:raise ValueError('Invalid character library')
  for id,row in characters.items():
   identifier(id)
   if row.get('id')!=id or type(row.get('revision')) is not int or row['revision']<1 or not isinstance(row.get('history',[]),list):raise ValueError('Invalid character version')
   for version in [row,*row.get('history',[])]:validate(version,doc,lambda voice:(stage/'voices/profiles'/identifier(voice)/'profile.json').is_file())
  chatfile=stage/'conversations/chat.json'
  if chatfile.exists():
   if chatfile.stat().st_size>2*1024*1024:raise ValueError('Imported conversation is too large')
   messages=json.loads(chatfile.read_text(encoding='utf-8'))
   if not isinstance(messages,list) or len(messages)>100 or any(not isinstance(m,dict) or m.get('role') not in ('user','assistant') or not isinstance(m.get('content'),str) for m in messages):raise ValueError('Invalid imported conversation')
  for chat_id,row in doc.get('chats',{}).items():
   identifier(chat_id)
   if row.get('id')!=chat_id or not isinstance(row.get('name'),str) or not isinstance(row.get('messages'),list) or len(row['messages'])>100 or any(not isinstance(m,dict) or m.get('role') not in ('user','assistant') or not isinstance(m.get('content'),str) for m in row['messages']):raise ValueError('Invalid named conversation')
  # Treat verified imported contents as a temporary isolated source and run the normal remapping branch path.
  incoming_id=key();doc['id']=incoming_id;doc['name']=name or doc.get('name','Imported project');doc['deleted']=False;doc['archived']=False;doc['snapshots']={};doc['_temporary']=True
  for row in doc['assets'].values():row['workspace']=incoming_id
  temp=self.store.folder(incoming_id);os.replace(stage,temp);atomic(temp/'workspace.json',doc);self.store.index(doc)
  try:result=self.branch(incoming_id,doc['name'],chat=chatfile.exists() or bool(doc.get('chats')))
  finally:
   # This is a newly created verified staging workspace, never an existing user workspace.
   shutil.rmtree(temp)
   from contextlib import closing
   import sqlite3
   with closing(sqlite3.connect(self.store.root/'catalog.sqlite')) as db,db:db.execute('DELETE FROM workspaces WHERE id=?',(incoming_id,))
  return result
 def recover(self):
  for p in (self.store.root/'operations').glob('*.json'):
   journal=json.loads(p.read_text(encoding='utf-8'))
   if journal['id'] in self.store.active_operations:continue
   if journal.get('kind')=='portable' and journal.get('state')=='copying':self.abort(journal['id']);continue
   if journal.get('kind')=='portable' and journal.get('state')=='verified':
    stage=self.store.root/'operations'/journal['id']/'portable';target=self.store.folder(journal['destination']);folder=target if target.exists() else stage;doc=json.loads((folder/'workspace.json').read_text(encoding='utf-8'))
    for row in doc['assets'].values():
     if digest(contained(folder,folder/row['path']))!=row['sha256']:raise ValueError('Interrupted branch has corrupt media; source retained')
    if journal.get('intent')=='export':self.finish_export(journal,stage)
    else:self.publish(journal,stage,doc)

 def abort(self,operation):
  path=self.store.root/'operations'/f'{identifier(operation)}.json';journal=json.loads(path.read_text(encoding='utf-8'));stage=contained(self.store.root,self.store.root/'operations'/operation/'portable')
  if stage.exists():shutil.rmtree(stage)
  if journal.get('temporary_anchor'):
   try:self.store.remove_snapshot(journal['workspace'],journal['anchor'])
   except ValueError:pass
  journal['state']='aborted';atomic(path,journal);self.store.operation_pins.discard(journal['workspace'])

 def estimate(self,w,snapshot=None):
  doc=self.store.get(w);anchor=doc['snapshots'].get(snapshot) if snapshot else None
  rows=anchor['assets'] if anchor else {a:r for a,r in doc['assets'].items() if not r.get('trashed') and not r.get('metadata',{}).get('pending_operation')}
  context=anchor['context'] if anchor else doc['context'];profiles=set((anchor or {}).get('voice_profiles',[]))
  profiles.update(r.get('metadata',{}).get('settings',{}).get('profile') for r in rows.values())
  if context.get('voice'):profiles.add(context['voice'])
  if not anchor:profiles.update(p.parent.name for p in (self.store.folder(w)/'voices/profiles').glob('*/profile.json'))
  size=sum(r['bytes'] for r in rows.values())
  for id in profiles:
   if not id:continue
   folder=self.store.folder(w)/'voices/profiles'/identifier(id)
   if not (folder/'profile.json').is_file():folder=self.profiles/id
   size+=sum((folder/name).stat().st_size for name in ('profile.json','reference.wav') if (folder/name).is_file())
  return {'assets':len(rows),'bytes':size,'models_bundled':False}
