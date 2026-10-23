import json,tempfile,time,unittest,wave
from pathlib import Path
import studio
from workspace_store import WorkspaceStore,atomic
from studio_workspaces import StudioHub
class ScopedChainTests(unittest.TestCase):
 def test_moved_media_still_supports_frames_continuation_and_audio_video_joins(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   root=Path(tmp);store=WorkspaceStore(root/'work');atomic(store.root/'migration.json',{'state':'complete'});hub=StudioHub(store.root);destination=store.create('Destination')['id']
   video=root/'fixture.mp4';studio.run_media(['-f','lavfi','-i','color=c=blue:s=16x16:r=24','-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(video)])
   asset=store.import_file('free-work',video);moved=store.transfer('free-work',asset['id'],destination,True);used=hub.use_asset(destination,moved['id']);actor=hub.studio(destination)
   frame=actor.export_frame(used['job']);self.assertTrue((store.folder(destination)/'uploads'/frame['image']).is_file())
   prepared=store.folder(destination)/'jobs/preparation'
   with studio.workspace_scope(actor.directory):command,settings=studio.prepare(dict(prompt='Steady shot',quality='light',seconds=3,size='source',continue_from=used['job']),prepared)
   self.assertEqual(settings['continue_from'],used['job']);self.assertTrue((prepared/'last-frame.png').exists())
   joined=actor.attach({'clips':[dict(kind='job',id=used['job'],chain=False),dict(kind='job',id=used['job'],chain=False)]})
   for _ in range(300):
    if actor.current is None:break
    time.sleep(.02)
   row=json.loads((store.folder(destination)/'jobs'/joined['id']/'job.json').read_text());self.assertEqual(row['status'],'completed');self.assertTrue(row['combined']);self.assertNotIn('imported_asset',row['settings'])
   audio=root/'fixture.wav'
   with wave.open(str(audio),'wb') as output:output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(b'\1\0'*1600)
   asset=store.import_file(destination,audio);used=hub.use_asset(destination,asset['id']);joined=actor.voice.join(dict(clips=[{'id':used['audio'],'chain':True},{'id':used['audio'],'chain':False}],gap_ms=250))
   for _ in range(300):
    if actor.voice.current is None:break
    time.sleep(.02)
   row=json.loads((actor.voice.jobs/joined['id']/'job.json').read_text());self.assertEqual(row['status'],'completed');self.assertAlmostEqual(row['seconds'],.45,places=2)
 def test_moved_narration_copies_project_owned_voice_reference(self):
  import hashlib
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   root=Path(tmp);store=WorkspaceStore(root/'work');atomic(store.root/'migration.json',{'state':'complete'});hub=StudioHub(store.root);source=store.create('Voice source')['id'];destination=store.create('Voice destination')['id'];profile='c'*32;folder=store.folder(source)/'voices/profiles'/profile;folder.mkdir(parents=True)
   with wave.open(str(folder/'reference.wav'),'wb') as output:output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000);output.writeframes(b'\1\0'*2400)
   sha=hashlib.sha256((folder/'reference.wav').read_bytes()).hexdigest();atomic(folder/'profile.json',dict(id=profile,name='Test voice',description='Neutral voice',reference_text='Reference preserved',sha256=sha))
   asset=store.import_file(source,folder/'reference.wav',metadata={'settings':{'action':'read','text':'Reference preserved','profile':profile}});moved=store.transfer(source,asset['id'],destination,True);new_profile=moved['metadata']['settings']['profile'];self.assertNotEqual(new_profile,profile)
   store.update(source,{'deleted':True});store.purge_workspace(source);actor=hub.studio(destination);reference=actor.voice.file('profiles',new_profile,'reference.wav');self.assertEqual(hashlib.sha256(reference.read_bytes()).hexdigest(),sha)
 def test_trashed_chain_is_not_used_for_new_continuations(self):
  import shutil
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   root=Path(tmp);store=WorkspaceStore(root/'work');atomic(store.root/'migration.json',{'state':'complete'});hub=StudioHub(store.root);actor=hub.studio('free-work');folder=store.folder('free-work');parent=folder/'jobs/chain-fixture';parent.mkdir()
   studio.run_media(['-f','lavfi','-i','color=c=blue:s=16x16:r=24','-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(parent/'video.mp4')]);studio.join_clips([parent/'video.mp4']*3,parent/'combined.mp4')
   atomic(parent/'job.json',dict(id='chain-fixture',status='completed',combined=True,settings=dict(prompt='Test chain',quality='high',size='source',seed=0,seconds=1,resolution=[16,16])))
   chain=next(a for a in hub.publish('free-work') if a['metadata'].get('variant')=='chain');hub.mutate_asset('free-work',dict(action='trash',id=chain['id']))
   child=folder/'jobs/continuation-fixture';child.mkdir();shutil.copy2(parent/'video.mp4',child/'video.mp4')
   with studio.workspace_scope(folder):studio.join_continuation(child,'chain-fixture')
   self.assertAlmostEqual(studio.video_seconds(child/'combined.mp4'),2,places=1)
   hub.mutate_asset('free-work',dict(action='restore',id=chain['id']));self.assertTrue(json.loads((parent/'job.json').read_text())['combined'])
 def test_purging_used_asset_removes_compatibility_cache_without_reappearance(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'tmp') as tmp:
   root=Path(tmp);store=WorkspaceStore(root/'work');atomic(store.root/'migration.json',{'state':'complete'});hub=StudioHub(store.root);video=root/'fixture.mp4';studio.run_media(['-f','lavfi','-i','color=c=blue:s=16x16:r=24','-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(video)])
   asset=store.import_file('free-work',video);used=hub.use_asset('free-work',asset['id']);hub.mutate_asset('free-work',dict(action='trash',id=asset['id']));hub.mutate_asset('free-work',dict(action='purge',id=asset['id']))
   self.assertEqual(hub.publish('free-work'),[]);self.assertFalse((store.folder('free-work')/'jobs'/used['job']).exists());self.assertTrue(video.exists())
