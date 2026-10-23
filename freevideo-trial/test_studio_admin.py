import json, os, tempfile, unittest
from pathlib import Path
from studio_admin import delete_job
class AdminTests(unittest.TestCase):
 def job(self,root,key,status='completed'):
  folder=root/key;folder.mkdir();(folder/'job.json').write_text(json.dumps({'status':status}));(folder/'audio.wav').write_bytes(b'keep samples');return folder
 def test_delete_source_preserves_chain_and_profile_copies(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=self.job(root,'source');chain=self.job(root,'chain');profile=root/'profile.wav';profile.write_bytes((source/'audio.wav').read_bytes())
   (chain/'audio.wav').unlink();os.link(source/'audio.wav',chain/'audio.wav')
   self.assertTrue(delete_job(root,'source')['ok']);self.assertFalse(source.exists());self.assertEqual((chain/'audio.wav').read_bytes(),b'keep samples');self.assertTrue(profile.exists())
 def test_reject_escape_active_unknown_and_links(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);running=self.job(root,'running','running');outside=root/'keep';outside.write_text('preserve')
   for key in ('../keep','C:/Windows','',None,'missing','running'):
    with self.assertRaises((ValueError,OSError)):delete_job(root,key)
   self.assertTrue(running.exists());self.assertEqual(outside.read_text(),'preserve')
   source=self.job(root,'linked')
   try:os.symlink(outside,source/'link')
   except OSError:return
   with self.assertRaises(ValueError):delete_job(root,'linked')
   self.assertTrue(outside.exists())
