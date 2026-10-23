import unittest
import numpy as np
from sound_script import parse_script,mix_plan,sound_cues

class SoundScriptTests(unittest.TestCase):
 def test_descriptions_are_removed_from_spoken_text_and_order_preserved(self):
  plan=parse_script('{rain} Oh, LOOK! a car!! <car honking> It is loud. {stop} Quiet now.')
  self.assertEqual([p['kind'] for p in plan],['background','speech','action','speech','background_stop','speech'])
  self.assertEqual([p['text'] for p in plan if p['kind']=='speech'],['Oh, LOOK! a car!!','It is loud.','Quiet now.'])
  self.assertEqual(len(sound_cues(plan)),2)
 def test_options_and_malformed_cues(self):
  plan=parse_script('<horn | 2s | -6dB> <pause: 1s>')
  self.assertEqual(plan[0]['seconds'],2);self.assertEqual(plan[0]['db'],-6);self.assertEqual(plan[1]['seconds'],1)
  for text in ('<unclosed','{nested <cue>}','<horn | 100s>','<horn | 3dB>','<pause: 31s>','< >','<horn>'*13):
   with self.assertRaises(ValueError,msg=text):parse_script(text)
  self.assertEqual(parse_script(r'Use \< and \{ literally')[0]['text'],'Use < and { literally')
 def test_action_is_sequential_while_background_overlays_until_stopped(self):
  rate=1000;plan=parse_script('{wind | 1s | -20dB} First <horn | 1s | 0dB> Next {stop} Last')
  def load(index,part):return np.full(rate,.5 if part['kind']=='action' else .1 if part['kind']=='speech' else .2,dtype=np.float32),rate
  audio,timeline=mix_plan(plan,load,rate)
  self.assertEqual(len(audio),4000)
  self.assertAlmostEqual(float(audio[500]),.12,places=4);self.assertAlmostEqual(float(audio[1500]),.52,places=4);self.assertAlmostEqual(float(audio[3500]),.1,places=4)
  self.assertEqual(next(row for row in timeline if row['kind']=='background')['end'],3)
 def test_background_only_action_only_and_clipping_protection(self):
  def load(index,part):return np.ones(500,dtype=np.float32),1000
  audio,_=mix_plan(parse_script('{rain | 2s | 0dB}'),load,1000);self.assertEqual(len(audio),2000);self.assertLessEqual(np.max(np.abs(audio)),.981)
  audio,_=mix_plan(parse_script('<horn | 1s>'),load,1000);self.assertEqual(len(audio),500)
 def test_rate_conversion_preserves_speech_duration(self):
  audio,_=mix_plan(parse_script('Hello'),lambda i,p:(np.ones(16000,dtype=np.float32)*.2,16000),24000)
  self.assertEqual(len(audio),24000)
