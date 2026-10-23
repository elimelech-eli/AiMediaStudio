import tempfile,unittest,json
from pathlib import Path
from types import SimpleNamespace
from workspace_store import WorkspaceStore,atomic
from studio_conversations import Conversations
from workspace_portable import PortableProjects

class ProjectTreeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=WorkspaceStore(Path(self.temp.name));self.hub=SimpleNamespace(store=self.store,active=lambda:None);self.chats=Conversations(self.hub);self.portable=PortableProjects(self.store,self.store.root/'shared/voices/profiles')
 def test_named_histories_duplicate_move_trash(self):
  w=self.store.create('First')['id'];dest=self.store.create('Other')['id'];a=self.chats.action(w,dict(action='create',name='Script'))['id'];instance=self.chats.instance(w,a);instance.messages=[dict(role='user',content='Original')];instance.save()
  b=self.chats.action(w,dict(action='duplicate',id=a,name='Alternative'))['id'];self.assertEqual(self.chats.get(w,b)['messages'],instance.messages)
  instance.messages.append(dict(role='assistant',content='Only original'));instance.save();self.assertEqual(len(self.chats.get(w,b)['messages']),1)
  moved=self.chats.action(w,dict(action='move',id=b,destination=dest))['id'];self.assertEqual(len(self.chats.get(dest,moved)['messages']),1)
  with self.assertRaises(ValueError):self.chats.get(w,b)
  self.chats.action(w,dict(action='restore',id=b));self.assertEqual(self.chats.get(w,b)['name'],'Alternative')
 def test_branch_and_zip_preserve_all_chats(self):
  w=self.store.create('Source')['id']
  for name in ('A','B'):self.chats.action(w,dict(action='create',name=name))
  branch=self.portable.branch(w,'Branch',chat=True);self.assertEqual({x['name'] for x in branch['chats'].values()},{'A','B'})
  result=self.portable.export(w,chat=True);restored=self.portable.import_zip(self.portable.exports/result['file']);self.assertEqual(len(restored['chats']),2)
 def test_active_chat_and_archive_are_readonly(self):
  w=self.store.create('Source')['id'];a=self.chats.action(w,dict(action='create'))['id'];instance=self.chats.instance(w,a);instance.busy=True
  with self.assertRaises(ValueError):self.chats.action(w,dict(action='trash',id=a))
  instance.busy=False;self.store.update(w,dict(archived=True))
  with self.assertRaises(ValueError):self.chats.action(w,dict(action='create'))
 def test_verified_archive_reclaim_and_restore(self):
  from workspace_archive import reclaim,restore_assets
  from workspace_store import digest
  w=self.store.create('Archived')['id'];source=self.store.root/'test.txt';source.write_text('Keep every byte');a=self.store.import_file(w,source);self.chats.action(w,dict(action='create',name='Kept chat'))
  output=self.portable.export(w,chat=True);doc=self.store.update(w,dict(archived=True));doc.update(archive_file=output['file'],archive_sha256=digest(self.portable.exports/output['file']));self.store.save(doc)
  reclaim(self.store,self.portable.exports,w);self.assertFalse((self.store.folder(w)/a['path']).exists());self.assertEqual(len(self.chats.rows(w)),1)
  restore_assets(self.store,self.portable.exports,w);self.assertEqual((self.store.folder(w)/a['path']).read_text(),'Keep every byte');self.assertFalse(self.store.get(w)['archive_reclaimed'])
 def test_corrupt_archive_cannot_reclaim(self):
  from workspace_archive import reclaim
  w=self.store.create('Archived')['id'];source=self.store.root/'test.txt';source.write_text('Original');a=self.store.import_file(w,source);output=self.portable.export(w);doc=self.store.update(w,dict(archived=True));doc.update(archive_file=output['file'],archive_sha256='bad');self.store.save(doc)
  with self.assertRaises(ValueError):reclaim(self.store,self.portable.exports,w)
  self.assertTrue((self.store.folder(w)/a['path']).exists())
 def test_legacy_history_is_imported_once(self):
  atomic(self.store.folder('free-work')/'conversations/chat.json',[dict(role='user',content='Keep me')]);self.assertEqual(len(self.chats.rows('free-work')),1);self.assertEqual(len(self.chats.rows('free-work')),1)

if __name__=='__main__':unittest.main()
