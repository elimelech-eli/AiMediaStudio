import copy,json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from workspace_store import WorkspaceStore,atomic
from workspace_portable import PortableProjects
from studio_characters import action,enrich,validate,remap_settings,asset_ids

class CharactersTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp');self.root=Path(self.temp.name);self.store=WorkspaceStore(self.root/'work');self.w=self.store.create('Characters')['id'];self.other=self.store.create('Other')['id']
  image=self.root/'face.png';image.write_bytes(b'local identity fixture');self.face=self.store.import_file(self.w,image)
  self.hub=SimpleNamespace(store=self.store,gate=threading.RLock(),queue=SimpleNamespace(protected_owners=lambda:set()),use_asset=lambda w,a:{'image':a+'.png'})
  self.base=dict(name='Alice',aliases=['Ally'],appearance='Red hair, freckles.',body_language='Confident posture.',behavior='A long behavior file. '*300,references=[dict(asset=self.face['id'],role='face',approved=True)],outfits=[],state={})
  self.character=action(self.hub,self.w,dict(action='save',character=self.base))
 def tearDown(self):self.temp.cleanup()
 def capture(self,engine='image',value=None):
  value=value or {'prompt':'Ally gets coffee'};return enrich(self.hub,self.w,engine,copy.deepcopy(value),value)
 def test_alias_resolution_strict_and_long_behavior_separate_from_visual_prompt(self):
  result=self.capture();self.assertIn(self.face['id']+'.png',result['images']);self.assertLess(len(result['prompt']),2000);self.assertEqual(result['character_snapshot']['characters'][0]['behavior'],self.base['behavior'].strip())
  with self.assertRaisesRegex(ValueError,'requires identity'):self.capture(value=dict(prompt='Alice',use_character_references=False))
  result=self.capture(value=dict(prompt='Alice',character_ids=[]));self.assertNotIn('character_snapshot',result)
 def test_versioned_continuation_retains_previous_identity_and_state(self):
  before=self.capture('video');id='a'*32;folder=self.store.folder(self.w)/'jobs'/id;folder.mkdir();atomic(folder/'job.json',{'settings':before})
  changed=dict(self.base,appearance='Completely different identity');action(self.hub,self.w,dict(action='save',id=self.character['id'],revision=1,character=changed))
  continued=self.capture('video',dict(prompt='Her face returns into frame',continue_from=id))
  self.assertEqual(continued['character_snapshot']['characters'][0]['appearance'],self.base['appearance']);self.assertTrue(continued['character_guidance'])
  latest=self.capture('video',dict(prompt='Continue',continue_from=id,refresh_characters=True));self.assertEqual(latest['character_snapshot']['characters'][0]['revision'],2)
 def test_project_isolation_missing_face_and_asset_retention(self):
  with self.assertRaisesRegex(ValueError,'not available'):enrich(self.hub,self.other,'image',{'prompt':'x'},{'prompt':'x','character_ids':[self.character['id']]})
  with self.assertRaisesRegex(ValueError,'retain'):self.store.trash(self.w,self.face['id'])
  with self.assertRaisesRegex(ValueError,'matching assets'):validate(dict(self.base,references=[dict(asset=self.face['id'],role='face')]),self.store.get(self.other))
  action(self.hub,self.w,dict(action='save',id=self.character['id'],revision=1,character=dict(self.base,references=[])))
  with self.assertRaisesRegex(ValueError,'reference image'):self.capture()
 def test_stale_edit_and_alias_collision(self):
  with self.assertRaisesRegex(ValueError,'changed'):action(self.hub,self.w,dict(action='save',id=self.character['id'],revision=0,character=self.base))
  with self.assertRaisesRegex(ValueError,'already uses'):action(self.hub,self.w,dict(action='save',character=dict(self.base,name='Else',aliases=['Ally'])))
 def test_branch_export_import_character_and_captured_job_independence(self):
  captured=self.capture();generated=self.root/'generated.png';generated.write_bytes(b'output');asset=self.store.import_file(self.w,generated,metadata={'settings':captured,'required':[self.face['id']]})
  portable=PortableProjects(self.store,self.root/'shared');branch=portable.branch(self.w,'Independent');row=next(iter(branch['characters'].values()));self.assertNotEqual(asset_ids(row)[0],self.face['id']);self.assertIn(asset_ids(row)[0],branch['assets'])
  recipe=next(a for a in branch['assets'].values() if a['metadata'].get('settings'))['metadata']['settings'];self.assertEqual(recipe['character_snapshot']['characters'][0]['references'][0]['asset'],asset_ids(row)[0])
  exported=portable.export(self.w);imported=portable.import_zip(portable.exports/exported['file']);self.assertEqual(len(imported['characters']),1);self.assertEqual(next(iter(imported['characters'].values()))['references'][0]['description'],'Face and facial identity')
 def test_voice_selection_preserves_exact_script_and_remaps(self):
  doc=self.store.get(self.w);doc['characters'][self.character['id']]['voice']='b'*32;self.store.save(doc)
  result=self.capture('voice',{'action':'read','text':'Alice says hello.','profile':'c'*32});self.assertEqual(result['profile'],'b'*32);self.assertEqual(result['text'],'Alice says hello.')
  remap_settings(result,{self.face['id']:'d'*32},{'b'*32:'e'*32});row=result['character_snapshot']['characters'][0];self.assertEqual(row['voice'],'e'*32);self.assertIn('d'*32,row['asset_fingerprints'])
 def test_outfits_and_image_to_video_handoff_keep_captured_version(self):
  outfit=dict(id='c'*32,name='Jacket',description='Blue jacket',references=[self.face['id']])
  row=action(self.hub,self.w,dict(action='save',id=self.character['id'],revision=1,character=dict(self.base,outfits=[outfit],state={'outfit':outfit['id']})))
  result=self.capture();generated=self.root/'output.png';generated.write_bytes(b'image')
  source=self.store.import_file(self.w,generated,metadata={'settings':result,'required':[self.face['id']]})
  action(self.hub,self.w,dict(action='save',id=row['id'],revision=2,character=self.base))
  video=self.capture('video',dict(prompt='Walk forward',character_source_asset=source['id']))
  self.assertEqual(video['character_snapshot']['characters'][0]['state']['outfit'],outfit['id']);self.assertEqual(len(video['character_guidance']),2)
 def test_proposal_revision_guard_and_duplicate_names(self):
  with self.assertRaisesRegex(ValueError,'since this proposal'):self.capture(value=dict(prompt='Alice',character_revisions={self.character['id']:0}))
  first=action(self.hub,self.w,dict(action='duplicate',id=self.character['id']));second=action(self.hub,self.w,dict(action='duplicate',id=self.character['id']));self.assertNotEqual(first['name'],second['name'])
 def test_reference_budget_rejects_before_queue(self):
  with self.assertRaisesRegex(ValueError,'four images'):self.capture(value=dict(prompt='Alice',images=['a.png','b.png','c.png','d.png']))
 def test_copying_output_remaps_captured_identity_dependencies(self):
  settings=self.capture();file=self.root/'result.png';file.write_bytes(b'result');asset=self.store.import_file(self.w,file,metadata={'settings':settings,'required':[self.face['id']]})
  copied=self.store.transfer(self.w,asset['id'],self.other);row=copied['metadata']['settings']['character_snapshot']['characters'][0]
  self.assertNotEqual(row['references'][0]['asset'],self.face['id']);self.assertIn(row['references'][0]['asset'],self.store.get(self.other)['assets']);self.assertIn(row['references'][0]['asset'],row['asset_fingerprints'])
 def test_face_and_body_are_both_used_for_identity_guidance(self):
  body=self.root/'body.png';body.write_bytes(b'body reference');asset=self.store.import_file(self.w,body)
  references=[*self.base['references'],dict(asset=asset['id'],role='body',approved=True)]
  action(self.hub,self.w,dict(action='save',id=self.character['id'],revision=1,character=dict(self.base,references=references)))
  result=self.capture('video');self.assertEqual([r['description'] for r in result['character_guidance']],['Face and facial identity','Body and proportions'])
 def add_images(self,count):
  image=self.root/'extra.png';image.write_bytes(b'reference')
  return [dict(asset=self.store.import_file(self.w,image)['id'],description=('Detail '+str(i) if i else '')) for i in range(count)]
 def test_ten_freely_described_images_and_limit(self):
  references=self.add_images(11)
  normalized=validate(dict(self.base,references=references[:10]),self.store.get(self.w));self.assertEqual(len(normalized['references']),10);self.assertEqual(normalized['references'][0]['description'],'');self.assertEqual(normalized['references'][1]['description'],'Detail 1')
  with self.assertRaisesRegex(ValueError,'10 reference images'):validate(dict(self.base,references=references),self.store.get(self.w))
 def test_automatic_budget_and_explicit_reference_choice_reach_engine(self):
  references=self.add_images(10);action(self.hub,self.w,dict(action='save',id=self.character['id'],revision=1,character=dict(self.base,references=references)))
  result=self.capture('video',dict(prompt='Alice waves',image='start.png'));self.assertEqual(len(result['character_guidance']),3)
  selected=[references[8]['asset'],references[9]['asset']];explicit=self.capture('video',dict(prompt='Alice waves',character_reference_ids={self.character['id']:selected}))
  self.assertEqual([r['asset'] for r in explicit['character_guidance']],selected);self.assertEqual(explicit['character_guidance'][0]['description'],'Detail 8')
  with self.assertRaisesRegex(ValueError,'four images'):self.capture('video',dict(prompt='Alice',character_reference_ids={self.character['id']:[r['asset'] for r in references[:5]]}))
 def test_untagged_image_is_valid_strict_reference(self):
  refs=self.add_images(1);action(self.hub,self.w,dict(action='save',id=self.character['id'],revision=1,character=dict(self.base,references=refs)))
  result=self.capture();self.assertIn('General character reference',result['prompt']);self.assertEqual(len(result['images']),1)
 def test_continuation_preserves_chosen_subset_and_descriptions(self):
  refs=self.add_images(5);action(self.hub,self.w,dict(action='save',id=self.character['id'],revision=1,character=dict(self.base,references=refs)))
  selected=[refs[3]['asset']];before=self.capture('video',dict(prompt='Alice',character_reference_ids={self.character['id']:selected}));id='f'*32;folder=self.store.folder(self.w)/'jobs'/id;folder.mkdir();atomic(folder/'job.json',{'settings':before})
  after=self.capture('video',dict(prompt='Continue',continue_from=id));self.assertEqual(after['character_snapshot']['characters'][0]['active_references'],selected);self.assertEqual(after['character_guidance'][0]['description'],'Detail 3')
 def test_auto_handoff_rebalances_capacity_and_explicit_choice_stays_pinned(self):
  refs=self.add_images(10);action(self.hub,self.w,dict(action='save',id=self.character['id'],revision=1,character=dict(self.base,references=refs)))
  before=self.capture();image=self.root/'handoff.png';image.write_bytes(b'output');source=self.store.import_file(self.w,image,metadata={'settings':before})
  after=self.capture('video',dict(prompt='Continue',image='start.png',character_source_asset=source['id']));self.assertEqual(len(after['character_guidance']),3)
 def test_legacy_same_image_roles_merge_into_free_text(self):
  refs=[dict(asset=self.face['id'],role='face'),dict(asset=self.face['id'],role='body')]
  result=validate(dict(self.base,references=refs),self.store.get(self.w));self.assertEqual(len(result['references']),1);self.assertIn('Face',result['references'][0]['description']);self.assertIn('Body',result['references'][0]['description'])
if __name__=='__main__':unittest.main()
