import json,tempfile,unittest,zipfile
from pathlib import Path
from workspace_store import WorkspaceStore,atomic
from workspace_portable import PortableProjects
class PortableTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp');self.root=Path(self.temp.name);self.store=WorkspaceStore(self.root/'work');self.profiles=self.root/'voices';self.profiles.mkdir();self.portable=PortableProjects(self.store,self.profiles)
  self.source=self.root/'sample.txt';self.source.write_text('Portable asset');self.project=self.store.create('Original')['id'];self.asset=self.store.import_file(self.project,self.source)
 def tearDown(self):self.temp.cleanup()
 def test_branch_survives_source_project_purge_and_snapshot_restore(self):
  atomic(self.store.folder(self.project)/'conversations/chat.json',[{'role':'user','content':'Snapshot chat'}])
  snap=self.store.snapshot(self.project,'Version one',include_chat=True)
  branch=self.portable.branch(self.project,'Independent',snap['id'],True)
  copied=list(branch['assets'].values())[0];self.assertNotEqual(copied['id'],self.asset['id'])
  self.store.update(self.project,{'deleted':True});self.store.purge_workspace(self.project)
  self.assertEqual(self.store.asset(branch['id'],copied['id'])[1].read_text(),'Portable asset')
  self.assertEqual(json.loads((self.store.folder(branch['id'])/'conversations/chat.json').read_text())[0]['content'],'Snapshot chat')
 def test_export_import_and_reject_archive_escape(self):
  exported=self.portable.export(self.project);result=self.portable.import_zip(self.portable.exports/exported['file'])
  self.assertNotEqual(result['id'],self.project);self.assertEqual(len(result['assets']),1)
  unsafe=self.root/'unsafe.zip'
  with zipfile.ZipFile(unsafe,'w') as archive:archive.writestr('../outside.txt','blocked')
  with self.assertRaises(ValueError):self.portable.import_zip(unsafe)
  self.assertFalse((self.root/'outside.txt').exists())
 def test_verified_branch_recovers_and_graph_copy_remaps_dependencies(self):
  second=self.store.import_file(self.project,self.source,metadata={'required':[self.asset['id']]})
  copied=self.store.transfer(self.project,second['id'],'free-work')
  self.assertEqual(len(self.store.assets('free-work')),2);self.assertNotEqual(copied['metadata']['required'][0],self.asset['id'])
  def fail(phase):
   if phase=='portable_verified':raise OSError('power loss')
  self.store.failpoint=fail
  with self.assertRaises(OSError):self.portable.branch(self.project,'Recovered')
  self.store.failpoint=lambda phase:None;self.portable.recover()
  self.assertTrue(any(w['name']=='Recovered' for w in self.store.listing()))
 def test_import_rejects_executable_asset_type(self):
  import hashlib
  doc=self.store.get(self.project);row=doc['assets'][self.asset['id']];payload=b'<html>blocked</html>';row.update(kind='images',path='assets/images/unsafe.html',bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
  archive=self.root/'unsafe-type.zip'
  with zipfile.ZipFile(archive,'w') as output:output.writestr('workspace.json',json.dumps(doc));output.writestr(row['path'],payload)
  with self.assertRaisesRegex(ValueError,'extension'):self.portable.import_zip(archive)
