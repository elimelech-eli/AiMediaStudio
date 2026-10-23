import json,os,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from studio_files import atomic_json
from studio_diagnostics import Diagnostics
import studio

class DiagnosticTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
 def test_transient_windows_lock_retries_and_preserves_old_file(self):
  file=self.root/'job.json';atomic_json(file,{'status':'running'});replace=os.replace;seen=[]
  def locked(source,target):
   seen.append(str(source))
   if len(seen)<3:self.assertEqual(json.loads(file.read_text())['status'],'running');raise PermissionError(5,'Access is denied')
   replace(source,target)
  with patch('studio_files.os.replace',side_effect=locked),patch('studio_files.time.sleep'):atomic_json(file,{'status':'completed'})
  self.assertEqual(json.loads(file.read_text())['status'],'completed');self.assertEqual(len(seen),3);self.assertEqual(list(self.root.glob('*.tmp')),[])
 def test_concurrent_writes_are_whole_json_and_do_not_share_tempfiles(self):
  file=self.root/'job.json';errors=[]
  def save(index):
   try:atomic_json(file,{'writer':index,'payload':'x'*5000})
   except Exception as error:errors.append(error)
  threads=[threading.Thread(target=save,args=(n,)) for n in range(12)]
  for thread in threads:thread.start()
  for thread in threads:thread.join()
  self.assertEqual(errors,[]);self.assertEqual(len(json.loads(file.read_text())['payload']),5000);self.assertEqual(list(self.root.glob('*.tmp')),[])
 def test_failed_replace_keeps_previous_data_and_cleans_tempfile(self):
  file=self.root/'job.json';atomic_json(file,{'old':True})
  with patch('studio_files.os.replace',side_effect=PermissionError(5,'Denied')),patch('studio_files.time.sleep'):
   with self.assertRaises(PermissionError):atomic_json(file,{'new':True})
  self.assertEqual(json.loads(file.read_text()),{'old':True});self.assertEqual(list(self.root.glob('*.tmp')),[])
 def test_progress_lock_does_not_abort_image_generation(self):
  app=studio.Studio.__new__(studio.Studio);app.directory=self.root;app.lock=threading.RLock();app.image_current='job';app.image_states={}
  output=self.root/'uploads/freevideo-image/result.png';output.parent.mkdir(parents=True);output.write_bytes(b'local fixture image')
  folder=self.root/'image-jobs/job';folder.mkdir(parents=True);row=dict(id='job',status='running',started=0,settings={'workspace_id':'fixture'})
  app.image_service=Mock();app.image_service.status.side_effect=[{'phase':'loading','stage':'load','fraction':0},{'phase':'complete','file':'freevideo-image/result.png'}]
  original=studio.write_json;calls=[]
  def save(path,value):
   calls.append(1)
   if len(calls)==1:raise PermissionError(5,'Access is denied')
   original(path,value)
  log=Diagnostics(self.root/'logs')
  with patch.object(studio,'write_json',side_effect=save),patch.object(studio.time,'sleep'),patch.object(studio,'LOG',log):app.finish_image(folder,row,'worker')
  self.assertEqual(json.loads((folder/'job.json').read_text())['status'],'completed');self.assertIsNone(app.image_current);app.image_service.cancel.assert_not_called();self.assertTrue(any(x['level']=='warning' for x in log.events()))
 def test_logs_redact_credentials_and_do_not_fail_application_when_unwritable(self):
  log=Diagnostics(self.root/'logs');log.record('error','image','Access denied',details='Bearer secret-value token=another-secret')
  event=log.events()[0];self.assertNotIn('secret',event['details']);self.assertIn('[redacted]',event['details'])
  with patch.object(Path,'mkdir',side_effect=PermissionError(5,'Denied')):self.assertTrue(log.record('error','http','Still return the API error'))
  self.assertTrue(log.last_error)
  with self.assertRaises(ValueError):log.view(source='../arbitrary-file')

if __name__=='__main__':unittest.main()
