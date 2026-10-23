import hashlib,io,json,tempfile,time,unittest
from pathlib import Path
from studio_models import Models
class ModelTests(unittest.TestCase):
 def wait(self,m):
  for _ in range(200):
   if m.download['state']!='downloading':
    if m.worker:m.worker.join(timeout=2)
    return
   time.sleep(.01)
  self.fail('Download worker did not finish')
 def test_verified_download_and_selection_without_network(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   payload=b'GGUF verified fixture';sha=hashlib.sha256(payload).hexdigest();name='Hermes-3-Llama-3.1-8B.Q5_K_M.gguf'
   class Opener:
    def open(self,url,timeout=30):return io.BytesIO(json.dumps({'sha':'a'*40,'siblings':[{'rfilename':name,'lfs':{'size':len(payload),'sha256':sha}}]}).encode() if '/api/' in url else payload)
   m=Models(Path(tmp),opener=Opener());plan=m.plan('hermes-q5');self.assertEqual(plan['bytes'],len(payload));m.install(plan);self.wait(m);self.assertEqual(m.download['state'],'complete');m.select('hermes-q5');self.assertEqual(m.selected('writing')['sha256'],sha)
   with self.assertRaises(ValueError):m.plan('untrusted-repo')
 def test_corrupt_download_is_never_registered_and_busy_switch_rejected(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   m=Models(Path(tmp));plan=dict(id='hermes-q5',revision='a'*40,bytes=4,files=[dict(file='Hermes-3-Llama-3.1-8B.Q5_K_M.gguf',bytes=4,sha256='0'*64,url='https://huggingface.co/fixture')])
   class Opener:
    def open(self,url,timeout=30):return io.BytesIO(b'GGUF')
   m.opener=Opener();m.install(plan);self.wait(m);self.assertEqual(m.download['state'],'failed');self.assertNotIn('hermes-q5',m.state['installed']);m.busy=lambda:True
   with self.assertRaises(ValueError):m.select('hermes-q4')
 def test_model_download_cancel_keeps_existing_selection(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   m=Models(Path(tmp));plan=dict(id='hermes-q5',revision='a'*40,bytes=4,files=[dict(file='Hermes-3-Llama-3.1-8B.Q5_K_M.gguf',bytes=4,sha256=hashlib.sha256(b'GGUF').hexdigest(),url='https://huggingface.co/fixture')])
   class Incoming(io.BytesIO):
    def read(self,n=-1):m.cancel.set();return super().read(n)
   class Opener:
    def open(self,url,timeout=30):return Incoming(b'GGUF')
   m.opener=Opener();m.install(plan);self.wait(m);self.assertEqual(m.download['state'],'cancelled');self.assertEqual(m.state['selected']['writing'],'hermes-q4')
 def test_recovered_publication_requires_checksum_verification(self):
  from workspace_store import atomic
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   payload=b'GGUF recovered fixture';sha=hashlib.sha256(payload).hexdigest();name='Hermes-3-Llama-3.1-8B.Q5_K_M.gguf'
   m=Models(Path(tmp));folder=Path(tmp)/'hermes-q5';folder.mkdir();(folder/name).write_bytes(payload);atomic(folder/'verified-model.json',dict(id='hermes-q5',revision='a'*40,bytes=len(payload),files=[dict(file=name,bytes=len(payload),sha256=sha)]))
   m=Models(Path(tmp));self.assertFalse(m.state['installed']['hermes-q5']['verified']);m.select('hermes-q5');self.assertTrue(m.state['installed']['hermes-q5']['verified'])
