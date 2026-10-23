"""Adapter-specific local model catalog and verified downloads; never installs executable model code."""
import hashlib,json,os,shutil,threading,time,urllib.request,urllib.parse
from pathlib import Path
from workspace_store import atomic,digest,contained
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parent
CATALOG={
 'sfx-audioldm2':dict(engine='sound-effects',name='AudioLDM 2 · local sound effects',repo='cvssp/audioldm2',revision='c8e7e189d324425c05c4c2f81214041ef4107983',license='CC-BY-NC-SA-4.0',gpu_mib=4500),
 'cydonia-heretic-q4':dict(engine='writing',name='Cydonia Heretic · 24B · Q4_K_M',repo='mradermacher/Cydonia-24B-v4.3-heretic-GGUF',revision='7b7b06cf73df212fcbe9bc4385adf71afff2b4b0',file='Cydonia-24B-v4.3-heretic.Q4_K_M.gguf',license='See upstream Cydonia/Mistral license',gpu_mib=18000,chat_template='embedded'),
 'vision-qwen25-3b':dict(engine='vision',name='Qwen2.5-VL · 3B · Q4_K_M',repo='ggml-org/Qwen2.5-VL-3B-Instruct-GGUF',revision='5037fcf163dd95d1e41d1974465f0898ed108ca2',file='Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf',projector='mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf',license='See Qwen2.5-VL-3B upstream license',gpu_mib=5000,chat_template='embedded'),
 'rocinante-q4':dict(engine='writing',name='Rocinante-X · 12B · Q4_K_M',repo='bartowski/TheDrummer_Rocinante-X-12B-v1-GGUF',revision='4302599a9fecd0e250c3790d77a38f3bd791fdd4',file='TheDrummer_Rocinante-X-12B-v1-Q4_K_M.gguf',license='See upstream Mistral Nemo license',gpu_mib=9500,chat_template='embedded'),
 'hermes-q4':dict(engine='writing',name='Hermes 3 · 8B · Q4_K_M',repo='NousResearch/Hermes-3-Llama-3.1-8B-GGUF',revision='307a5dfb59aa38d88b6cfd32f44b8ad7c1da9fb8',file='Hermes-3-Llama-3.1-8B.Q4_K_M.gguf',license='Llama 3',gpu_mib=5500),
 'hermes-q5':dict(engine='writing',name='Hermes 3 · 8B · Q5_K_M',repo='NousResearch/Hermes-3-Llama-3.1-8B-GGUF',revision='307a5dfb59aa38d88b6cfd32f44b8ad7c1da9fb8',file='Hermes-3-Llama-3.1-8B.Q5_K_M.gguf',license='Llama 3',gpu_mib=7000),
 'voice-base-06':dict(engine='voice-read',name='Qwen TTS Base · 0.6B',repo='Qwen/Qwen3-TTS-12Hz-0.6B-Base',license='Apache 2.0',gpu_mib=2800),
 'voice-base-17':dict(engine='voice-read',name='Qwen TTS Base · 1.7B',repo='Qwen/Qwen3-TTS-12Hz-1.7B-Base',license='Apache 2.0',gpu_mib=4300),
 'voice-design-17':dict(engine='voice-design',name='Qwen VoiceDesign · 1.7B',repo='Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign',license='Apache 2.0',gpu_mib=4300),
 'image-qwen':dict(engine='image',name='Qwen Image 2.1 Turbo · FreeVideo pack',license='See installed pack notices',managed=True),
 'video-h3':dict(engine='video',name='VDN-H3 · installed FreeVideo profile',license='See installed engine/model notices',managed=True),
}
DEFAULTS={'writing':'hermes-q4','voice-read':'voice-base-06','voice-design':'voice-design-17','image':'image-qwen','video':'video-h3'}
class SafeRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  host=urllib.parse.urlparse(newurl).hostname or ''
  if urllib.parse.urlparse(newurl).scheme!='https' or not (host=='huggingface.co' or host.endswith(('.huggingface.co','.hf.co','.xethub.hf.co'))):raise ValueError('Unapproved model download redirect')
  return super().redirect_request(req,fp,code,msg,headers,newurl)
