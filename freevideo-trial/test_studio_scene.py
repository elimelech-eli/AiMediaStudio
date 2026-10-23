import json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from workspace_store import WorkspaceStore
from studio_scene import capture
from studio_characters import remap_settings,voice_ids

class SceneTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp');self.root=Path(self.temp.name);self.store=WorkspaceStore(self.root/'work');self.w=self.store.create('Scene')['id'];doc=self.store.get(self.w);self.cid='a'*32;doc['characters']={self.cid:dict(id=self.cid,name='Mira',trashed=False)};self.store.save(doc);self.hub=SimpleNamespace(store=self.store);self.rid='b'*32
 def tearDown(self):self.temp.cleanup()
 def value(self,**scene):return dict(prompt='A sunny kitchen, fixed camera.',audio_mode='generated',scene=dict(roles=[dict(id=self.rid,character=self.cid,actions='Makes coffee.',speech={'mode':'none'})],beats=[dict(role=self.rid,action='Sets the mug down.')],**scene))
 def test_compiles_scoped_character_actions_and_ordered_beats(self):
  result=capture(self.hub,self.w,self.value());self.assertIn('Mira: Makes coffee.',result['prompt']);self.assertIn('1. Mira: Sets the mug down.',result['prompt']);self.assertEqual(result['character_ids'],[self.cid]);self.assertFalse(result['scene_snapshot']['speech_pending'])
 def test_speech_requires_explicit_visual_only_and_is_not_rendered_as_dialogue(self):
  value=self.value();value['scene']['roles'][0]['speech']={'mode':'text','text':'Your coffee is ready.'}
  with self.assertRaisesRegex(ValueError,'lip-sync'):capture(self.hub,self.w,value)
  value['scene']['visual_only']=True;result=capture(self.hub,self.w,value);self.assertNotIn('Your coffee is ready.',result['prompt']);self.assertEqual(result['audio_mode'],'silent');self.assertEqual(result['scene_snapshot']['roles'][0]['speech']['text'],'Your coffee is ready.')
 def test_rejects_foreign_character_and_dangling_beats(self):
  value=self.value();value['scene']['roles'][0]['character']='c'*32
  with self.assertRaisesRegex(ValueError,'this project'):capture(self.hub,self.w,value)
  value=self.value();value['scene']['beats'][0]['role']='d'*32
  with self.assertRaisesRegex(ValueError,'removed character'):capture(self.hub,self.w,value)
 def test_recording_plan_is_project_owned_and_remaps_with_voice(self):
  file=self.root/'recording.wav';file.write_bytes(b'fixture');asset=self.store.import_file(self.w,file);value=self.value(visual_only=True);value['scene']['roles'][0]['speech']={'mode':'recording','recording':asset['id']};result=capture(self.hub,self.w,value);snapshot=result['scene_snapshot'];settings={'scene_snapshot':snapshot};remap_settings(settings,{asset['id']:'e'*32},{});self.assertEqual(snapshot['roles'][0]['speech']['recording'],'e'*32)
  snapshot['roles'][0]['speech']={'voice':'f'*32};self.assertIn('f'*32,voice_ids(settings))
 def test_empty_plan_and_duplicate_character_rejected(self):
  value=self.value();value['scene']['roles'].append(dict(value['scene']['roles'][0],id='c'*32))
  with self.assertRaisesRegex(ValueError,'one scene card'):capture(self.hub,self.w,value)
  with self.assertRaisesRegex(ValueError,'Describe'):capture(self.hub,self.w,dict(prompt='',scene={'roles':[],'beats':[]}))
 def test_continuation_uses_captured_character_after_library_removal(self):
  from workspace_store import atomic
  value=self.value();job='f'*32;folder=self.store.folder(self.w)/'jobs'/job;folder.mkdir();atomic(folder/'job.json',{'settings':{'character_snapshot':{'characters':[{'id':self.cid,'name':'Captured Mira'}]}}})
  doc=self.store.get(self.w);doc['characters']={};self.store.save(doc);value['continue_from']=job
  result=capture(self.hub,self.w,value);self.assertEqual(result['scene_snapshot']['roles'][0]['name'],'Captured Mira')

 def test_native_audio_is_rendered_without_visual_only_acknowledgment(self):
  value=self.value();value['audio_mode']='silent';value['scene']['roles'][0]['speech']={'mode':'native','text':'Your coffee is ready.'}
  result=capture(self.hub,self.w,value)
  self.assertEqual(result['audio_mode'],'generated')
  self.assertIn('Mira: Says: Your coffee is ready.',result['prompt'])
  self.assertFalse(result['scene_snapshot']['speech_pending'])
 def test_native_audio_direction_is_optional(self):
  value=self.value();value['scene']['roles'][0]['speech']={'mode':'native'}
  result=capture(self.hub,self.w,value)
  self.assertIn('natural speech',result['prompt'])

if __name__=='__main__':unittest.main()
