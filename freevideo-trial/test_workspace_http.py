import http.client,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import studio
from studio_workspaces import StudioHub
from workspace_store import WorkspaceStore,atomic
from studio_diagnostics import Diagnostics
class ProjectHTTPTests(unittest.TestCase):
 def test_project_import_copy_scope_range_and_trash(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   root=Path(tmp);store=WorkspaceStore(root);atomic(root/'migration.json',{'state':'complete'});hub=StudioHub(root)
   server=studio.ThreadingHTTPServer(('127.0.0.1',0),studio.Handler);server.hub=hub;server.studio=hub.studio('free-work');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();port=server.server_address[1]
   def call(path,value=None,w='free-work',extra=None):
    c=http.client.HTTPConnection('127.0.0.1',port);headers={'Host':f'127.0.0.1:{port}','Origin':f'http://127.0.0.1:{port}','X-Studio-Token':studio.TOKEN,'X-Studio-Workspace':w,**(extra or {})};c.request('POST' if value is not None else 'GET',path,json.dumps(value) if value is not None else None,headers);r=c.getresponse();status=r.status;body=r.read();c.close();return status,body
   try:
    with patch.object(studio,'PORT',port),patch.object(studio,'LOG',Diagnostics(root/'logs')):
     status,body=call('/api/workspaces/create',{'name':'Test project'});self.assertEqual(status,201);p=json.loads(body)['id']
     source=root/'input.txt';source.write_text('Shared context test');a=store.import_file('free-work',source)
     status,body=call('/api/assets/action',{'action':'copy','id':a['id'],'destination':p});self.assertEqual(status,200);copy=json.loads(body)
     self.assertEqual(call('/asset/'+copy['id'],w='free-work')[0],400)
     status,body=call('/asset/'+copy['id'],w=p,extra={'Range':'bytes=0-5'});self.assertEqual(status,206);self.assertEqual(body,b'Shared')
     self.assertEqual(call('/api/assets/action',{'action':'trash','id':copy['id']},p)[0],200)
     self.assertEqual(call('/asset/'+copy['id'],w=p)[0],400)
     self.assertEqual(call('/api/assets/action',{'action':'restore','id':copy['id']},p)[0],200)
     status,body=call('/api/chats/action',{'action':'create','name':'HTTP named chat'},p);self.assertEqual(status,200);chat=json.loads(body)['id']
     status,body=call('/api/tree');self.assertEqual(status,200);self.assertTrue(any(x['id']==p and len(x['chats'])==1 for x in json.loads(body)['projects']))
     status,body=call('/api/state',w=p,extra={'X-Studio-Chat':chat});self.assertEqual(status,200);self.assertEqual(json.loads(body)['chat']['messages'],[])
     self.assertEqual(call('/api/state',w='free-work',extra={'X-Studio-Chat':chat})[0],400)
     self.assertEqual(call('/api/chat/state',w=p,extra={'X-Studio-Chat':chat})[0],200)
     background='20261017-123457-abcdef13';background_folder=store.folder(p)/'jobs'/background;atomic(background_folder/'job.json',{'id':background,'status':'completed','settings':{'prompt':'Background completion'}});(background_folder/'video.mp4').write_bytes(b'immutable fixture video bytes')
     status,body=call('/api/tree');self.assertTrue(any(a['name']=='Background completion' for x in json.loads(body)['projects'] if x['id']==p for a in x['assets']))
     failed='20261017-123456-abcdef12';atomic(store.folder(p)/'jobs'/failed/'job.json',{'id':failed,'status':'failed','settings':{'prompt':'Failed fixture'}})
     status,body=call('/api/tree');self.assertTrue(any(j['id']==failed for x in json.loads(body)['projects'] for j in x['jobs']))
     status,body=call('/api/job/status?kind=video&id='+failed,w=p);self.assertEqual(status,200);self.assertEqual(json.loads(body)['status'],'failed')
     status,body=call('/api/job/status?kind=video&id='+failed,w='free-work');self.assertEqual(status,400);error_id=json.loads(body)['error_id']
     status,body=call('/api/logs');self.assertEqual(status,200);self.assertTrue(any(row['id']==error_id for row in json.loads(body)['events']))
     self.assertEqual(call('/api/logs?source=../../arbitrary')[0],400)
     self.assertEqual(call('/api/jobs/hide',{'id':failed,'kind':'videos'},p)[0],200)
     self.assertEqual(call('/api/jobs/hide',{'id':'../escape','kind':'videos'},p)[0],400)

     self.assertEqual(call('/api/workspace/archive',{},p)[0],200);doc=store.get(p);self.assertTrue(doc['archived']);self.assertTrue((hub.portable.exports/doc['archive_file']).is_file())
     self.assertEqual(call('/api/chats/action',{'action':'create'},p)[0],400)
     self.assertEqual(call('/api/workspace/update',{'archived':False},p)[0],200)
     hub.studio('free-work').current='running'
     self.assertEqual(call('/api/workspace/update',{'archived':True},'free-work')[0],400)
   finally:server.shutdown();server.server_close();thread.join()
