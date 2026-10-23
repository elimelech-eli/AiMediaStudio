import tempfile,unittest,json
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from studio_attachments import decode_text,excerpt,prepare

class AttachmentTests(unittest.TestCase):
 def test_text_decoding_and_binary_rejection(self):
  self.assertEqual(decode_text('hello'.encode('utf-16')),'hello')
  self.assertEqual(decode_text(b'\xef\xbb\xbfhello'),'hello')
  for raw in (b'binary\0data',b'\xff\xff',b'a'*(2*1024*1024+1)):
   with self.assertRaises(ValueError):decode_text(raw)
 def test_large_text_is_explicitly_excerpted_and_query_relevant(self):
  text='A'*10000+'\nunique revenue 12345\n'+'B'*5000
  result,truncated=excerpt(text,'unique revenue',3600)
  self.assertTrue(truncated);self.assertIn('revenue 12345',result);self.assertLess(len(result),3800)
 def test_attachment_access_uses_current_workspace_and_reads_real_contents(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'data.csv';p.write_text('name,total\nAlice,42',encoding='utf-8')
   store=Mock();store.asset.return_value=({'id':'a'*32,'name':'data.csv','kind':'documents'},p)
   rows,notes,visual=prepare(Mock(store=store),'project-A',[{'asset':'a'*32}],'total?')
   store.asset.assert_called_once_with('project-A','a'*32);self.assertIn('Alice,42',notes);self.assertEqual(visual,[])
   store.asset.side_effect=ValueError('Asset not found in this workspace')
   with self.assertRaises(ValueError):prepare(Mock(store=store),'project-B',[{'asset':'a'*32}],'')
 def test_real_image_is_encoded_and_invalid_items_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'test.png';Image.new('RGB',(64,64),'red').save(p)
   store=Mock();store.asset.return_value=({'id':'a'*32,'name':'red','kind':'images'},p)
   _,_,visual=prepare(Mock(store=store),'free-work',[{'asset':'a'*32}],'color?')
   self.assertTrue(visual[0]['url'].startswith('data:image/jpeg;base64,'))
   for items in ([{}]*5,[{'path':'C:/secret.txt'}],{}):
    with self.assertRaises(ValueError):prepare(Mock(store=store),'free-work',items,'')

 def test_low_framerate_video_is_sampled_without_seeking_past_last_frame(self):
  import subprocess
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'uploads').mkdir();p=root/'clip.mp4';ffmpeg=Path(__file__).parent.parent/'media-runtime/ffmpeg/ffmpeg.exe'
   subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc=size=64x64:rate=1:duration=3','-pix_fmt','yuv420p','-threads','1','-y',str(p)],check=True,capture_output=True)
   store=Mock();store.asset.return_value=({'id':'a'*32,'name':'clip','kind':'videos'},p);store.folder.return_value=root
   _,notes,visual=prepare(Mock(store=store),'free-work',[{'asset':'a'*32}],'')
   self.assertEqual(len(visual),4);self.assertIn('audio is not analyzed',notes);self.assertEqual(list((root/'uploads').iterdir()),[])
