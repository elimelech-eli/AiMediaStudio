import tempfile,unittest,wave
from pathlib import Path
from voice_studio import VoiceStudio,write

def profile(root,id='a'*32,name='Test voice'):
 folder=Path(root)/'profiles'/id;folder.mkdir(parents=True)
 with wave.open(str(folder/'reference.wav'),'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\0\0'*240)
 write(folder/'profile.json',dict(id=id,name=name,description='Test',reference_text='Hello',sha256='test'))
 return id

class SavedVoiceTests(unittest.TestCase):
 def test_only_real_profiles_are_listed_and_can_be_renamed_duplicated_trashed(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);voice=VoiceStudio(root);id=profile(root);(root/'profiles'/'invalid').mkdir()
   self.assertEqual(len(voice.profile_listing()),1);voice.profile_action(dict(action='rename',id=id,name='Renamed'),{});self.assertEqual(voice.profile_listing()[0]['name'],'Renamed')
   copy=voice.profile_action(dict(action='duplicate',id=id),{});self.assertNotEqual(copy['id'],id);voice.profile_action(dict(action='trash',id=id),{});self.assertEqual(len(voice.profile_listing()),1);self.assertEqual(len(voice.profile_listing(True)),2);voice.profile_action(dict(action='restore',id=id),{});self.assertEqual(len(voice.profile_listing()),2)
 def test_voice_purge_preserves_recording_and_snapshot_dependencies(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);voice=VoiceStudio(root);id=profile(root);voice.profile_action(dict(action='trash',id=id),{})
   with self.assertRaisesRegex(ValueError,'snapshot'):voice.profile_action(dict(action='purge',id=id),dict(snapshots={'s':{'voice_profiles':[id]}}))
   voice.profile_action(dict(action='purge',id=id),dict(assets={'recording':{'metadata':{'settings':{'profile':id}}}}));self.assertFalse((root/'profiles'/id).exists())
