import unittest, tempfile, io, json
from pathlib import Path
from unittest.mock import patch
import studio_chat
class ChatTests(unittest.TestCase):
 def reset_warmup(self):
  studio_chat.StudioChat._shared_process=None;studio_chat.StudioChat._active_chat=None;studio_chat.StudioChat._warming=False;studio_chat.StudioChat._warm_thread=None;studio_chat.StudioChat._runtime={'status':'unloaded','mode':None,'model':None}
 def test_preload_is_idempotent_and_first_reply_waits_without_mixing_protocol(self):
  import threading
  self.reset_warmup();self.addCleanup(self.reset_warmup)
  entered=threading.Event();release=threading.Event();errors=[]
  class Output:
   reads=0
   def readline(self):
    self.reads+=1
    if self.reads==1:entered.set();release.wait(3);return json.dumps({'loaded':True})+'\n'
    return json.dumps({'text':'Actual reply'})+'\n'
  class Process:
   stdin=io.StringIO();stdout=Output()
   def poll(self):return None
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   chat=studio_chat.StudioChat(Path(tmp)/'chat.json');chat.process=Process();spec={'id':'test-model'}
   chat.preload('cpu',spec);self.assertTrue(entered.wait(2));self.assertEqual(chat.preload('cpu',spec)['status'],'loading');self.assertEqual(chat.messages,[])
   def reply():
    try:chat.reply({'text':'Real message','mode':'cpu'},[])
    except Exception as error:errors.append(str(error))
   thread=threading.Thread(target=reply);thread.start()
   self.assertEqual(len(chat.process.stdin.getvalue().splitlines()),1)
   with self.assertRaisesRegex(ValueError,'loading'):chat.stop()
   release.set();thread.join(5);self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
   sent=[json.loads(x) for x in chat.process.stdin.getvalue().splitlines()];self.assertTrue(sent[0]['preload']);self.assertNotIn('messages',sent[0]);self.assertEqual(len(sent),2);self.assertEqual(chat.messages[-1]['content'],'Actual reply')
 def test_resource_failure_defers_preload_without_history(self):
  self.reset_warmup();self.addCleanup(self.reset_warmup)
  class Process:
   stdin=io.StringIO();stdout=io.StringIO(json.dumps({'error':'GPU is busy. Use CPU mode.'})+'\n')
   def poll(self):return None
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   chat=studio_chat.StudioChat(Path(tmp)/'chat.json');chat.process=Process();chat.preload('gpu',{'id':'test'});studio_chat.StudioChat._warm_thread.join(3)
   self.assertEqual(chat.runtime_state()['status'],'deferred');self.assertEqual(chat.messages,[]);self.assertFalse(studio_chat.StudioChat._warming)
 def test_admission_allows_first_chat_to_wait_but_prevents_competing_media(self):
  import threading
  from types import SimpleNamespace
  from studio_workspaces import StudioHub
  self.reset_warmup();self.addCleanup(self.reset_warmup);studio_chat.StudioChat._warming=True
  hub=StudioHub.__new__(StudioHub);hub.gate=threading.RLock();hub.store=SimpleNamespace(operation_pins=set());hub.instances={};hub.reserved=False;hub.conversations=SimpleNamespace(busy=lambda:False)
  with hub.admission('/api/chat/send','free-work'):self.assertTrue(hub.reserved)
  with hub.admission('/api/image/generate','free-work'):self.assertFalse(hub.reserved) # submission queues without claiming the GPU
  with self.assertRaises(ValueError):
   with hub.admission('/api/join','free-work'):pass
 def test_local_history_success_error_and_validation(self):
  with tempfile.TemporaryDirectory() as tmp:
   with patch.object(studio_chat,'ROOT',Path(tmp)):
    chat=studio_chat.StudioChat()
   class Process:
    stdin=io.StringIO();stdout=io.StringIO(json.dumps({'text':'A short camera prompt.'})+'\n'+json.dumps({'error':'GPU is busy'})+'\n')
    def poll(self):return None
   chat.process=Process()
   self.assertEqual(chat.reply({'text':'Write a prompt','mode':'cpu'},[])['text'],'A short camera prompt.')
   self.assertEqual(len(chat.messages),2)
   request=json.loads(chat.process.stdin.getvalue().splitlines()[0]);self.assertEqual(request['mode'],'cpu');self.assertNotIn('Lexi',request['messages'][0]['content'])
   with self.assertRaisesRegex(ValueError,'GPU is busy'):chat.reply({'text':'Again'},[])
   self.assertFalse(chat.busy);self.assertEqual(len(chat.messages),2)
   with self.assertRaises(ValueError):chat.reply({'text':'','mode':'cpu'},[])
   chat.clear();self.assertEqual(json.loads(chat.path.read_text()),[]);chat.process=None
 def test_busy_blocks_unload_and_clear(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(studio_chat,'ROOT',Path(tmp)):
   chat=studio_chat.StudioChat();chat.busy=True
   with self.assertRaises(ValueError):chat.stop()
   with self.assertRaises(ValueError):chat.clear()

 def test_other_workspace_cannot_unload_an_active_shared_chat(self):
  import threading
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   a=studio_chat.StudioChat(Path(tmp)/'a/chat.json');b=studio_chat.StudioChat(Path(tmp)/'b/chat.json');entered=threading.Event();release=threading.Event();errors=[]
   class Output:
    def readline(self):entered.set();release.wait(timeout=3);return json.dumps({'text':'Owned reply'})+'\n'
   class Process:
    stdin=io.StringIO();stdout=Output()
    def poll(self):return None
   a.process=Process()
   def reply():
    try:a.reply({'text':'Test','mode':'cpu'},[])
    except Exception as e:errors.append(str(e))
   thread=threading.Thread(target=reply);thread.start();self.assertTrue(entered.wait(2))
   try:
    with self.assertRaisesRegex(ValueError,'current local chat'):b.stop()
   finally:release.set();thread.join();a.process=None
   self.assertEqual(errors,[]);self.assertEqual(a.messages[-1]['content'],'Owned reply');self.assertEqual(b.messages,[])
