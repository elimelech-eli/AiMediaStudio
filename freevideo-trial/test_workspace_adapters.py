import tempfile,unittest,json,threading
from pathlib import Path
import studio
from studio_workspaces import StudioHub
from workspace_store import WorkspaceStore,atomic
class AdapterTests(unittest.TestCase):
 def test_image_handoff_is_allowed_while_source_project_has_pending_work(self):
  from PIL import Image
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   root=Path(tmp);store=WorkspaceStore(root/'work');atomic(store.root/'migration.json',{'state':'complete'});hub=StudioHub(store.root);source=root/'reference.png';Image.new('RGB',(8,8),'red').save(source)
   asset=hub.store.import_file('free-work',source);hub.queue.enqueue('free-work','video',{'prompt':'Pending render'})
   result=hub.mutate_asset('free-work',{'action':'use','id':asset['id']});self.assertTrue(result['image'].endswith('.png'))
   with self.assertRaisesRegex(ValueError,'active workspace'):hub.mutate_asset('free-work',{'action':'trash','id':asset['id']})
 def test_workspace_paths_are_owned_by_request_and_worker(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   root=Path(tmp);a=studio.Studio(root/'a');b=studio.Studio(root/'b')
   for s,value in [(a,'a'),(b,'b')]:
    path=Path(s.directory)/'jobs'/value;path.mkdir();(path/'video.mp4').write_bytes(b'test video');atomic(path/'job.json',dict(id=value,status='completed',settings={}))
   self.assertEqual(a.history()[0]['id'],'a');self.assertEqual(b.history()[0]['id'],'b')
   self.assertNotEqual(a.chat.path,b.chat.path)
   barrier=threading.Barrier(2);found=[]
   def scoped(s):
    with studio.workspace_scope(s.directory):barrier.wait();found.append(studio.jobs_root())
   t=threading.Thread(target=scoped,args=(a,));t.start();scoped(b);t.join();self.assertEqual(set(found),{root/'a/jobs',root/'b/jobs'})
 def test_global_admission_and_project_state(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   root=Path(tmp);store=WorkspaceStore(root);p=store.create('Other')['id'];atomic(root/'migration.json',{'state':'complete'});hub=StudioHub(root);a=hub.studio('free-work');b=hub.studio(p)
   a.current='test-job'
   with self.assertRaisesRegex(ValueError,'active'): 
    with hub.admission('/api/join'):pass
   self.assertEqual(hub.active()['workspace'],'free-work');a.current=None
   with hub.admission('/api/chat/send'):
    self.assertIs(hub.studio(p),b)
    with self.assertRaises(ValueError):
     with hub.admission('/api/join'):pass
   self.assertFalse(hub.reserved)
 def test_context_snapshots_stale_proposals_and_exact_voice_script(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   root=Path(tmp);store=WorkspaceStore(root);atomic(root/'migration.json',{'state':'complete'});hub=StudioHub(root)
   store.context('free-work',dict(revision=0,brief='Coastal scene',style='Warm illustration'))
   result=hub.capture('free-work','video',dict(prompt='A camera pan.',context_revision=1))
   self.assertIn('Warm illustration',result['prompt']);self.assertEqual(result['user_prompt'],'A camera pan.')
   exact='Read only this. 😊';voice=hub.capture('free-work','voice',dict(text=exact));self.assertEqual(voice['text'],exact)
   store.context('free-work',dict(revision=1,brief='Changed'))
   self.assertEqual(result['context_snapshot']['brief'],'Coastal scene')
   with self.assertRaisesRegex(ValueError,'changed'):hub.capture('free-work','image',dict(prompt='test',context_revision=1))
   with self.assertRaisesRegex(ValueError,'another'):hub.capture('free-work','image',dict(prompt='test',proposal_workspace='a'*32))
   self.assertEqual(hub.capture('free-work','image',dict(prompt='Exact',use_context=False))['prompt'],'Exact')
 def test_publication_preserves_concurrent_context_edits_and_snapshots(self):
  from unittest.mock import patch
  from workspace_store import digest as real_digest
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   root=Path(tmp);store=WorkspaceStore(root);atomic(root/'migration.json',{'state':'complete'});hub=StudioHub(root);image=store.folder('free-work')/'uploads/fixture.png';image.write_bytes(b'immutable local test bytes');changed=[]
   def during_hash(path):
    if not changed:
     changed.append(True);hub.store.context('free-work',dict(revision=0,brief='Concurrent edit'));hub.store.snapshot('free-work','Concurrent snapshot')
    return real_digest(path)
   with patch('studio_workspaces.digest',side_effect=during_hash):hub.publish('free-work')
   current=hub.store.get('free-work');self.assertEqual(current['context']['brief'],'Concurrent edit');self.assertEqual(len(current['snapshots']),1);self.assertEqual(len(current['assets']),1)
