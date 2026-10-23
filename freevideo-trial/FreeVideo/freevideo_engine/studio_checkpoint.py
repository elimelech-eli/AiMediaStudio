"""Opt-in Studio disk checkpoints. No model or CUDA imports on the control path."""
import hashlib,json,os,shutil,time
from pathlib import Path
PAUSE_EXIT=77
class PauseSaved(SystemExit):
 def __init__(self):super().__init__(PAUSE_EXIT)
def directory(value=None):
 value=value or os.environ.get('STUDIO_CHECKPOINT_DIR')
 return Path(value).resolve() if value else None
def atomic(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix(path.suffix+'.tmp')
 with temporary.open('w',encoding='utf-8') as stream:
  json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
 os.replace(temporary,path)
def requested(folder):return folder is not None and (folder/'pause.request').is_file()
def commit(folder,stage,**extra):
 atomic(folder/'receipt.json',dict(version=1,stage=stage,saved=time.time(),**extra));raise PauseSaved()
def boundary(folder,stage,**extra):
 if requested(folder):commit(folder,stage,**extra)
def ready(folder,fresh=False):
 try:
  folder=Path(folder);receipt=json.loads((folder/'receipt.json').read_text(encoding='utf-8'))
  return receipt.get('version')==1 and (not fresh or receipt.get('saved',0)>=json.loads((folder/'pause.request').read_text(encoding='utf-8'))['requested'])
 except (OSError,ValueError,TypeError,KeyError,AttributeError):return False
def identity(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
def image_load(folder,identity_value,torch,device):
 if folder is None or not (folder/'image-state.pt').exists():return None
 saved=torch.load(folder/'image-state.pt',map_location='cpu',weights_only=True)
 if saved.get('identity')!=identity_value:raise ValueError('Image checkpoint does not match this request')
 if not 0<=saved['step']<=8 or not torch.isfinite(saved['latents']).all():raise ValueError('Invalid image checkpoint')
 return saved['step'],saved['latents'].to(device)
def image_boundary(folder,key,step,latents,torch):
 if not requested(folder):return
 temporary=folder/'image-state.tmp';torch.save(dict(identity=key,step=step,latents=latents.detach().cpu()),temporary)
 os.replace(temporary,folder/'image-state.pt');commit(folder,'image-step',step=step)
def stabilize_video(request,folder):
 # The encoder's temporary directory is removed when the controller exits.
 folder.mkdir(parents=True,exist_ok=True);source=Path(request['conditioning']);target=folder/'conditioning.pt'
 if source.resolve()!=target.resolve():
  shutil.copyfile(source,target);request['conditioning']=str(target)
 return request
def video_boundary(request,metrics=None):
 folder=directory()
 if not requested(folder):return
 saved=dict(request)
 if metrics is not None and not request.get('resume_decode'):
  from .decode_resume import completed_sampling
  retained=dict(metrics,phase='sample_finalize',success=False,sampling_checkpoint_complete=True)
  if not completed_sampling(retained):raise ValueError('Cannot checkpoint incomplete video sampling')
  source=Path(request['artifacts'])/'latents.pt'
  if not source.is_file():raise ValueError('Video sampling checkpoint is missing')
  target=folder/'latents.pt';temporary=folder/'latents.link.tmp';temporary.unlink(missing_ok=True)
  try:os.link(source,temporary)
  except OSError:shutil.copyfile(source,temporary)
  os.replace(temporary,target);atomic(folder/'sample-metrics.json',retained);atomic(folder/'sample-request.json',request)
  saved['resume_decode']=dict(latents=str(folder/'latents.pt'),metrics=str(folder/'sample-metrics.json'),request=str(folder/'sample-request.json'))
 atomic(folder/'video-request.json',saved);commit(folder,'video-decode' if metrics is not None else 'video-encoded')
