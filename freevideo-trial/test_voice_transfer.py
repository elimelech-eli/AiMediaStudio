import json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from workspace_store import WorkspaceStore,digest
from voice_studio import VoiceStudio,write
from test_audio_collections import profile
from studio_voice_transfer import transfer,recover
class VoiceTransferTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=WorkspaceStore(Path(self.tmp.name));self.a=self.store.create('Source')['id'];self.b=self.store.create('Destination')['id']
  self.hub=SimpleNamespace(store=self.store,gate=threading.RLock(),queue=SimpleNamespace(protected_owners=lambda:set()),active=lambda:None,conversations=SimpleNamespace(busy=lambda w:False))
  self.source=VoiceStudio(self.store.folder(self.a)/'voices');self.target=VoiceStudio(self.store.folder(self.b)/'voices');self.id=profile(self.source.root);file=self.source.local_profiles/self.id/'profile.json';row=json.loads(file.read_text());row['sha256']=digest(file.parent/'reference.wav');write(file,row)
 def run_transfer(self,action='move'):return transfer(self.hub,self.a,dict(action=action,id=[self.id],destination=self.b))
 def test_move_retains_existing_recording_reference_and_clears_context(self):
  doc=self.store.get(self.a);doc['context']['voice']=self.id;doc['assets']['fixture']={'metadata':{'settings':{'profile':self.id}}};self.store.save(doc)
  result=self.run_transfer();new=result['voices'][0]['id'];self.assertEqual(new,self.id);self.assertEqual(self.source.profile_listing(),[]);self.assertEqual(self.target.profile_listing()[0]['id'],new)
  self.assertTrue(self.source.file('profiles',self.id,'reference.wav').is_file());self.assertIn(self.id,self.source.state()['retained_profiles']);self.assertEqual(self.source.state()['profiles'],[]);self.assertIsNone(self.store.get(self.a)['context']['voice'])
 def test_copy_gets_new_id_and_source_stays_visible(self):
  result=self.run_transfer('copy');self.assertNotEqual(result['voices'][0]['id'],self.id);self.assertEqual(len(self.source.profile_listing()),1);self.assertEqual(len(self.target.profile_listing()),1)
 def test_collision_preserves_destination_voice(self):
  profile(self.target.root,id=self.id,name='Existing');before=(self.target.local_profiles/self.id/'profile.json').read_bytes();result=self.run_transfer();self.assertNotEqual(result['voices'][0]['id'],self.id);self.assertEqual((self.target.local_profiles/self.id/'profile.json').read_bytes(),before)
 def test_recovery_finishes_after_verified_copy_without_losing_source(self):
  import studio_voice_transfer
  original=studio_voice_transfer.atomic;source_file=self.source.local_profiles/self.id/'profile.json'
  def fail(path,value):
   if Path(path)==source_file:raise OSError('Simulated interruption')
   return original(path,value)
  with patch('studio_voice_transfer.atomic',side_effect=fail):
   with self.assertRaises(OSError):self.run_transfer()
  self.assertEqual(len(self.source.profile_listing()),1);recover(self.store);self.assertEqual(self.source.profile_listing(),[]);self.assertEqual(len(self.target.profile_listing()),1)
 def test_busy_and_paused_projects_are_protected(self):
  self.hub.queue.protected_owners=lambda:{self.a}
  with self.assertRaisesRegex(ValueError,'active or paused'):self.run_transfer()
  self.assertEqual(len(self.source.profile_listing()),1);self.assertEqual(self.target.profile_listing(),[])
