"""Offline AudioLDM2 effects generation, invoked only inside a reserved audio job."""
import json,sys,hashlib,os
from pathlib import Path

def effect_key(part,model):return hashlib.sha256(json.dumps([model.get('revision'),part['kind'],part['prompt'],part['seconds'],40],ensure_ascii=False).encode()).hexdigest()

def main():
 import numpy as np,soundfile as sf
 folder=Path(sys.argv[1]).resolve();request=json.loads((folder/'request.json').read_text(encoding='utf-8'));spec=request['sound_model_spec'];cache=Path(__file__).resolve().parent.parent/'media-workspaces/shared/sound-effects';cache.mkdir(parents=True,exist_ok=True)
 sys.path.insert(0,str(Path(__file__).resolve().parent/'FreeVideo'))
 from freevideo_engine.studio_checkpoint import directory,boundary
 checkpoint=directory(str(folder/'checkpoint'));boundary(checkpoint,'sound-inputs')
 pipeline=None;manifest={}
 for index,part in enumerate(request['sound_plan']):
  if part['kind'] not in ('action','background'):continue
  key=effect_key(part,spec);cached=cache/(key+'.wav');target=folder/f'sound-{index}.wav'
  valid=False
  if cached.is_file():
   try:valid=sf.info(cached).frames>0
   except Exception:pass
  if not valid:
   if pipeline is None:
    import torch
    from diffusers import AudioLDM2Pipeline
    torch.set_num_threads(4)
    print(json.dumps({'phase':'Loading local sound-effects model'}),flush=True)
    pipeline=AudioLDM2Pipeline.from_pretrained(spec['path'],torch_dtype=torch.float16,use_safetensors=True,local_files_only=True)
    from audioldm_compat import generate_hidden_states
    from types import MethodType
    pipeline.generate_language_model=MethodType(generate_hidden_states,pipeline)
    pipeline.enable_model_cpu_offload()
   print(json.dumps({'phase':'Generating '+part['kind']+' sound','chunk':index+1,'total':len(request['sound_plan'])}),flush=True)
   seed=int(key[:8],16)%2147483647
   prompt=part['prompt']+(', continuous ambient background, no speech, no music' if part['kind']=='background' else ', isolated sound effect, no speech, no music')
   with torch.inference_mode():audio=pipeline(prompt=prompt,num_inference_steps=40,audio_length_in_s=part['seconds'],generator=torch.Generator('cpu').manual_seed(seed)).audios[0]
   audio=np.asarray(audio,dtype=np.float32)
   if not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio))<1e-5:raise ValueError('Sound generation produced invalid or silent audio')
   temporary=cache/(key+'.partial.wav');sf.write(temporary,audio,16000,subtype='PCM_16');os.replace(temporary,cached)
  import shutil
  shutil.copyfile(cached,target);manifest[str(index)]=target.name
  boundary(checkpoint,'sound-effect',effect=index)
 (folder/'sounds.json').write_text(json.dumps(manifest),encoding='utf-8')

if __name__=='__main__':main()
