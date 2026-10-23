import json,os,tempfile,unittest,time
from pathlib import Path
from unittest.mock import patch
from freevideo_engine.studio_checkpoint import atomic,PauseSaved,boundary,ready,identity,image_load,image_boundary,video_boundary,stabilize_video
class CheckpointTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.folder=self.root/'checkpoint';self.folder.mkdir()
 def request(self):atomic(self.folder/'pause.request',{'requested':time.time()})
 def test_receipt_only_after_boundary_and_fresh_for_each_pause(self):
  self.assertFalse(ready(self.folder));self.request()
  with self.assertRaises(PauseSaved):boundary(self.folder,'voice-section',section=2)
  self.assertTrue(ready(self.folder,True));self.request();self.assertFalse(ready(self.folder,True));self.assertTrue(ready(self.folder))
 def test_image_checkpoint_preserves_exact_next_step(self):
  import torch
  key=identity({'seed':123,'prompt':'test'});value=torch.tensor([1.,2.,3.]);self.request()
  with self.assertRaises(PauseSaved):image_boundary(self.folder,key,4,value,torch)
  step,saved=image_load(self.folder,key,torch,'cpu');self.assertEqual(step,4);self.assertTrue(torch.equal(value,saved))
  with self.assertRaisesRegex(ValueError,'does not match'):image_load(self.folder,'other',torch,'cpu')
 def test_video_checkpoint_reuses_completed_sampling_with_provenance(self):
  import torch
  from freevideo_engine.decode_resume import sampling_provenance,save_sampling,load_saved_sampling
  cache=self.root/'cache';cache.mkdir();(cache/'manifest.json').write_text('{}');condition=self.root/'conditioning.pt';condition.write_bytes(b'conditioning')
  artifacts=self.root/'artifacts';artifacts.mkdir()
  request=dict(seed=2,geometry=dict(width=256,height=256,frames=39,fps=24),cache=str(cache),conditioning=str(condition),engine_options={'base':str(self.root/'base')},decoder_options={},artifacts=str(artifacts),metrics=str(self.root/'metrics.json'))
  with patch.dict(os.environ,STUDIO_CHECKPOINT_DIR=str(self.folder)):
   stabilize_video(request,self.folder);provenance=sampling_provenance(request)
   video=torch.ones(1,24,12,16,16);audio=torch.ones(2,32,65)
   save_sampling(dict(video=video,audio=audio,seed=2,geometry=request['geometry'],sampling_provenance=provenance),artifacts,torch)
   metrics=dict(success=False,phase='sample_finalize',config={'steps':8},step_seconds=[1.]*8,finite_latents=True,geometry=request['geometry'],sampling_provenance=provenance,sampling_checkpoint_complete=True)
   self.request()
   with self.assertRaises(PauseSaved):video_boundary(request,metrics)
  condition.unlink();saved=json.loads((self.folder/'video-request.json').read_text());result=load_saved_sampling(saved,torch)
  self.assertTrue(torch.equal(result[0],video));self.assertTrue(torch.equal(result[1],audio));self.assertTrue(result[2]['sampling_reused'])

 def test_voice_worker_resumes_saved_sections_without_regenerating(self):
  import runpy,sys,hashlib,contextlib
  import numpy as np,soundfile as sf
  from types import SimpleNamespace
  job=self.root;profile=job/'profiles'/'voice';profile.mkdir(parents=True);sf.write(profile/'reference.wav',np.ones(80)*.2,24000)
  profile_data=dict(id='voice',sha256=hashlib.sha256((profile/'reference.wav').read_bytes()).hexdigest(),reference_text='Reference')
  atomic(job/'request.json',dict(action='read',text='One. Two.',seed=123,profile_data=profile_data,profile_root=str(profile.parent),sound_plan=[{'kind':'speech','text':'One. Two.'}]))
  calls=[];pause_once=[True]
  def generate(**kw):
   calls.append(kw['text'])
   if pause_once[0]:atomic(self.folder/'pause.request',{'requested':time.time()});pause_once[0]=False
   return [np.ones(80,dtype=np.float32)*.25],24000
  model=SimpleNamespace(create_voice_clone_prompt=lambda **kw:None,generate_voice_clone=generate)
  fake_torch=SimpleNamespace(Tensor=__import__('torch').Tensor,set_num_threads=lambda n:None,manual_seed=lambda n:None,bfloat16=None,inference_mode=contextlib.nullcontext,cuda=SimpleNamespace(empty_cache=lambda:None))
  qwen=SimpleNamespace(Qwen3TTSModel=SimpleNamespace(from_pretrained=lambda *a,**kw:model))
  with patch.dict(sys.modules,torch=fake_torch,qwen_tts=qwen),patch('voice_text.chunks',return_value=['One.','Two.']),patch.object(sys,'argv',['voice_job.py',str(job)]):
   with self.assertRaises(PauseSaved):runpy.run_path(str(Path(__file__).with_name('voice_job.py')),run_name='__main__')
   self.assertEqual(calls,['One.']);self.assertTrue((job/'section-0-0.wav').exists());self.assertFalse((job/'audio.wav').exists())
   (self.folder/'pause.request').unlink();runpy.run_path(str(Path(__file__).with_name('voice_job.py')),run_name='__main__')
  self.assertEqual(calls,['One.','Two.']);self.assertGreater(sf.info(job/'audio.wav').frames,160)

 def test_retaining_sampling_accepts_identical_copy_but_not_other_bytes(self):
  from freevideo_engine.decode_resume import retain_latents
  source=self.root/'latents.pt';source.write_bytes(b'original');target=self.root/'artifacts';target.mkdir();(target/'latents.pt').write_bytes(b'original');retain_latents(source,target)
  (target/'latents.pt').write_bytes(b'different')
  with self.assertRaises(FileExistsError):retain_latents(source,target)
 def test_image_pipeline_continues_at_next_step_with_identical_result(self):
  import torch,numpy as np
  from types import SimpleNamespace
  from freevideo_engine.image_gen.qwen_pipeline import QwenImageGenerator
  calls=[];trigger=[False]
  class Transformer:
   config={'in_channels':4}
   def __call__(inner,**kw):
    calls.append(1)
    if trigger[0] and len(calls)==4:self.request()
    return torch.ones_like(kw['hidden_states'])*.2,
  class VAE:
   config={'z_dim':4,'latents_mean':[0]*4,'latents_std':[1]*4}
   def parameters(inner):return iter(())
   def decode(inner,value,**kw):return (value[:,:3],)
  text=SimpleNamespace(encode_prompt=lambda prompt:(torch.ones(1,8,4),None))
  def make():return QwenImageGenerator(None,device='cpu',transformer=Transformer(),vae=VAE(),text_encoder=text)
  fresh=make().generate('test',width=256,height=256,seed=123)
  calls.clear();trigger[0]=True
  with self.assertRaises(PauseSaved):make().generate('test',width=256,height=256,seed=123,checkpoint_directory=self.folder)
  self.assertEqual(len(calls),4);(self.folder/'pause.request').unlink();trigger[0]=False;calls.clear()
  resumed=make().generate('test',width=256,height=256,seed=123,checkpoint_directory=self.folder)
  self.assertEqual(len(calls),4);self.assertTrue(np.array_equal(np.asarray(fresh),np.asarray(resumed)))

 def test_video_is_marked_paused_only_after_worker_exit(self):
  import subprocess,sys,threading
  from studio import Studio
  job=self.root/'jobs'/('a'*32);job.mkdir(parents=True);checkpoint=job/'checkpoint';checkpoint.mkdir();atomic(checkpoint/'pause.request',{'requested':time.time()})
  row=dict(id='a'*32,status='pausing',started=time.time(),elapsed_base=25,settings={});atomic(job/'job.json',row)
  source=str(Path(__file__).parent/'FreeVideo')
  code="import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from freevideo_engine.studio_checkpoint import boundary;boundary(Path(sys.argv[2]),'fixture')"
  process=subprocess.Popen([sys.executable,'-c',code,source,str(checkpoint)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  self.addCleanup(lambda:process.kill() if process.poll() is None else None)
  studio=Studio.__new__(Studio);studio.directory=self.root;studio.lock=threading.RLock();studio.current=row['id'];studio.process=process
  studio.finish(job,row,process)
  saved=json.loads((job/'job.json').read_text());self.assertEqual(saved['status'],'paused');self.assertIsNotNone(process.poll());self.assertIsNone(studio.current);self.assertGreaterEqual(saved['elapsed'],25)
