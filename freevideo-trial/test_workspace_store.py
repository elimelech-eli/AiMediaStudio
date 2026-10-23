import json,tempfile,unittest
from pathlib import Path
from workspace_store import WorkspaceStore
class StoreTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp');self.root=Path(self.temp.name);self.store=WorkspaceStore(self.root/'work');self.src=self.root/'sample.txt';self.src.write_text('immutable sample');self.project=self.store.create('A project')['id']
 def tearDown(self):self.temp.cleanup()
 def test_import_copy_move_and_index_rebuild(self):
  a=self.store.import_file('free-work',self.src);copy=self.store.transfer('free-work',a['id'],self.project)
  self.assertNotEqual(a['id'],copy['id']);self.assertEqual(self.src.read_text(),'immutable sample')
  self.store.trash(self.project,copy['id']);self.store.purge(self.project,copy['id'])
  moved=self.store.transfer('free-work',a['id'],self.project,True);self.assertEqual(moved['id'],a['id']);self.assertEqual(self.store.assets('free-work'),[])
  self.store.rebuild();self.assertEqual(len(self.store.listing()),2)
 def test_crash_recovery_publication_and_move(self):
  def fail(stage):
   if stage=='published':raise OSError('simulated power loss')
  self.store.failpoint=fail
  with self.assertRaises(OSError):self.store.import_file('free-work',self.src)
  self.store=WorkspaceStore(self.root/'work');self.assertEqual(len(self.store.assets('free-work')),1)
  a=self.store.assets('free-work')[0]
  def fail_move(stage):
   if stage=='move_published':raise OSError('simulated power loss')
  self.store.failpoint=fail_move
  with self.assertRaises(OSError):self.store.transfer('free-work',a['id'],self.project,True)
  self.store=WorkspaceStore(self.root/'work');self.assertEqual(self.store.assets('free-work'),[]);self.assertEqual(self.store.assets(self.project)[0]['id'],a['id'])
 def test_scope_dependency_context_and_snapshot_pins(self):
  a=self.store.import_file('free-work',self.src)
  with self.assertRaises(ValueError):self.store.asset(self.project,a['id'])
  with self.assertRaises(ValueError):self.store.get('../escape')
  snap=self.store.snapshot('free-work','Keep');self.store.trash('free-work',a['id'])
  with self.assertRaisesRegex(ValueError,'snapshot'):self.store.purge('free-work',a['id'])
  self.store.remove_snapshot('free-work',snap['id']);self.store.trash('free-work',a['id'],True)
  self.store.import_file('free-work',self.src,metadata={'required':[a['id']]})
  self.store.trash('free-work',a['id'])
  self.store.purge('free-work',a['id'])
  self.assertEqual(len(self.store.assets('free-work')),1)
  self.store.context(self.project,dict(revision=0,brief='A brief'))
  with self.assertRaises(ValueError):self.store.context(self.project,dict(revision=0,brief='stale'))
 def test_idempotent_import_retains_edits_and_free_work_protection(self):
  operation='a'*32;a=self.store.import_file('free-work',self.src,operation=operation);self.store.edit_asset('free-work',a['id'],{'name':'Renamed'})
  again=self.store.import_file('free-work',self.src,operation=operation);self.assertEqual(again['name'],'Renamed');self.assertEqual(len(self.store.assets('free-work')),1)
  with self.assertRaises(ValueError):self.store.update('free-work',{'deleted':True})
 def test_cancelled_transfer_preserves_source_and_purge_recovers(self):
  a=self.store.import_file('free-work',self.src);operation='b'*32;self.store.cancelled.add(operation)
  with self.assertRaises(InterruptedError):self.store.transfer('free-work',a['id'],self.project,operation_id=operation)
  self.assertEqual(len(self.store.assets('free-work')),1);self.assertEqual(self.store.assets(self.project),[])
  self.store.trash('free-work',a['id'])
  def fail(phase):
   if phase=='purge_catalog':raise OSError('power loss')
  self.store.failpoint=fail
  with self.assertRaises(OSError):self.store.purge('free-work',a['id'])
  self.store=WorkspaceStore(self.root/'work');self.assertEqual(self.store.assets('free-work',True),[])

 def test_completed_output_survives_bulk_reference_deletion_and_transfer(self):
  reference=self.store.import_file('free-work',self.src)
  output=self.store.import_file('free-work',self.src,metadata={'required':[reference['id']]})
  self.store.batch_trash('free-work',[reference['id']])
  self.assertEqual(len(self.store.transfer_plan('free-work',output['id'])['assets']),1)
  self.store.purge('free-work',reference['id'])
  row,path=self.store.asset('free-work',output['id'])
  self.assertEqual(path.read_text(),'immutable sample')
  self.assertEqual(row['metadata']['required'],[])
  self.assertIn(reference['id'],row['metadata']['omitted_required'])
  self.store.transfer('free-work',output['id'],self.project)
 def test_busy_workspace_still_protects_reference_deletion(self):
  reference=self.store.import_file('free-work',self.src)
  self.store.pins.add('free-work')
  with self.assertRaises(ValueError):self.store.trash('free-work',reference['id'])
  with self.assertRaises(ValueError):self.store.batch_trash('free-work',[reference['id']])
