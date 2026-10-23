import json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from workspace_store import WorkspaceStore,atomic
from studio_queue import JobQueue

class QueueTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=WorkspaceStore(Path(self.temp.name));self.w=self.store.create('Queue test')['id'];self.launched=[]
  self.hub=SimpleNamespace(store=self.store,gate=threading.RLock(),reserved=False,instances={},busy=lambda **kw:False)
  def start(engine,value):
   self.launched.append((engine,value));row=next(j for j in self.queue.doc['jobs'] if j['id']==value['_queued_id']);atomic(self.queue.file(row),dict(id=row['id'],status='completed',settings=value))
  st=SimpleNamespace(chat=SimpleNamespace(stop=lambda:None),start=lambda v:start('video',v),start_image=lambda v:start('image',v),voice=SimpleNamespace(start=lambda v:start('voice',v),cancel=lambda:None),cancel=lambda:None,cancel_image=lambda:None,image_service=None)
  self.hub.studio=lambda w:st;self.queue=JobQueue(self.hub);self.queue.available_gpu=lambda row:True
 def submit(self,engine='video'):
  return self.queue.enqueue(self.w,engine,dict(prompt='Original prompt',text='Original script',model_spec={'id':'original'},context_snapshot={'revision':2}))
 def test_snapshots_fifo_and_one_running(self):
  a=self.submit();b=self.submit('voice');self.assertEqual(a['status'],'queued');self.queue.tick();self.assertEqual(len(self.launched),1);self.queue.tick();self.assertEqual(len(self.launched),1);self.queue.tick();self.assertEqual(len(self.launched),2);self.assertEqual(self.launched[1][0],'voice');self.assertEqual(self.launched[0][1]['_queued_id'],a['id'])
 def test_reorder_uses_revision_and_full_pending_set(self):
  a=self.submit();b=self.submit('image');rev=self.queue.doc['revision'];self.queue.action(dict(action='reorder',ids=[b['id'],a['id']],revision=rev));self.queue.tick();self.assertEqual(self.launched[0][0],'image')
  with self.assertRaisesRegex(ValueError,'Queue changed'):self.queue.action(dict(action='reorder',ids=[],revision=rev))
 def test_cancel_pending_never_dispatches_and_retry_has_fresh_id(self):
  a=self.submit();self.queue.action(dict(action='cancel',id=a['id']));self.queue.tick();self.assertFalse(self.launched);b=self.queue.action(dict(action='retry',id=a['id']));self.assertNotEqual(a['id'],b['id']);self.assertEqual(b['settings']['context_snapshot']['revision'],2)
 def test_restart_keeps_pending_and_marks_running_interrupted(self):
  a=self.submit();b=self.submit();self.queue.doc['jobs'][0]['status']='running';atomic(self.queue.file(self.queue.doc['jobs'][0]),dict(status='running'));self.queue.save();recovered=JobQueue(self.hub);self.assertEqual([j['status'] for j in recovered.doc['jobs']],['interrupted','queued']);self.assertEqual(recovered.pending()[0]['id'],b['id'])
 def test_external_gpu_or_chat_activity_waits_and_failure_does_not_block_next(self):
  self.submit();self.submit();self.queue.available_gpu=lambda row:False;self.queue.tick();self.assertFalse(self.launched);self.queue.available_gpu=lambda row:True;self.hub.busy=lambda **kw:True;self.queue.tick();self.assertFalse(self.launched);self.hub.busy=lambda **kw:False
  self.hub.studio=lambda w:(_ for _ in ()).throw(ValueError('Input unavailable'));self.queue.tick();self.assertEqual(self.queue.doc['jobs'][0]['status'],'failed');self.assertEqual(self.queue.pending()[0]['status'],'queued')
 def test_pending_project_is_pinned_and_request_is_deep_copied(self):
  value=dict(prompt='Before',model_spec={'id':'chosen'});a=self.queue.enqueue(self.w,'video',value);value['model_spec']['id']='later';self.assertEqual(a['settings']['model_spec']['id'],'chosen')
  with self.assertRaisesRegex(ValueError,'active job'):self.store.update(self.w,{'deleted':True})
 def test_pause_survives_restart_and_orphan_submission_is_recoverable(self):
  a=self.submit();self.queue.action({'action':'pause'});self.queue.tick();self.assertFalse(self.launched)
  self.queue.doc['jobs']=[];self.queue.save();recovered=JobQueue(self.hub)
  self.assertTrue(recovered.state()['paused']);self.assertEqual(recovered.doc['jobs'][0]['status'],'interrupted');self.assertEqual(recovered.doc['jobs'][0]['id'],a['id'])

 def test_gpu_admission_accepts_null_model_memory(self):
  from unittest.mock import patch
  with patch('studio_queue.subprocess.run',return_value=SimpleNamespace(stdout='12000, 2000, 0')):
   for spec in ({'gpu_mib':None},{},{'gpu_mib':8000}):
    self.assertTrue(JobQueue.available_gpu(self.queue,{'settings':{'model_spec':spec}}))
   self.assertFalse(JobQueue.available_gpu(self.queue,{'settings':{'model_spec':{'gpu_mib':11000}}}))
   self.assertFalse(JobQueue.available_gpu(self.queue,{'settings':{'model_spec':None,'sound_model_spec':{'gpu_mib':11000}}}))
 def test_dispatch_failure_is_visible_in_job_and_logged(self):
  from unittest.mock import patch
  self.submit();self.hub.studio=lambda w:(_ for _ in ()).throw(ValueError('Cannot start engine'))
  with patch('studio_diagnostics.LOG.record') as log:
   self.queue.tick();log.assert_called_once()
  job=json.loads(self.queue.file(self.queue.doc['jobs'][0]).read_text(encoding='utf-8'))
  self.assertEqual(job['message'],'Cannot start engine');self.assertEqual(job['phase'],'Failed before generation started')

 def test_running_video_exposes_engine_stage_and_elapsed(self):
  from unittest.mock import patch
  self.submit();self.queue.tick();row=self.queue.doc['jobs'][0]
  atomic(self.queue.file(row),{'status':'running','started':row['started'],'settings':row['settings']})
  with patch('studio.phase',return_value=('Encoding reference and prompt: image encoder',None)):
   self.queue.tick()
  current=self.queue.state()['jobs'][0]
  self.assertEqual(current['phase'],'Encoding reference and prompt: image encoder');self.assertIsNone(current['progress']);self.assertGreaterEqual(current['elapsed'],0)
  with patch('studio.phase',return_value=('Sampling: 4 / 16 steps',25)):
   self.queue.tick()
  self.assertEqual(self.queue.state()['jobs'][0]['progress'],25)
 def test_running_image_preserves_worker_stage(self):
  self.submit('image');self.queue.tick();row=self.queue.doc['jobs'][0]
  atomic(self.queue.file(row),{'status':'running','phase':'Decoding image','progress':0.8})
  self.queue.tick();self.assertEqual(self.queue.state()['jobs'][0]['phase'],'Decoding image');self.assertEqual(row['progress'],0.8)

 def test_pause_continue_keeps_id_and_normalized_settings(self):
  from freevideo_engine.studio_checkpoint import atomic as write
  self.submit();self.submit('image');self.queue.tick();row=self.queue.doc['jobs'][0]
  actual={'id':row['id'],'status':'running','checkpoint_capable':True,'settings':dict(row['settings'],seed=12345),'elapsed':12}
  write(self.queue.file(row),actual)
  self.queue.action(dict(action='pause',id=row['id']));self.assertTrue(self.queue.doc['paused']);self.assertEqual(row['status'],'pausing')
  with self.assertRaisesRegex(ValueError,'Only a paused'):self.queue.action(dict(action='resume',id=row['id']))
  actual.update(status='paused',phase='Paused',elapsed=12);write(self.queue.file(row),actual);self.queue.tick();self.assertEqual(row['status'],'paused')
  self.assertNotIn(self.w,self.queue.owners());self.assertIn(self.w,self.queue.protected_owners())
  checkpoint=self.queue.file(row).parent/'checkpoint';write(checkpoint/'receipt.json',{'version':1})
  restored=JobQueue(self.hub);self.assertEqual(restored.doc['jobs'][0]['status'],'paused')
  self.queue.action(dict(action='resume',id=row['id']));self.assertEqual(row['status'],'queued');self.assertFalse(self.queue.doc['paused']);self.assertTrue(row['settings']['_resume'])
  persisted=json.loads(self.queue.file(row).read_text(encoding='utf-8'));self.assertEqual(persisted['settings']['seed'],12345)
  self.assertEqual(self.queue.pending()[-1]['id'],row['id'])
 def test_legacy_worker_and_missing_checkpoint_cannot_fake_pause(self):
  self.submit();self.queue.tick();row=self.queue.doc['jobs'][0];atomic(self.queue.file(row),dict(status='running',settings=row['settings']))
  with self.assertRaisesRegex(ValueError,'before checkpoint support'):self.queue.action(dict(action='pause',id=row['id']))
  row['status']='paused'
  with self.assertRaisesRegex(ValueError,'missing or invalid'):self.queue.action(dict(action='resume',id=row['id']))
 def test_retry_never_carries_resume_flag_to_a_new_job(self):
  self.submit();row=self.queue.doc['jobs'][0];row.update(status='failed');row['settings']['_resume']=True
  retry=self.queue.action(dict(action='retry',id=row['id']));self.assertNotIn('_resume',retry['settings'])
