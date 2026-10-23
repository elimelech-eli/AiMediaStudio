from studio_attachments import DOCUMENTS as TEXT_FORMATS
"""Project-owned immutable assets. Manifests are authoritative; SQLite is a rebuildable index."""
import hashlib,json,os,re,shutil,sqlite3,threading,time,uuid
from pathlib import Path
from contextlib import closing

class OperationCancelled(InterruptedError):
 def __init__(self,operation):self.operation=operation;super().__init__('Copy cancelled; source files remain unchanged')

def key():return uuid.uuid4().hex

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def atomic(path,value):
 from studio_files import atomic_json
 return atomic_json(path,value)

def identifier(value):
 if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{32}|free-work',value):raise ValueError('Invalid workspace/asset ID')
 return value

def contained(root,path):
 root=Path(root).resolve();path=Path(path)
 if not path.resolve().is_relative_to(root):raise ValueError('Path leaves its workspace')
 cursor=path
 while cursor!=root:
  if cursor.is_symlink() or cursor.is_junction():raise ValueError('Filesystem links are not supported')
  if cursor.parent==cursor:raise ValueError('Invalid path')
  cursor=cursor.parent
 return path

class WorkspaceStore:
 def __init__(self,root,failpoint=lambda phase:None):
  self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self.failpoint=failpoint;self.pins=set();self.operation_pins=set();self.cancelled=set();self.active_operations=set();self.recovery_errors=[]
  (self.root/'operations').mkdir(exist_ok=True);(self.root/'projects').mkdir(exist_ok=True);(self.root/'shared/voices').mkdir(parents=True,exist_ok=True)
  if not (self.root/'free-work/workspace.json').exists():self._create('free-work','Free work','free')
  self.rebuild();self.recover()
 def folder(self,w):return contained(self.root,self.root/('free-work' if identifier(w)=='free-work' else 'projects/'+w))
 def get(self,w):
  try:return json.loads((self.folder(w)/'workspace.json').read_text(encoding='utf-8'))
  except FileNotFoundError:raise ValueError('Workspace not found')
 def save(self,w):
  with self.lock:
   atomic(self.folder(w['id'])/'workspace.json',w);self.index(w)
 def index(self,w):
  with closing(sqlite3.connect(self.root/'catalog.sqlite')) as db, db:
   db.execute('PRAGMA foreign_keys=ON');db.execute('CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, document TEXT NOT NULL)')
   db.execute('INSERT OR REPLACE INTO workspaces VALUES(?,?)',(w['id'],json.dumps(w)))
 def rebuild(self):
  with self.lock:
   with closing(sqlite3.connect(self.root/'catalog.sqlite')) as db, db:
    db.execute('CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, document TEXT NOT NULL)');db.execute('DELETE FROM workspaces')
    for path in [self.root/'free-work/workspace.json',*(self.root/'projects').glob('*/workspace.json')]:
     if path.exists():
      w=json.loads(path.read_text(encoding='utf-8'));db.execute('INSERT INTO workspaces VALUES(?,?)',(w['id'],json.dumps(w)))
 def listing(self):
  with closing(sqlite3.connect(self.root/'catalog.sqlite')) as db, db:return [doc for row in db.execute('SELECT document FROM workspaces ORDER BY id') if not (doc:=json.loads(row[0])).get('_temporary')]
 def _create(self,w,name,kind='project'):
  folder=self.folder(w);folder.mkdir(parents=True,exist_ok=True)
  for sub in ('assets/images','assets/videos','assets/audio','assets/documents','jobs','image-jobs','uploads','voices/jobs','voices/profiles','context','conversations','snapshots','trash'):(folder/sub).mkdir(parents=True,exist_ok=True)
  row=dict(id=w,name=name,type=kind,archived=False,deleted=False,version=1,created=time.time(),context=dict(revision=0,brief='',style='',references=[],voice=None),assets={},snapshots={})
  atomic(folder/'workspace.json',row);return row
 def create(self,name):
  if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise ValueError('Project name must be 1–100 characters')
  with self.lock:
   row=self._create(key(),name.strip());self.index(row);return row
 def update(self,w,changes):
  with self.lock:
   row=self.get(w)
   if row['id']=='free-work' and any(k in changes for k in ('deleted','archived','name')):raise ValueError('Free work cannot be renamed, archived or deleted')
   if w in (self.pins|self.operation_pins):raise ValueError('Workspace has an active job')
   if 'name' in changes:
    name=changes['name']
    if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise ValueError('Invalid project name')
    row['name']=name.strip()
   for field in ('archived','deleted'):
    if field in changes:
     if type(changes[field]) is not bool:raise ValueError('Invalid project state')
     row[field]=changes[field]
   self.save(row);return row
 def assets(self,w,trash=False):return [a for a in self.get(w)['assets'].values() if bool(a.get('trashed'))==trash and not a.get('metadata',{}).get('pending_operation')]
 def asset(self,w,a,trash=False):
  row=self.get(w)['assets'].get(identifier(a))
  if not row or row.get('metadata',{}).get('pending_operation') or (row.get('trashed') and not trash):raise ValueError('Asset not found in this workspace')
  path=contained(self.folder(w),self.folder(w)/row['path'])
  if not path.is_file():raise ValueError('Asset file is missing')
  return row,path
 def _attach(self,w,row):
  doc=self.get(w);doc['assets'][row['id']]=row;self.save(doc)
 def import_file(self,w,source,name=None,metadata=None,operation=None):
  source=Path(source)
  if source.is_symlink() or source.is_junction() or not source.is_file():raise ValueError('Choose a regular file')
  # Imports arrive through validated Studio media upload routes; documents are UTF-8 text.
  suffix=source.suffix.lower();kind='images' if suffix in ('.png','.jpg','.jpeg','.webp') else 'videos' if suffix in ('.mp4','.mov','.webm','.mkv') else 'audio' if suffix in ('.wav','.mp3','.flac','.ogg','.m4a') else 'documents' if suffix in TEXT_FORMATS else None
  if not kind:raise ValueError('Unsupported asset format')
  op=identifier(operation) if operation else key();journal=self.root/'operations'/f'{op}.json'
  with self.lock:
   if journal.exists():
    old=json.loads(journal.read_text(encoding='utf-8'))
    if old['workspace']!=w:raise ValueError('Operation belongs to another workspace')
    if old['asset']['sha256']!=digest(source):raise ValueError('Operation ID was used for different content')
    if old['state']!='complete':self._recover_one(old)
    found=self.get(w)['assets'].get(old['asset']['id'])
    if not found:raise ValueError('Incomplete copy; source unchanged, retry with a new operation ID')
    return found
   doc=self.get(w)
   if doc.get('deleted') or doc.get('archived'):raise ValueError('Restore the project before adding assets')
   a=key();filename='media'+suffix;relative=f'assets/{kind}/{a}/{filename}';final=contained(self.folder(w),self.folder(w)/relative)
   size=source.stat().st_size
   if shutil.disk_usage(self.root).free<size+64*1024*1024:raise ValueError('Insufficient disk space for a verified copy')
   record=dict(id=a,workspace=w,name=(name or source.name)[:200],kind=kind,path=relative,bytes=size,sha256=digest(source),created=time.time(),trashed=False,tags=[],favorite=False,metadata=metadata or {})
   stage=self.folder(w)/'jobs'/('import-'+op)/filename
   job=dict(id=op,kind='import',workspace=w,asset=record,stage=str(stage.relative_to(self.folder(w))),state='copying')
   atomic(journal,job)
  stage.parent.mkdir(parents=True,exist_ok=True);self.copy_file(source,stage,(metadata or {}).get('pending_operation',op))
  if digest(stage)!=record['sha256']:raise ValueError('Copy verification failed; source unchanged')
  job['state']='verified';atomic(journal,job);self.failpoint('verified')
  self._recover_one(job);return record
 def _recover_one(self,job):
  with self.lock:
   w=job['workspace'];record=job['asset'];folder=self.folder(w);final=contained(folder,folder/record['path']);stage=contained(folder,folder/job['stage'])
   if job['state']=='copying':
    if not stage.is_file() or digest(stage)!=record['sha256']:return
    job['state']='verified'
   if not final.exists():
    if not stage.exists() or digest(stage)!=record['sha256']:raise ValueError('Incomplete copy requires recovery')
    final.parent.mkdir(parents=True,exist_ok=True);os.replace(stage,final)
   if digest(final)!=record['sha256']:raise ValueError('Published asset checksum mismatch')
   job['state']='published';atomic(self.root/'operations'/f"{job['id']}.json",job);self.failpoint('published')
   self._attach(w,record);job['state']='complete';atomic(self.root/'operations'/f"{job['id']}.json",job)
 def recover(self):
  for p in sorted((self.root/'operations').glob('*.json')):
   job=json.loads(p.read_text(encoding='utf-8'))
   if job['id'] in self.active_operations:continue
   if job.get('kind')=='import' and job.get('state') not in ('complete','aborted'):self._recover_one(job)
   if job.get('kind')=='move' and job.get('state')!='complete':self._finish_move(job)
   if job.get('kind')=='project-purge' and job.get('state')!='complete':self._finish_project_purge(job)
   if job.get('kind')=='purge' and job.get('state')!='complete':self._finish_purge(job)
   if job.get('kind')=='transfer' and job.get('state') not in ('complete','aborted'):
    if job.get('cancel_requested'):self.abort_transfer(job)
    else:self._finish_transfer(job)
 def edit_asset(self,w,a,changes):
  with self.lock:
   row,path=self.asset(w,a,True);doc=self.get(w)
   if 'name' in changes:
    if not isinstance(changes['name'],str) or not 1<=len(changes['name'].strip())<=200:raise ValueError('Invalid asset name')
    row['name']=changes['name'].strip()
   if 'tags' in changes:
    if not isinstance(changes['tags'],list) or len(changes['tags'])>20 or any(not isinstance(t,str) or len(t)>50 for t in changes['tags']):raise ValueError('Invalid tags')
    row['tags']=changes['tags']
   if 'favorite' in changes:row['favorite']=bool(changes['favorite'])
   doc['assets'][a]=row;self.save(doc);return row
 def trash(self,w,a,restore=False):
  with self.lock:
   if w in (self.pins|self.operation_pins):raise ValueError('Wait for the active workspace job')
   doc=self.get(w);row,path=self.asset(w,a,True)
   if not restore:
    from studio_characters import retained_assets
    if a in retained_assets(doc):raise ValueError('This reference is retained by a project character')
    if a in doc['context']['references']:raise ValueError('Remove this reference from project context first')
   # Files stay under stable immutable IDs; trash is a manifest state, avoiding broken snapshots.
   row['trashed']=not restore;doc['assets'][a]=row;self.save(doc);return row
 def purge(self,w,a):
  with self.lock:
   doc=self.get(w);row,path=self.asset(w,a,True)
   if w in (self.pins|self.operation_pins) or not row['trashed']:raise ValueError('Only inactive trashed assets can be purged')
   from studio_characters import retained_assets
   if a in retained_assets(doc):raise ValueError('This reference is retained by a project character')
   if any(a in snap['assets'] for snap in doc['snapshots'].values()):raise ValueError('Asset is retained by a snapshot; remove that snapshot first')
   operation=dict(id=key(),kind='purge',state='prepared',workspace=w,asset=row)
   atomic(self.root/'operations'/f"{operation['id']}.json",operation);self._finish_purge(operation)
 def _finish_purge(self,operation):
  with self.lock:
   w=operation['workspace'];row=operation['asset'];doc=self.get(w)
   doc['assets'].pop(row['id'],None)
   # Completed outputs remain usable when their historical recipe inputs are removed.
   for dependent in doc['assets'].values():
    meta=dependent.get('metadata',{});required=meta.get('required',[])
    if row['id'] in required:
     meta['required']=[a for a in required if a!=row['id']]
     meta['omitted_required']=list(dict.fromkeys([*meta.get('omitted_required',[]),row['id']]))
   if row['id'] not in doc.setdefault('tombstones',[]):doc['tombstones'].append(row['id'])
   self.save(doc);self.failpoint('purge_catalog')
   path=contained(self.folder(w),self.folder(w)/row['path']);path.unlink(missing_ok=True)
   compat=row.get('metadata',{}).get('compat_path')
   if compat:
    legacy=contained(self.folder(w),self.folder(w)/compat);legacy.unlink(missing_ok=True);self.reconcile_chain(legacy)
   self.cleanup_asset_cache(w,row)
   operation['state']='complete';atomic(self.root/'operations'/f"{operation['id']}.json",operation)
 def context(self,w,value):
  with self.lock:
   doc=self.get(w);old=doc['context'];revision=value.get('revision')
   if revision!=old['revision']:raise ValueError('Context changed; reload before saving')
   brief=value.get('brief','');style=value.get('style','');refs=value.get('references',[])
   if not isinstance(brief,str) or not isinstance(style,str) or len(brief)>8000 or len(style)>2000 or not isinstance(refs,list) or len(refs)>4:raise ValueError('Invalid project context')
   for a in refs:
    row,_=self.asset(w,a)
    if row['kind']!='images':raise ValueError('Context references must be images')
   doc['context']=dict(revision=revision+1,brief=brief,style=style,references=refs,voice=value.get('voice'));self.save(doc);return doc['context']
 def snapshot(self,w,name,include_chat=False):
  with self.lock:
   doc=self.get(w);sid=key();assets={a:json.loads(json.dumps(v)) for a,v in doc['assets'].items() if not v.get('trashed') and not v.get('metadata',{}).get('pending_operation')}
   chatfile=self.folder(w)/'conversations/chat.json'
   chat=json.loads(chatfile.read_text(encoding='utf-8')) if include_chat and chatfile.exists() else None
   snap=dict(characters=json.loads(json.dumps(doc.get('characters',{}))),chat_behavior=json.loads(json.dumps(doc.get('chat_behavior',dict(text='',name='',enabled=True,revision=0)))),chats=json.loads(json.dumps(doc.get('chats',{}))) if include_chat else {},id=sid,name=str(name or 'Snapshot')[:100],created=time.time(),context=doc['context'],assets=assets,chat=chat,voice_profiles=[p.parent.name for p in (self.folder(w)/'voices/profiles').glob('*/profile.json')])
   doc['snapshots'][sid]=snap;atomic(self.folder(w)/'snapshots'/f'{sid}.json',snap);self.save(doc);return snap
 def remove_snapshot(self,w,s):
  with self.lock:
   doc=self.get(w)
   if s not in doc['snapshots']:raise ValueError('Snapshot not found')
   del doc['snapshots'][s];self.save(doc);(self.folder(w)/'snapshots'/f'{identifier(s)}.json').unlink(missing_ok=True)

 def _finish_move(self,job):
  with self.lock:
   source=self.get(job['source']);dest=self.get(job['destination']);old=job['source_asset'];copied=job['destination_asset']
   path=contained(self.folder(job['destination']),self.folder(job['destination'])/copied['path'])
   if not path.is_file() or digest(path)!=old['sha256']:raise ValueError('Move destination verification failed; source retained')
   temporary_id=copied['id'];copied=dict(copied,id=old['id']);dest['assets'].pop(temporary_id,None);dest['assets'][old['id']]=copied;self.save(dest)
   self.failpoint('move_published');source['assets'].pop(old['id'],None);source.setdefault('tombstones',[]).append(old['id']);self.save(source)
   original=contained(self.folder(job['source']),self.folder(job['source'])/old['path'])
   if original.exists():original.unlink()
   compat=old.get('metadata',{}).get('compat_path')
   if compat:
    legacy=contained(self.folder(job['source']),self.folder(job['source'])/compat)
    if legacy.is_file():legacy.unlink()
   job['state']='complete';atomic(self.root/'operations'/f"{job['id']}.json",job)

 def transfer_plan(self,w,a,include=True):
  doc=self.get(w);found={}
  def visit(id):
   if id in found:return
   row,path=self.asset(w,id);found[id]=row
   if include:
    for required in row.get('metadata',{}).get('required',[]):
     if required in doc['assets'] and not doc['assets'][required].get('trashed'):visit(required)
  if type(include) is not bool:raise ValueError('Invalid dependency-copy option')
  for root in (a if isinstance(a,list) else [a]):visit(root)
  profile_bytes=0
  from studio_characters import voice_ids
  for profile in set().union(*(voice_ids(r.get('metadata',{}).get('settings',{})) for r in found.values())):
   folder=self.folder(w)/'voices/profiles'/identifier(profile)
   profile_bytes+=sum((folder/name).stat().st_size for name in ('profile.json','reference.wav') if (folder/name).is_file())
  return dict(assets=list(found.values()),bytes=sum(x['bytes'] for x in found.values())+profile_bytes,voice_profile_bytes=profile_bytes)
 def transfer(self,w,a,destination,move=False,include=True,operation_id=None):
  if w==destination:raise ValueError('Choose another workspace')
  with self.lock:
   if w in (self.pins|self.operation_pins) or destination in (self.pins|self.operation_pins):raise ValueError('Wait for active workspace jobs')
   source=self.get(w);dest=self.get(destination)
   if dest.get('archived') or dest.get('deleted'):raise ValueError('Restore the destination first')
   plan=self.transfer_plan(w,a,include)
   if shutil.disk_usage(self.root).free<plan['bytes']+64*1024**2:raise ValueError('Not enough disk space for this complete transfer')
   ids={x['id'] for x in plan['assets']}
   if move:
    from studio_characters import retained_assets
    if ids.intersection(retained_assets(source)):raise ValueError('Project characters retain these references; copy instead')
    if any(id in source['context']['references'] for id in ids):raise ValueError('Project context retains a reference; copy it instead')
    if any(ids.intersection(snap['assets']) for snap in source['snapshots'].values()):raise ValueError('A snapshot retains an asset; copy instead')
    if any(ids.intersection(row.get('metadata',{}).get('required',[])) for id,row in source['assets'].items() if id not in ids and not row.get('trashed')):raise ValueError('Another creation requires these assets; copy instead')
   operation=dict(id=identifier(operation_id) if operation_id else key(),kind='transfer',state='copying',source=w,destination=destination,root=a[0] if isinstance(a,list) else a,move=move,include=include,assets=plan['assets'],copies={})
   journal_path=self.root/'operations'/f"{operation['id']}.json"
   if journal_path.exists():raise ValueError('This transfer operation already exists; inspect its progress instead of resubmitting')
   atomic(journal_path,operation)
  self.active_operations.add(operation['id'])
  try:self._finish_transfer(operation)
  except OperationCancelled:
   self.abort_transfer(operation);raise
  finally:self.active_operations.discard(operation['id'])
  with self.lock:
   primary=operation['root'];result_id=primary if move else operation['copies'][primary]['id'];return self.get(destination)['assets'][result_id]
 def _finish_transfer(self,operation):
  w=operation['source'];destination=operation['destination'];self.operation_pins.update([w,destination]);op=operation['id'];journal=self.root/'operations'/f'{op}.json'
  if operation['state']=='copying':
   for row in operation['assets']:
    a=row['id']
    if a in operation['copies']:continue
    source=contained(self.folder(w),self.folder(w)/row['path'])
    metadata={k:v for k,v in row.get('metadata',{}).items() if k not in ('compat_path','required')};metadata.update(pending_operation=op,copied_from=dict(workspace=w,asset=a))
    copy=self.import_file(destination,source,row['name'],metadata,operation=uuid.uuid5(uuid.NAMESPACE_URL,op+':'+a).hex)
    operation['copies'][a]=copy;atomic(journal,operation)
   operation['state']='verified';atomic(journal,operation);self.failpoint('move_verified')
  profiles=operation.setdefault('profiles',{})
  from studio_characters import voice_ids,remap_settings
  for old_profile in set().union(*(voice_ids(row.get('metadata',{}).get('settings',{})) for row in operation['assets'])):
   source_profile=self.folder(w)/'voices/profiles'/identifier(old_profile)
   if not (source_profile/'profile.json').is_file():continue
   if old_profile not in profiles:profiles[old_profile]=key();atomic(journal,operation)
   new_profile=profiles[old_profile];target=self.folder(destination)/'voices/profiles'/new_profile
   if not target.exists():
    stage=self.folder(destination)/'jobs'/('profile-import-'+op)/new_profile;stage.mkdir(parents=True,exist_ok=True)
    descriptor=json.loads((source_profile/'profile.json').read_text(encoding='utf-8'))
    self.copy_file(source_profile/'reference.wav',stage/'reference.wav',op)
    if digest(stage/'reference.wav')!=descriptor['sha256']:raise ValueError('Voice reference transfer verification failed')
    descriptor['id']=new_profile;atomic(stage/'profile.json',descriptor);os.replace(stage,target)
  source=self.get(w);dest=self.get(destination);mapping={a:(a if operation['move'] else row['id']) for a,row in operation['copies'].items()}
  for row in operation['assets']:
   copy=dict(operation['copies'][row['id']]);path=contained(self.folder(destination),self.folder(destination)/copy['path'])
   if digest(path)!=row['sha256']:raise ValueError('Transfer verification failed; source retained')
   dest['assets'].pop(copy['id'],None);copy['id']=mapping[row['id']];meta=dict(copy['metadata']);meta.pop('pending_operation',None);meta['required']=[mapping[a] for a in row.get('metadata',{}).get('required',[]) if a in mapping]
   if not operation['include'] and row.get('metadata',{}).get('required'):meta['omitted_required']=row['metadata']['required']
   meta['inputs']={role:([mapping[x] for x in value if x in mapping] if isinstance(value,list) else mapping.get(value)) for role,value in row.get('metadata',{}).get('inputs',{}).items()}
   if meta.get('settings',{}).get('profile') in profiles:meta['settings']=dict(meta['settings'],profile=profiles[meta['settings']['profile']])
   meta=json.loads(json.dumps(meta));remap_settings(meta.get('settings',{}),mapping,profiles)
   copy['metadata']=meta;dest['assets'][copy['id']]=copy
  self.save(dest);self.failpoint('move_published');operation['state']='published';atomic(journal,operation)
  if operation['move']:
   for row in operation['assets']:
    source['assets'].pop(row['id'],None)
    if row['id'] not in source.setdefault('tombstones',[]):source['tombstones'].append(row['id'])
   self.save(source)
   for row in operation['assets']:
    contained(self.folder(w),self.folder(w)/row['path']).unlink(missing_ok=True)
    if row.get('metadata',{}).get('compat_path'):
     legacy=contained(self.folder(w),self.folder(w)/row['metadata']['compat_path']);legacy.unlink(missing_ok=True);self.reconcile_chain(legacy)
  if operation['move']:
   for row in operation['assets']:self.cleanup_asset_cache(w,row)
  operation['state']='complete';atomic(journal,operation);self.operation_pins.difference_update([w,destination])


 def purge_workspace(self,w):
  with self.lock:
   doc=self.get(w)
   if w=='free-work' or not doc.get('deleted') or w in (self.pins|self.operation_pins):raise ValueError('Only inactive projects in project trash can be permanently deleted')
   operation=dict(id=key(),kind='project-purge',state='prepared',workspace=w)
   atomic(self.root/'operations'/f"{operation['id']}.json",operation);self._finish_project_purge(operation)
 def _finish_project_purge(self,operation):
  w=identifier(operation['workspace'])
  if w=='free-work':raise ValueError('Cannot purge Free work')
  folder=self.folder(w);assert folder.parent==self.root/'projects'
  if folder.exists():shutil.rmtree(folder)
  with closing(sqlite3.connect(self.root/'catalog.sqlite')) as db,db:db.execute('DELETE FROM workspaces WHERE id=?',(w,))
  operation['state']='complete';atomic(self.root/'operations'/f"{operation['id']}.json",operation)

 def copy_file(self,source,target,operation):
  with Path(source).open('rb') as incoming,Path(target).open('wb') as outgoing:
   for block in iter(lambda:incoming.read(1024*1024),b''):
    if operation in self.cancelled:raise OperationCancelled(operation)
    outgoing.write(block)
   outgoing.flush();os.fsync(outgoing.fileno())
 def cancel_operation(self,operation,workspace=None):
  path=self.root/'operations'/f'{identifier(operation)}.json';job=json.loads(path.read_text(encoding='utf-8'))
  if workspace and workspace not in (job.get('workspace'),job.get('source'),job.get('destination')):raise ValueError('Operation belongs to another workspace')
  if job.get('state')!='copying':raise ValueError('Operation has passed its cancellation point')
  job['cancel_requested']=True;atomic(path,job);self.cancelled.add(operation)
  if operation not in self.active_operations and job.get('kind')=='transfer':self.abort_transfer(job)
  return {'ok':True}
 def abort_transfer(self,operation):
  with self.lock:
   op=operation['id'];w=operation['destination'];doc=self.get(w)
   for a,row in list(doc['assets'].items()):
    if row.get('metadata',{}).get('pending_operation')==op:
     contained(self.folder(w),self.folder(w)/row['path']).unlink(missing_ok=True);del doc['assets'][a]
   self.save(doc)
   for profile in operation.get('profiles',{}).values():
    target=contained(self.folder(w),self.folder(w)/'voices/profiles'/profile)
    if target.exists():shutil.rmtree(target)
   for path in (self.root/'operations').glob('*.json'):
    child=json.loads(path.read_text(encoding='utf-8'))
    if child.get('kind')=='import' and child.get('asset',{}).get('metadata',{}).get('pending_operation')==op:
     contained(self.folder(w),self.folder(w)/child['stage']).unlink(missing_ok=True);child['state']='aborted';atomic(path,child)
   operation['state']='aborted';atomic(self.root/'operations'/f'{op}.json',operation);self.operation_pins.difference_update([operation['source'],w])
 def batch_trash(self,w,ids,restore=False):
  with self.lock:
   if w in (self.pins|self.operation_pins):raise ValueError('Workspace is busy')
   if not isinstance(ids,list) or not ids or len(ids)>500:raise ValueError('Select 1–500 assets')
   doc=self.get(w);selected=set(ids)
   for a in selected:self.asset(w,a,True)
   if not restore:
    from studio_characters import retained_assets
    if selected.intersection(retained_assets(doc)):raise ValueError('Project characters retain selected references')
    if selected.intersection(doc['context']['references']):raise ValueError('Remove selected references from project context first')
   for a in selected:doc['assets'][a]['trashed']=not restore
   self.save(doc);return {'ok':True,'count':len(selected)}

 def reconcile_chain(self,path):
  if path.name not in ('combined.mp4','combined.wav'):return
  record=path.parent/'job.json'
  if record.exists():
   row=json.loads(record.read_text(encoding='utf-8'));row['combined']=False;row.pop('combined_text',None);atomic(record,row)

 def cleanup_asset_cache(self,w,asset):
  folder=self.folder(w);contained(folder,folder/'uploads'/(asset['id']+Path(asset['path']).suffix)).unlink(missing_ok=True)
  for base in (folder/'jobs',folder/'voices/jobs'):
   for file in base.glob('*/job.json'):
    job=json.loads(file.read_text(encoding='utf-8'))
    if job.get('settings',{}).get('imported_asset')!=asset['id']:continue
    for name in ('video.mp4','audio.wav','combined.mp4','combined.wav','job.json'):(file.parent/name).unlink(missing_ok=True)
    if not any(file.parent.iterdir()):file.parent.rmdir()
