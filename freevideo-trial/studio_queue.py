"""Durable global media scheduling. Engine job IDs remain stable from submission."""
import json,threading,time,uuid,subprocess
from workspace_store import atomic

PATHS={'video':'jobs','image':'image-jobs','voice':'voices/jobs'}
TERMINAL={'paused','completed','failed','cancelled','canceled','interrupted'}
class JobQueue:
 def __init__(self,hub):
  self.hub=hub;self.lock=threading.RLock();self.path=hub.store.root/'queue.json';self.stopped=threading.Event()
  self.doc=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'revision':0,'jobs':[]}
  for row in self.doc['jobs']:
   if row['status'] in ('running','cancelling','pausing'):
    file=self.file(row);actual=json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
    row.update(status=actual.get('status') if actual.get('status') in TERMINAL else 'interrupted',message=actual.get('message','') if actual.get('status') in TERMINAL else 'Studio stopped during this job. Retry starts a new generation.')
    if row['status']=='interrupted':self.write_job(row)
  known={j['id'] for j in self.doc['jobs']}
  # A power loss between placeholder publication and queue commit must not leave
  # an invisible pending item which can never dispatch.
  for project in hub.store.listing():
   for engine,sub in PATHS.items():
    for file in (hub.store.folder(project['id'])/sub).glob('*/job.json'):
     try:actual=json.loads(file.read_text(encoding='utf-8'))
     except (OSError,ValueError):continue
     if actual.get('status')=='queued' and actual['id'] not in known and actual.get('settings',{}).get('_queued_id')==actual['id']:
      row=dict(id=actual['id'],workspace=project['id'],project=project['name'],engine=engine,status='interrupted',submitted=actual.get('started',time.time()),settings=actual['settings'],message='Submission was interrupted before queue commit. Retry to generate.')
      self.doc['jobs'].append(row);self.write_job(row)
  self.save()
 def file(self,row):return self.hub.store.folder(row['workspace'])/PATHS[row['engine']]/row['id']/'job.json'
 def save(self):self.doc['revision']+=1;atomic(self.path,self.doc)
 def protected_owners(self):return {j['workspace'] for j in self.doc['jobs'] if j['status'] in ('queued','running','cancelling','pausing','paused')}
 def owners(self):return {j['workspace'] for j in self.doc['jobs'] if j['status'] in ('running','cancelling','pausing') or (j['status']=='queued' and not self.doc.get('paused'))}
 def pending(self):return [j for j in self.doc['jobs'] if j['status']=='queued']
 def write_job(self,row):
  file=self.file(row);file.parent.mkdir(parents=True,exist_ok=True)
  atomic(file,dict(id=row['id'],status=row['status'],started=row.get('started',row['submitted']),phase=row.get('phase') or ('Failed before generation started' if row['status']=='failed' else row.get('message') or 'Pending in global queue'),message=row.get('message',''),settings=row['settings']))
 def enqueue(self,w,engine,value):
  if engine not in PATHS:raise ValueError('Unsupported queued engine')
  doc=self.hub.store.get(w)
  if doc.get('archived') or doc.get('deleted'):raise ValueError('Restore the project first')
  if w in self.hub.store.operation_pins:raise ValueError('Wait for the project file operation')
  prompt=value.get('text' if engine=='voice' else 'prompt')
  if not isinstance(prompt,str) or not prompt.strip():raise ValueError('Enter a prompt or script')
  with self.hub.gate,self.lock,self.hub.store.lock:
   id=uuid.uuid4().hex;settings=json.loads(json.dumps(value));settings.pop('_resume',None);settings['_queued_id']=id
   row=dict(id=id,workspace=w,project=doc['name'],engine=engine,status='queued',submitted=time.time(),settings=settings)
   self.doc['jobs'].append(row);self.hub.store.pins.add(w);self.write_job(row);self.save();return json.loads(self.file(row).read_text(encoding='utf-8'))
 def state(self):
  with self.lock:
   return dict(checkpoint_support=True,paused=self.doc.get('paused',False),revision=self.doc['revision'],jobs=[{k:v for k,v in j.items() if k!='settings'}|{'name':str(j['settings'].get('text') or j['settings'].get('prompt'))[:100],'model':(j['settings'].get('model_spec') or {}).get('name')} for j in self.doc['jobs']])
 def action(self,value):
  with self.hub.gate,self.lock:
   action=value.get('action')
   if action in ('pause','resume') and not value.get('id'):
    self.doc['paused']=action=='pause';self.save();return self.state()
   if action=='reorder':
    ids=value.get('ids');pending=[j['id'] for j in self.pending()]
    if value.get('revision')!=self.doc['revision'] or not isinstance(ids,list) or len(ids)!=len(set(ids)) or set(ids)!=set(pending):raise ValueError('Queue changed; refresh and reorder again')
    mapping={j['id']:j for j in self.pending()};self.doc['jobs']=[j for j in self.doc['jobs'] if j['status']!='queued']+[mapping[id] for id in ids];self.save();return self.state()
   row=next((j for j in self.doc['jobs'] if j['id']==value.get('id')),None)
   if not row:raise ValueError('Queue job not found')
   if action=='pause':
    if row['status']!='running':raise ValueError('Only a running generation can pause')
    actual=json.loads(self.file(row).read_text(encoding='utf-8'))
    if actual.get('status')!='running':raise ValueError('Job changed; refresh before pausing')
    if not actual.get('checkpoint_capable'):raise ValueError('This worker started before checkpoint support. Let it finish; new jobs support Pause.')
    checkpoint=self.file(row).parent/'checkpoint';checkpoint.mkdir(exist_ok=True)
    atomic(checkpoint/'pause.request',{'requested':time.time()})
    self.doc['paused']=True
    row.update(status='pausing',phase='Pausing at next safe checkpoint',message='Saving progress before releasing GPU memory')
    actual.update(status='pausing',phase=row['phase']);atomic(self.file(row),actual);self.save();return self.state()
   if action=='resume':
    if row['status']!='paused':raise ValueError('Only a paused generation can continue')
    from freevideo_engine.studio_checkpoint import ready
    if not ready(self.file(row).parent/'checkpoint'):raise ValueError('Saved checkpoint is missing or invalid; cannot resume')
    self.doc['paused']=False
    row.update(status='queued',phase='Resume queued',message='Waiting to reload saved progress',elapsed_base=row.get('elapsed',0))
    row['settings']['_resume']=True;row.pop('finished',None);row.pop('progress',None)
    self.doc['jobs'].remove(row);self.doc['jobs'].append(row)
    actual=json.loads(self.file(row).read_text(encoding='utf-8'));actual.update(status='queued',phase='Resume queued',message=row['message']);atomic(self.file(row),actual);self.save();return self.state()
   if action=='dismiss':
    if row['status'] not in TERMINAL-{'paused'}:raise ValueError('Only finished jobs can be dismissed; cancel a paused job first')
    self.doc['jobs'].remove(row);self.save();return self.state()
   if action=='retry':
    if row['status'] not in TERMINAL-{'completed','paused'}:raise ValueError('Only failed, cancelled or interrupted jobs can retry')
    return self.enqueue(row['workspace'],row['engine'],row['settings'])
   if action!='cancel':raise ValueError('Unknown queue action')
   if row['status'] in ('queued','paused'):row.update(status='cancelled',finished=time.time());self.write_job(row);self.save()
   elif row['status'] in ('running','pausing'):
    st=self.hub.studio(row['workspace']);{'video':st.cancel,'image':st.cancel_image,'voice':st.voice.cancel}[row['engine']]();row['status']='cancelling';self.save()
   else:raise ValueError('Job is no longer pending or running')
   return self.state()
 def available_gpu(self,row):
  result=subprocess.run(['nvidia-smi','--query-gpu=memory.total,memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  total,used,util=map(float,result.stdout.strip().splitlines()[0].split(','));needed=max((row['settings'].get('model_spec') or {}).get('gpu_mib') or 1500,(row['settings'].get('sound_model_spec') or {}).get('gpu_mib',0) or 0)
  return util<=30 and total-used>=needed
 def tick(self):
  with self.hub.gate,self.lock:
   running=next((j for j in self.doc['jobs'] if j['status'] in ('running','cancelling','pausing')),None)
   if running:
    actual=json.loads(self.file(running).read_text(encoding='utf-8'))
    if actual['status'] in TERMINAL:
     running.update(status=actual['status'],finished=time.time(),message=actual.get('message',''),phase=actual.get('phase',''),elapsed=actual.get('elapsed',0));self.save()
    else:
     stage,progress=actual.get('phase'),actual.get('progress')
     if running['engine']=='video' and not stage:
      from studio import phase
      stage,progress=phase(self.file(running).parent)
     running.update(phase=('Pausing at next safe checkpoint · '+(stage or 'Generating')) if running['status']=='pausing' else stage or 'Generating',progress=progress,elapsed=running.get('elapsed_base',0)+max(0,round(time.time()-running['started'])))
    return
   if self.doc.get('paused'):return
   if self.hub.reserved or self.hub.busy(include_queue=False) or not self.pending():return
   row=self.pending()[0]
   if row['workspace'] in self.hub.store.operation_pins:return
   try:
    st=self.hub.studio(row['workspace'])
    for instance in list(self.hub.instances.values()):
     if instance.image_service:instance.image_service.stop_for_generation()
    st.chat.stop()
    if not self.available_gpu(row):row['message']='Waiting for GPU resources';return
    self.hub.reserved=True;row.update(status='running',started=time.time());row.pop('message',None);self.save()
    {'video':st.start,'image':st.start_image,'voice':st.voice.start}[row['engine']](dict(row['settings']))
   except Exception as exc:
    row.update(status='failed',finished=time.time(),message=str(exc));self.write_job(row);self.save()
    from studio_diagnostics import LOG
    LOG.record('error','queue',str(exc),workspace=row['workspace'],job=row['id'])
   finally:self.hub.reserved=False
 def start(self):
  def run():
   while not self.stopped.wait(1):
    try:self.tick()
    except Exception as exc:
     from studio_diagnostics import LOG
     LOG.record('error','queue',str(exc))
  threading.Thread(target=run,daemon=True,name='studio-queue').start()
