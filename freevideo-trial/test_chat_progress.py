import io,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from studio_chat import StudioChat
from unittest.mock import patch

class ChatProgressTests(unittest.TestCase):
 def test_stop_is_scoped_to_current_reply(self):
  with tempfile.TemporaryDirectory() as folder,patch('studio_chat.ROOT',Path(folder)):
   chat=StudioChat(Path(folder)/'chat.json');chat.busy=True;chat.request_id='a'*32
   with self.assertRaisesRegex(ValueError,'no longer'):chat.cancel_reply('b'*32)
   chat.cancel_reply('a'*32);self.assertTrue((Path(folder)/('studio-data/chat-runtime/cancel-'+'a'*32)).exists());self.assertEqual(chat.phase,'Stopping reply')
   chat.busy=False
   with self.assertRaises(ValueError):chat.cancel_reply('a'*32)
 def test_stopped_reply_keeps_partial_history(self):
  with tempfile.TemporaryDirectory() as folder:
   chat=StudioChat(Path(folder)/'chat.json');old=StudioChat._shared_process
   try:
    StudioChat._shared_process=SimpleNamespace(poll=lambda:None,stdin=io.StringIO(),stdout=io.StringIO(json.dumps({'event':'delta','text':'Preserved partial answer.'})+'\n'+json.dumps({'text':'Preserved partial answer.','stopped':True})+'\n'))
    result=chat.reply({'text':'A long answer please','mode':'cpu'},[])
    self.assertTrue(result['stopped']);self.assertEqual(chat.messages[-1]['content'],'Preserved partial answer.');self.assertTrue(chat.messages[-1]['stopped']);self.assertFalse(chat.busy);self.assertEqual(json.loads(chat.path.read_text(encoding='utf-8'))[-1]['content'],'Preserved partial answer.')
   finally:StudioChat._shared_process=old
 def test_deltas_are_visible_before_final_response_and_not_saved_as_history(self):
  with tempfile.TemporaryDirectory() as folder:
   chat=StudioChat(Path(folder)/'chat.json');chat.busy=True;chat.started=time.monotonic()
   old=StudioChat._shared_process
   try:
    def rows():
     yield json.dumps({'event':'phase','phase':'Loading local model'})+'\n'
     yield json.dumps({'event':'delta','text':'Hello '})+'\n'
     self.assertEqual(chat.state()['partial'],'Hello ');self.assertEqual(chat.state()['messages'],[])
     yield json.dumps({'event':'delta','text':'there'})+'\n'
     yield json.dumps({'text':'Hello there'})+'\n'
    stream=iter(rows());StudioChat._shared_process=SimpleNamespace(stdout=SimpleNamespace(readline=lambda:next(stream,'')))
    self.assertEqual(chat.read_reply(),{'text':'Hello there'});self.assertEqual(chat.state()['partial'],'Hello there')
    chat.busy=False;self.assertEqual(chat.state()['partial'],'');self.assertFalse(chat.path.exists())
   finally:StudioChat._shared_process=old
 def test_error_result_and_worker_disconnect(self):
  with tempfile.TemporaryDirectory() as folder:
   chat=StudioChat(Path(folder)/'chat.json');old=StudioChat._shared_process
   try:
    StudioChat._shared_process=SimpleNamespace(stdout=io.StringIO('{"error":"failure"}\n'))
    self.assertEqual(chat.read_reply(),{'error':'failure'})
    with self.assertRaisesRegex(ValueError,'stopped unexpectedly'):chat.read_reply()
   finally:StudioChat._shared_process=old