class Models:
 def __init__(self,root,busy=lambda:False,opener=None):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'registry.json';self.lock=threading.RLock();self.busy=busy;self.opener=opener or urllib.request.build_opener(SafeRedirect());self.cancel=threading.Event();self.download=None;self.worker=None;self.verification=None
  try:self.state=json.loads(self.path.read_text(encoding='utf-8'))
  except FileNotFoundError:self.state=dict(selected=DEFAULTS.copy(),installed={})
  defaults={'hermes-q4':PROJECT/'conversation-engine/models/Hermes-3-Llama-3.1-8B.Q4_K_M.gguf','voice-base-06':PROJECT/'media-runtime/voice/models/Base','voice-design-17':PROJECT/'media-runtime/voice/models/VoiceDesign','image-qwen':ROOT/'runtime/models/vdn/image_gen','video-h3':ROOT/'runtime/models/vdn/h3-base'}
  for id,path in defaults.items():
   if path.exists() and id not in self.state['installed']:
    record=dict(path=str(path),verified=True,origin='previously verified project installer',adapter=CATALOG[id]['engine'])
    if id=='hermes-q4':record.update(json.loads((PROJECT/'conversation-engine/installation.json').read_text(encoding='utf-8')));record['path']=str(path)
    self.state['installed'][id]=record
  self.recover_removal()
  for id,entry in CATALOG.items():
   folder=self.root/id;manifest=folder/'verified-model.json'
   if id not in self.state['installed'] and manifest.is_file():
    plan=json.loads(manifest.read_text(encoding='utf-8'))
    if plan.get('id')!=id:continue
    model_path=folder/entry['file'] if entry.get('file') else folder
    self.state['installed'][id]=dict(path=str(model_path),verified=False,revision=plan.get('revision'),adapter=entry['engine'],bytes=plan['files'][0]['bytes'] if entry.get('file') else plan['bytes'],sha256=plan['files'][0].get('sha256') if entry.get('file') else None,origin='Recovered publication; verification required before activation')
  if 'vision-qwen25-3b' in self.state['installed']:self.state['selected'].setdefault('vision','vision-qwen25-3b')
  if 'sfx-audioldm2' in self.state['installed']:self.state['selected'].setdefault('sound-effects','sfx-audioldm2')
  atomic(self.path,self.state)
  status=self.root/'download-state.json'
  if status.exists():
   self.download=json.loads(status.read_text(encoding='utf-8'))
   if self.download.get('state')=='downloading':self.download['state']='complete' if self.download.get('id') in self.state['installed'] else 'interrupted'
 def info(self):
  return dict(catalog=[dict(id=id,**entry,installed=id in self.state['installed'],available=(id in self.state['installed'] and self.state['installed'][id].get('verified',False) and Path(self.state['installed'][id]['path']).exists() and (not entry.get('projector') or (Path(self.state['installed'][id]['path']).parent/entry['projector']).is_file())),selected=self.state['selected'].get(entry['engine'])==id) for id,entry in CATALOG.items()],selected=self.state['selected'],download=dict(self.download) if self.download else None,verification=self.verification,free_disk_bytes=shutil.disk_usage(self.root).free,storage=str(self.root))
 def selected(self,engine):
  id=self.state['selected'][engine];record=self.state['installed'][id]
  return dict(projector=str(Path(record['path']).parent/CATALOG[id]['projector']) if CATALOG[id].get('projector') else None,id=id,path=record['path'],verified=record.get('verified',False),bytes=record.get('bytes'),sha256=record.get('sha256'),revision=record.get('revision'),gpu_mib=CATALOG[id].get('gpu_mib'),name=CATALOG[id]['name'],chat_template=CATALOG[id].get('chat_template','chatml'))
 def select(self,id):
  with self.lock:
   if self.busy() or (self.worker and self.worker.is_alive()) or self.download and self.download['state']=='downloading':raise ValueError('Wait for active jobs/downloads before switching models')
   if id not in CATALOG or id not in self.state['installed']:raise ValueError('Install and verify this compatible model first')
   if not Path(self.state['installed'][id]['path']).exists():raise ValueError('Installed model path is missing')
   if not self.state['installed'][id].get('verified'):self.verify_recovered(id)
   self.state['selected'][CATALOG[id]['engine']]=id;atomic(self.path,self.state);return self.info()
 def fetch_json(self,url):
  with self.opener.open(url,timeout=30) as r:return json.loads(r.read(8*1024*1024))
 def plan(self,id):
  cached=self.root/'plans'/(str(id)+'.json')
  if id in CATALOG and cached.is_file():return json.loads(cached.read_text(encoding='utf-8'))
  if id not in CATALOG:raise ValueError('Unsupported model')
  entry=CATALOG[id]
  if entry.get('managed'):raise ValueError('This engine uses its installed managed pack; a different architecture needs an adapter')
  api='https://huggingface.co/api/models/'+entry['repo'];revision=entry.get('revision')
  meta=self.fetch_json(api+('/revision/'+revision if revision else '')+'?blobs=true');revision=meta['sha'];rows=[]
  for file in meta['siblings']:
   name=file['rfilename']
   if entry.get('file') and name not in (entry['file'],entry.get('projector')):continue
   if not entry.get('file') and Path(name).suffix.lower() not in ('.safetensors','.json','.txt','.md','.model'):continue
   if name.startswith('/') or '\\' in name or '..' in Path(name).parts or ':' in name:raise ValueError('Unsafe remote model filename')
   lfs=file.get('lfs') or {};size=lfs.get('size',file.get('size'));sha=lfs.get('sha256') or lfs.get('oid');blob=file.get('blobId')
   if not isinstance(size,int) or size<0 or not (sha or blob):raise ValueError('Repository did not supply a verifiable file manifest')
   rows.append(dict(file=name,bytes=size,sha256=sha,blob=blob,url='https://huggingface.co/'+entry['repo']+'/resolve/'+revision+'/'+urllib.parse.quote(name,safe='/')))
  if not rows:raise ValueError('No compatible model files found')
  rows.sort(key=lambda row:row['file']!=entry.get('file'))
  if entry.get('projector') and not any(row['file']==entry['projector'] for row in rows):raise ValueError('Vision projector is missing from the repository')
  plan=dict(id=id,revision=revision,files=rows,bytes=sum(x['bytes'] for x in rows),license=entry['license'],name=entry['name']);atomic(cached,plan);return plan
 def install(self,plan,source=None,cleanup_source=False,workspace=None):
  # Source is an app-owned upload containing an exact official GGUF; public API never accepts filesystem paths.
  with self.lock:
   if self.busy() or (self.worker and self.worker.is_alive()) or self.download and self.download['state']=='downloading':raise ValueError('Wait for the active job/download')
   id=plan['id']
   if source and len(plan['files'])!=1:raise ValueError('This model requires multiple files; use the verified download')
   if id in self.state['installed']:raise ValueError('Model is already installed; its active copy is never overwritten')
   if shutil.disk_usage(self.root).free<plan['bytes']+128*1024**2:raise ValueError('Not enough storage for this model')
   self.cancel.clear();self.download=dict(id=id,state='downloading',done=0,total=plan['bytes'],started=time.time(),workspace=workspace)
   atomic(self.root/'download-plan.json',plan);atomic(self.root/'download-state.json',self.download)
   self.worker=threading.Thread(target=self._install,args=(plan,source,cleanup_source),daemon=True);self.worker.start();return self.download
 def _install(self,plan,source,cleanup_source=False):
  id=plan['id'];stage=self.root/(id+'.partial');stage.mkdir(exist_ok=True)
  try:
   for row in plan['files']:
    path=contained(stage,stage/row['file']);path.parent.mkdir(parents=True,exist_ok=True)
    sha=hashlib.sha256();git=hashlib.sha1();git.update(('blob '+str(row['bytes'])+'\0').encode())
    incoming=Path(source).open('rb') if source else self.opener.open(row['url'],timeout=30)
    with incoming,path.open('wb') as outgoing:
     for block in iter(lambda:incoming.read(1024*1024),b''):
      if self.cancel.is_set():raise InterruptedError('Model download cancelled')
      outgoing.write(block);sha.update(block);git.update(block);self.download['done']+=len(block)
     outgoing.flush();os.fsync(outgoing.fileno())
    if path.stat().st_size!=row['bytes'] or (row.get('sha256') and sha.hexdigest()!=row['sha256']) or (not row.get('sha256') and git.hexdigest()!=row['blob']):raise ValueError('Model checksum or size verification failed')
   target=self.root/id
   if target.exists():raise ValueError('Model destination already exists; no overwrite performed')
   atomic(stage/'verified-model.json',plan);os.replace(stage,target)
   entry=CATALOG[id];model_path=target/entry['file'] if entry.get('file') else target
   record=dict(path=str(model_path),verified=True,revision=plan['revision'],adapter=entry['engine'],bytes=plan['files'][0]['bytes'] if entry.get('file') else plan['bytes'],sha256=plan['files'][0].get('sha256') if entry.get('file') else None)
   with self.lock:self.state['installed'][id]=record;atomic(self.path,self.state)
   self.download['state']='complete'
   if source and cleanup_source:Path(source).unlink(missing_ok=True)
  except InterruptedError:self.download['state']='cancelled'
  except Exception as exc:self.download.update(state='failed',error=str(exc))
  finally:atomic(self.root/'download-state.json',self.download)
 def cancel_download(self):self.cancel.set();return {'ok':True}

 def clear_partial(self):
  with self.lock:
   if not self.download or (self.worker and self.worker.is_alive()) or self.download['state']=='downloading':raise ValueError('No inactive model download to clean')
   id=self.download['id']
   if id not in CATALOG:raise ValueError('Unknown staged model')
   stage=contained(self.root,self.root/(id+'.partial'))
   if stage.exists():shutil.rmtree(stage)
   return {'ok':True}
 def remove(self,id):
  with self.lock:
   if self.busy() or id in self.state['selected'].values():raise ValueError('Selected/active models cannot be removed')
   if id not in self.state['installed'] or id not in CATALOG:raise ValueError('Unknown installed model')
   folder=contained(self.root,self.root/id)
   if not (folder/'verified-model.json').exists():raise ValueError('Original managed models are retained; only downloaded models can be removed here')
   atomic(self.root/'removal.json',{'id':id,'state':'removing'});self.state['installed'].pop(id,None);atomic(self.path,self.state);shutil.rmtree(folder);atomic(self.root/'removal.json',{'id':id,'state':'complete'});return {'ok':True}

 def recover_removal(self):
  marker=self.root/'removal.json'
  if not marker.exists():return
  removal=json.loads(marker.read_text(encoding='utf-8'));id=removal.get('id')
  if removal.get('state')!='removing':return
  if id not in CATALOG or id in self.state['selected'].values():raise ValueError('Pending removal conflicts with the selected model; no file removed')
  folder=contained(self.root,self.root/id)
  if folder.exists():shutil.rmtree(folder)
  self.state['installed'].pop(id,None);atomic(self.path,self.state);removal['state']='complete';atomic(marker,removal)
 def verify_recovered(self,id):
  self.verification=id
  try:
   folder=contained(self.root,self.root/id);plan=json.loads((folder/'verified-model.json').read_text(encoding='utf-8'))
   for row in plan['files']:
    file=contained(folder,folder/row['file'])
    if not file.is_file() or file.stat().st_size!=row['bytes']:raise ValueError('Recovered model is incomplete; do not activate it')
    if row.get('sha256'):
     if digest(file)!=row['sha256']:raise ValueError('Recovered model checksum mismatch')
    else:
     h=hashlib.sha1();h.update(('blob '+str(row['bytes'])+'\0').encode());h.update(file.read_bytes())
     if h.hexdigest()!=row['blob']:raise ValueError('Recovered model metadata mismatch')
   self.state['installed'][id]['verified']=True;atomic(self.path,self.state)
  finally:self.verification=None
