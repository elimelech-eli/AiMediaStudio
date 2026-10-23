"""Local bounded diagnostic events; never records request bodies, prompts or tokens."""
import datetime,json,re,threading,traceback,uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parent
class Diagnostics:
 def __init__(self,directory=None):self.directory=Path(directory or ROOT/'studio-data/logs');self.lock=threading.RLock();self.last_error=None
 def clean(self,value):
  text=str(value or '')[:16000]
  text=re.sub(r'(?i)(bearer\s+|api[-_ ]?key[=: ]+|token[=: ]+)[^\s,;\"\']+',r'\1[redacted]',text)
  return text
 def record(self,level,component,message,workspace=None,job=None,details=None):
  row=dict(id=uuid.uuid4().hex,time=datetime.datetime.now(datetime.timezone.utc).isoformat(),level=level,component=component,message=self.clean(message),workspace=workspace,job=job)
  if details:row['details']=self.clean(details)
  try:
   with self.lock:
    self.directory.mkdir(parents=True,exist_ok=True);file=self.directory/'events.jsonl'
    if file.exists() and file.stat().st_size>5*1024**2:
     for index in (2,1):
      source=self.directory/f'events.{index}.jsonl'
      if source.exists():source.replace(self.directory/f'events.{index+1}.jsonl')
     file.replace(self.directory/'events.1.jsonl')
    with file.open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
   self.last_error=None
  except OSError as exc:self.last_error=str(exc)
  return row['id']
 def events(self,limit=300):
  rows=[]
  with self.lock:
   for file in [*(self.directory/f'events.{i}.jsonl' for i in (3,2,1)),self.directory/'events.jsonl']:
    if not file.exists():continue
    try:
     with file.open(encoding='utf-8') as stream:
      from collections import deque
      lines=deque(stream,maxlen=limit)
     for line in lines:
      try:rows.append(json.loads(line))
      except ValueError:pass
    except OSError:continue
  return rows[-limit:]
 def view(self,store=None,source='events'):
  sources={'backend':ROOT/'logs/studio.err.log','chat':ROOT/'studio-data/chat-runtime/worker.log','backend-output':ROOT/'logs/studio.log'}
  if source!='events':
   if source not in sources:raise ValueError('Unknown log source')
   try:
    with sources[source].open('rb') as stream:stream.seek(max(0,sources[source].stat().st_size-65536));raw=stream.read(65536).decode('utf-8',errors='replace')
   except FileNotFoundError:raw='No log entries yet.'
   return dict(source=source,text=self.clean(raw[-16000:]),sources=list(sources),storage_error=self.last_error)
  rows=self.events()
  if store:
   for workspace in store.listing():
    for kind,sub in [('image','image-jobs'),('video','jobs'),('voice','voices/jobs')]:
     for file in (store.folder(workspace['id'])/sub).glob('*/job.json'):
      try:
       job=json.loads(file.read_text(encoding='utf-8'))
       if job.get('status') not in ('failed','interrupted','completed','cancelled','canceled'):continue
       rows.append(dict(id='history-'+job['id'],time=datetime.datetime.fromtimestamp(job.get('started',0),datetime.timezone.utc).isoformat(),level='error' if job.get('status') in ('failed','interrupted') else 'warning' if job.get('status') in ('cancelled','canceled') else 'info',component=kind,message=self.clean(job.get('message') or 'Generation '+job['status']),workspace=workspace['id'],job=job['id'],historical=True))
      except (OSError,ValueError,KeyError):continue
  return dict(source=source,events=sorted(rows,key=lambda r:r.get('time',''),reverse=True)[:500],sources=list(sources),storage_error=self.last_error)

LOG=Diagnostics()
