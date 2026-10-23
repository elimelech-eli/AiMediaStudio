import json,tempfile,time,unittest,wave
from pathlib import Path
from unittest.mock import Mock,patch
import voice_studio
from voice_text import chunks,speech_text

class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=voice_studio.ROOT/'tmp');self.root=Path(self.temp.name);self.service=voice_studio.VoiceStudio(self.root)
    def tearDown(self):self.temp.cleanup()
    def design(self):return dict(action='design',text='Hello there. Welcome back.',description='Warm relaxed adult voice.',seed=7)
    def profile_fixture(self,root,identifier,name):
        folder=root/identifier;folder.mkdir(parents=True)
        with wave.open(str(folder/'reference.wav'),'wb') as output:output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000);output.writeframes(b'\x01\x00'*2400)
        voice_studio.write(folder/'profile.json',dict(id=identifier,name=name,reference_text='Local reference',description='Neutral'))
        return folder
    def test_saved_voices_are_strictly_workspace_local(self):
        shared=self.root/'shared';legacy='b'*32;self.profile_fixture(shared,legacy,'Legacy shared voice')
        free=voice_studio.VoiceStudio(self.root/'free-work/voices',profiles=shared);a=voice_studio.VoiceStudio(self.root/'a/voices',profiles=shared);b=voice_studio.VoiceStudio(self.root/'b/voices',profiles=shared)
        self.assertEqual(free.state()['profiles'],[]);self.assertEqual(a.state()['profiles'],[])
        self.profile_fixture(free.local_profiles,'f'*32,'Free work voice');self.profile_fixture(a.local_profiles,'a'*32,'Project A voice')
        self.assertEqual([p['name'] for p in free.state()['profiles']],['Free work voice']);self.assertEqual([p['name'] for p in a.state()['profiles']],['Project A voice']);self.assertEqual(b.state()['profiles'],[])
        for actor in (free,a,b):
            with self.assertRaisesRegex(ValueError,'this project'):actor.file('profiles',legacy,'profile.json')
        with self.assertRaisesRegex(ValueError,'this project'):b.file('profiles','a'*32,'reference.wav')
        self.assertTrue((shared/legacy/'reference.wav').exists())
    def test_missing_invalid_and_mismatched_saved_voices_are_not_offered(self):
        good=self.profile_fixture(self.service.local_profiles,'a'*32,'Good');missing=self.profile_fixture(self.service.local_profiles,'b'*32,'Missing');(missing/'reference.wav').unlink()
        invalid=self.profile_fixture(self.service.local_profiles,'c'*32,'Invalid audio');(invalid/'reference.wav').write_bytes(b'not a wav')
        mismatch=self.profile_fixture(self.service.local_profiles,'d'*32,'Wrong ID');voice_studio.write(mismatch/'profile.json',dict(id='e'*32,name='Wrong ID'))
        bad_json=self.profile_fixture(self.service.local_profiles,'e'*32,'Bad metadata');voice_studio.write(bad_json/'profile.json',[])
        self.assertEqual([p['name'] for p in self.service.state()['profiles']],['Good'])
        (good/'reference.wav').unlink();self.assertEqual(self.service.state()['profiles'],[])
        with self.assertRaisesRegex(ValueError,'unavailable'):self.service.file('profiles','a'*32,'profile.json')
    def test_validation_busy_and_unsafe_profile_identifiers(self):
        with self.assertRaises(ValueError):self.service.start(dict(self.design(),text='👩🏽‍💻'))
        with self.assertRaises(ValueError):self.service.file('profiles','../outside','profile.json')
        self.service.other_busy=lambda:True
        with self.assertRaises(ValueError):self.service.start(self.design())
        self.service.other_busy=lambda:False
        with patch.object(voice_studio.subprocess,'run',return_value=Mock(stdout='8192, 7000, 90')):
            with self.assertRaisesRegex(ValueError,'GPU is busy'):self.service.start(self.design())
    def test_design_save_profile_and_reuse_for_narration(self):
        def launch(command,**kwargs):
            folder=Path(command[-1]);
            with wave.open(str(folder/'audio.wav'),'wb') as output:output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000);output.writeframes(b'\x10\x00'*24000)
            (folder/'result.json').write_text(json.dumps(dict(seconds=1,sample_rate=24000)))
            return Mock(poll=Mock(return_value=0),returncode=0)
        with patch.object(voice_studio.subprocess,'run',return_value=Mock(stdout='8192, 1000, 0')),patch.object(voice_studio.subprocess,'Popen',side_effect=launch):
            row=self.service.start(self.design())
            for _ in range(100):
                if not self.service.current:break
                time.sleep(.01)
            self.assertEqual(self.service.state()['jobs'][0]['status'],'completed')
            profile=self.service.save_profile(row['id'],'Studio voice')
            self.assertEqual(profile['reference_text'],self.design()['text']);self.assertTrue(self.service.file('profiles',profile['id'],'reference.wav').is_file())
            read=self.service.start(dict(action='read',profile=profile['id'],text='This is another prepared sentence.'))
            for _ in range(100):
                if not self.service.current:break
                time.sleep(.01)
            self.assertEqual(read['settings']['profile'],profile['id'])
            self.assertEqual(len(self.service.state()['profiles']),1)
            continued=self.service.start(dict(action='read',continue_from=read['id'],text='The next sentence.',gap_ms=250))
            for _ in range(100):
                if not self.service.current:break
                time.sleep(.01)
            saved=json.loads((self.service.jobs/continued['id']/'job.json').read_text());self.assertTrue(saved['combined']);self.assertEqual(saved['combined_seconds'],2.25)
            third=self.service.start(dict(action='read',continue_from=continued['id'],text='One more sentence.',gap_ms=250))
            for _ in range(100):
                if not self.service.current:break
                time.sleep(.01)
            saved=json.loads((self.service.jobs/third['id']/'job.json').read_text());self.assertEqual(saved['combined_seconds'],3.5)
            self.assertEqual(saved['combined_text'].count('The next sentence.'),1)
    def test_chunks_preserve_words_and_strip_whole_emoji(self):
        text=('A short sentence. Another, longer sentence with clear words! '*100).strip()
        result=chunks(text);self.assertTrue(all(len(part)<=500 for part in result));self.assertEqual(' '.join(result).split(),text.split())
        self.assertEqual(speech_text('Hi 👩🏽‍💻 🇺🇸 1️⃣ friend').split(),['Hi','friend'])
    def test_cancel_targets_only_the_owned_worker_and_persists_intent(self):
        key='a'*32;folder=self.service.jobs/key;folder.mkdir();voice_studio.write(folder/'job.json',dict(status='running'))
        self.service.current=key;self.service.process=Mock(pid=98765)
        with patch.object(voice_studio.subprocess,'run') as run:
            self.service.cancel();self.assertEqual(run.call_args.args[0],['taskkill.exe','/PID','98765','/T','/F'])
        self.assertTrue(json.loads((folder/'job.json').read_text())['cancelled'])
    def test_manual_audio_chain_preserves_sample_order_and_full_parent_chain(self):
        import struct
        for key,sample in [('a'*32,1000),('b'*32,-1000),('c'*32,2000)]:
            folder=self.service.jobs/key;folder.mkdir()
            with wave.open(str(folder/'audio.wav'),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(struct.pack('<h',sample)*800)
            voice_studio.write(folder/'job.json',dict(id=key,status='completed',settings=dict(action='read',text=key[0],profile='1'*32)))
        first=self.service.join(dict(clips=[dict(id='a'*32,chain=True),dict(id='b'*32)],gap_ms=0))
        for _ in range(100):
            if not self.service.current:break
            time.sleep(.01)
        second=self.service.join(dict(clips=[dict(id=first['id'],chain=True),dict(id='c'*32)],gap_ms=100))
        for _ in range(100):
            if not self.service.current:break
            time.sleep(.01)
        with wave.open(str(self.service.file('jobs',second['id'],'combined.wav')),'rb') as audio:
            data=audio.readframes(audio.getnframes());samples=struct.unpack('<'+'h'*(len(data)//2),data)
        self.assertEqual(samples[:800],(1000,)*800);self.assertEqual(samples[800:1600],(-1000,)*800)
        self.assertEqual(samples[1600:2400],(0,)*800);self.assertEqual(samples[2400:],(2000,)*800)
        row=json.loads(self.service.file('jobs',second['id'],'job.json').read_text());self.assertEqual(row['settings']['text'],'a\n\nb\n\nc');self.assertEqual(row['settings']['profile'],'1'*32)
        with self.assertRaises(ValueError):self.service.join(dict(clips=[dict(id='../outside'),dict(id='a'*32)]))

if __name__=='__main__':unittest.main()
