import json, tempfile, unittest, threading, http.client, sys, time
from pathlib import Path
from unittest.mock import patch, Mock
import studio

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=studio.ROOT/'tmp')
        self.root=Path(self.temp.name)
        self.patches=[patch.object(studio,'UPLOADS',self.root/'uploads'),patch.object(studio,'JOBS',self.root/'jobs'),patch.object(studio,'IMAGE_JOBS',self.root/'image-jobs'),patch.object(studio,'VOICE_DATA',self.root/'voices')]
        for p in self.patches:p.start()
        studio.UPLOADS.mkdir();studio.JOBS.mkdir()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.temp.cleanup()
    def options(self,**extra):
        return dict(prompt='She smiles and waves.',quality='high',size='source',seconds=8,**extra)
    def test_keyframe_and_reference_layouts(self):
        command,settings=studio.prepare(self.options(image='lexi'),studio.JOBS/'image')
        media=json.loads((studio.JOBS/'image/media.json').read_text())
        self.assertEqual(settings['task'],'i2va');self.assertIn('first',media)
        self.assertEqual(settings['frames'],192);self.assertIn('--no-two-pass',command)
        (studio.UPLOADS/'motion.mp4').write_bytes(b'test')
        command,settings=studio.prepare(self.options(image='lexi',video='motion.mp4'),studio.JOBS/'reference')
        media=json.loads((studio.JOBS/'reference/media.json').read_text())
        self.assertEqual(settings['task'],'ref2va');self.assertNotIn('first',media)
        self.assertEqual([r['kind'] for r in media['references']],['image','video'])
    def test_project_character_guidance_preserves_explicit_identity_reference(self):
        for name in ('start.png','face.png','extra.png'):(studio.UPLOADS/name).write_bytes(b'local test reference')
        command,settings=studio.prepare(self.options(image='start.png',identity_image='extra.png',identity_mode=True,character_guidance=[dict(image='face.png',character='Alice',role='face')],character_snapshot={'version':1}),studio.JOBS/'characters')
        media=json.loads((studio.JOBS/'characters/media.json').read_text())
        self.assertEqual(settings['task'],'ref2va');self.assertEqual(len(media['references']),3);self.assertIn('Alice',settings['prompt']);self.assertEqual(settings['character_snapshot']['version'],1)
    def test_requested_action_priority_and_audio_settings(self):
        _,settings=studio.prepare(dict(self.options(),user_prompt='Alice makes coffee',audio_mode='silent'),studio.JOBS/'action')
        prompt=(studio.JOBS/'action/prompt.txt').read_text(encoding='utf-8')
        self.assertIn('[Shot 1] Primary scene/action: Alice makes coffee',prompt);self.assertIn('must not replace the requested action',prompt);self.assertEqual(settings['audio_mode'],'silent')
        with self.assertRaisesRegex(ValueError,'Silent'):studio.prepare(dict(self.options(),audio_mode='invalid'),studio.JOBS/'invalid-audio')
    def test_silent_output_removes_audio_without_reencoding_video(self):
        import subprocess
        source=self.root/'sound.mp4'
        studio.run_media(['-y','-f','lavfi','-i','color=blue:s=32x32:r=12:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-threads','2','-c:a','aac','-shortest',str(source)])
        def video_hash():
            return subprocess.run([str(studio.FFMPEG),'-v','error','-i',str(source),'-map','0:v:0','-c','copy','-f','hash','-hash','sha256','-'],capture_output=True,check=True).stdout
        before=video_hash();studio.silent_video_output(source);self.assertEqual(before,video_hash())
        probe=subprocess.run([str(studio.FFMPEG),'-hide_banner','-i',str(source)],capture_output=True).stderr.decode()
        self.assertNotIn('Audio:',probe);self.assertIn('Video:',probe)
    def test_silent_finalization_failure_is_not_published_as_completed(self):
        app=studio.Studio();folder=studio.JOBS/'silent-failure';folder.mkdir();(folder/'video.mp4').write_bytes(b'original worker output')
        row=dict(id=folder.name,status='running',started=studio.time.time(),settings={'audio_mode':'silent'});studio.write_json(folder/'job.json',row)
        with patch.object(studio,'silent_video_output',side_effect=ValueError('remux failed')):app.finish(folder,row,Mock(wait=Mock(return_value=0)))
        saved=json.loads((folder/'job.json').read_text());self.assertEqual(saved['status'],'failed');self.assertIn('silent output',saved['message']);self.assertEqual((folder/'video.mp4').read_bytes(),b'original worker output')
    def test_reject_traversal_and_bad_settings(self):
        with self.assertRaises(ValueError):studio.asset('../Lexi.png','image')
        with self.assertRaises(ValueError):studio.prepare(dict(prompt='x',seconds=999),studio.JOBS/'bad')
        with self.assertRaises(ValueError):studio.prepare(dict(prompt=''),studio.JOBS/'empty')
    def test_continuation_validation_and_source_framing(self):
        with self.assertRaises(ValueError):studio.completed_job('../outside')
        source=studio.JOBS/'source';source.mkdir();(source/'video.mp4').write_bytes(b'test')
        studio.write_json(source/'job.json',dict(status='running',settings=dict(size='portrait')))
        with self.assertRaises(ValueError):studio.prepare(self.options(continue_from='source'),studio.JOBS/'blocked')
        studio.write_json(source/'job.json',dict(status='completed',settings=dict(size='portrait')))
        with self.assertRaises(ValueError):studio.prepare(self.options(continue_from='source',image='lexi'),studio.JOBS/'mixed')
        with patch.object(studio,'last_frame',side_effect=lambda src,dst:dst.write_bytes(b'frame')):
            command,settings=studio.prepare(self.options(continue_from='source'),studio.JOBS/'next')
        self.assertEqual(settings['resolution'],[512,768]);self.assertEqual(settings['task'],'i2va')
        self.assertEqual(settings['continue_from'],'source')
        self.assertEqual(json.loads((studio.JOBS/'next/media.json').read_text())['first'],str(studio.JOBS/'next/last-frame.png'))
    def test_consistency_profile_inherits_and_never_mixes_unsupported_layouts(self):
        from freevideo_engine.media_request import read
        (studio.UPLOADS/'identity.png').write_bytes(b'identity')
        source=studio.JOBS/'source';source.mkdir();(source/'video.mp4').write_bytes(b'video')
        studio.write_json(source/'job.json',dict(status='completed',settings=dict(size='source',appearance='Defined muscles, freckles, fixed proportions.',identity_image='identity.png',identity_mode=False)))
        with patch.object(studio,'last_frame',side_effect=lambda src,dst:dst.write_bytes(b'frame')):
            _,settings=studio.prepare(self.options(continue_from='source'),studio.JOBS/'anchor')
            self.assertEqual(settings['appearance'],'Defined muscles, freckles, fixed proportions.')
            anchor=read(studio.JOBS/'anchor/media.json');self.assertIn('first',anchor);self.assertFalse(anchor['references'])
            _,settings=studio.prepare(self.options(continue_from='source',identity_mode=True),studio.JOBS/'guided')
        guided=read(studio.JOBS/'guided/media.json');self.assertNotIn('first',guided);self.assertEqual(len(guided['references']),2)
        self.assertEqual(settings['task'],'ref2va')
        prompt=(studio.JOBS/'guided/prompt.txt').read_text()
        self.assertTrue(prompt.startswith('integrated_multimodal_description:'))
        self.assertIn('Defined muscles',prompt)

    def test_manual_join_mixed_geometry_and_audio_then_export_frame(self):
        import subprocess
        first=studio.JOBS/'first';first.mkdir();second=studio.JOBS/'second';second.mkdir()
        studio.run_media(['-y','-f','lavfi','-i','color=red:s=32x32:r=24:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-threads','2','-c:a','aac','-shortest',str(first/'video.mp4')])
        studio.run_media(['-y','-f','lavfi','-i','color=blue:s=64x48:r=12:d=1','-c:v','libx264','-threads','2',str(second/'video.mp4')])
        for folder in (first,second):studio.write_json(folder/'job.json',dict(status='completed',settings=dict(size='source',appearance='Keep identity.')))
        app=studio.Studio()
        with self.assertRaises(ValueError):app.attach({'clips':[{'kind':'job','id':'../outside'},{'kind':'job','id':'second'}]})
        row=app.attach({'clips':[{'kind':'job','id':'first','chain':True},{'kind':'job','id':'second'}]})
        for _ in range(500):
            if not app.current:break
            time.sleep(.02)
        saved=json.loads((studio.JOBS/row['id']/'job.json').read_text());self.assertEqual(saved['status'],'completed',saved.get('message'))
        self.assertEqual(saved['settings']['resolution'],[32,32]);self.assertAlmostEqual(saved['settings']['seconds'],2,delta=.2)
        self.assertEqual(saved['settings']['appearance'],'Keep identity.')
        output=studio.JOBS/row['id']/'video.mp4'
        audio=subprocess.run([str(studio.FFMPEG),'-hide_banner','-i',str(output),'-vn','-af','volumedetect','-f','null','-'],capture_output=True)
        self.assertRegex(audio.stderr.decode(),r'max_volume: -?\d+(?:\.\d+)? dB')
        frame=app.export_frame(row['id'])
        from PIL import Image
        with Image.open(studio.asset(frame['image'],'image')) as image:
            red,green,blue=image.convert('RGB').getpixel((16,16));self.assertGreater(blue,200);self.assertLess(red,20)

    def test_real_final_frame_and_chained_join_without_generation(self):
        from PIL import Image
        source=studio.JOBS/'source';source.mkdir()
        studio.run_media(['-y','-f','lavfi','-i','color=red:s=32x32:r=4:d=0.5',
                          '-f','lavfi','-i','color=blue:s=32x32:r=4:d=0.5',
                          '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
                          '-map','[v]','-c:v','libx264','-threads','2',str(source/'video.mp4')])
        studio.write_json(source/'job.json',dict(status='completed'))
        studio.last_frame(source/'video.mp4',source/'last.png')
        with Image.open(source/'last.png') as im:
            red,green,blue=im.convert('RGB').getpixel((16,16))
        self.assertGreater(blue,200);self.assertLess(red,20)
        import shutil, subprocess
        following=studio.JOBS/'next';following.mkdir();shutil.copyfile(source/'video.mp4',following/'video.mp4')
        studio.join_continuation(following,'source')
        studio.write_json(following/'job.json',dict(status='completed'))
        third=studio.JOBS/'third';third.mkdir();shutil.copyfile(source/'video.mp4',third/'video.mp4')
        studio.join_continuation(third,'next')
        result=subprocess.run([str(studio.FFMPEG),'-v','error','-i',str(third/'combined.mp4'),
                               '-map','0:v:0','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True)
        self.assertEqual(len(result.stdout)//(32*32*3),12)
    def test_single_job_and_cancel_only_owned_pid(self):
        app=studio.Studio();app.current='owned';app.process=Mock(pid=12345)
        app.process.poll.return_value=None
        folder=studio.JOBS/'owned';folder.mkdir()
        studio.write_json(folder/'job.json',dict(status='running'))
        with self.assertRaises(ValueError):app.start(self.options())
        with patch.object(studio.subprocess,'run',return_value=Mock(returncode=0)) as run:
            app.cancel()
            self.assertEqual(run.call_args.args[0],['taskkill.exe','/PID','12345','/T','/F'])
        self.assertEqual(json.loads((folder/'job.json').read_text())['status'],'cancelling')
    def test_finish_cancel_and_failure(self):
        app=studio.Studio();folder=studio.JOBS/'job';folder.mkdir()
        row=dict(id='job',started=studio.time.time(),status='cancelling')
        studio.write_json(folder/'job.json',row)
        app.finish(folder,row,Mock(wait=Mock(return_value=1)))
        self.assertEqual(json.loads((folder/'job.json').read_text())['status'],'cancelled')
        row.update(status='running');studio.write_json(folder/'job.json',row)
        (folder/'error.log').write_text('Useful engine error')
        app.finish(folder,row,Mock(wait=Mock(return_value=1)))
        self.assertEqual(json.loads((folder/'job.json').read_text())['message'],'Useful engine error')
    def test_progress_reports_engine_stage(self):
        folder=studio.JOBS/'progress';folder.mkdir()
        (folder/'video.engine.log').write_text(json.dumps(dict(event='sampling_progress',completed_steps=8,total=16))+'\n')
        self.assertEqual(studio.phase(folder),('Sampling: 8 / 16 steps',50))
    def test_image_result_is_reusable_video_reference_and_blocks_parallel_work(self):
        app=studio.Studio();app.image_info=Mock(return_value={'ready':True})
        produced=studio.UPLOADS/'freevideo-image';produced.mkdir();(produced/'result.png').write_bytes(b'local image')
        service=Mock();service.start.return_value={'job':'private-key'}
        service.status.return_value={'phase':'complete','file':'freevideo-image/result.png','seconds':1}
        app.image_service=service
        with self.assertRaises(ValueError):app.start_image(dict(prompt='x',images=['../outside.png']))
        app.current='video-job'
        with self.assertRaises(ValueError):app.start_image(dict(prompt='x',images=[]))
        app.current=None
        row=app.start_image(dict(prompt='A green teapot',images=[],width=768,height=768,seed=None))
        for _ in range(100):
            if not app.image_current:break
            time.sleep(.01)
        saved=json.loads((studio.IMAGE_JOBS/row['id']/'job.json').read_text())
        self.assertEqual(saved['status'],'completed');self.assertEqual(studio.asset(saved['image'],'image').read_bytes(),b'local image')
        _,settings=studio.prepare(self.options(image=saved['image']),studio.JOBS/'from-image')
        self.assertEqual(settings['task'],'i2va')
        app.image_current='image-job'
        with self.assertRaises(ValueError):app.start(self.options())
    def test_worker_launch_and_completion_without_model_load(self):
        app=studio.Studio()
        original=studio.prepare
        def fake_prepare(options,folder):
            _,settings=original(options,folder)
            return [sys.executable,'-c','from pathlib import Path; Path('+repr(str(folder/'video.mp4'))+').write_bytes(b"test")'],settings
        with patch.object(studio,'prepare',side_effect=fake_prepare):
            row=app.start(self.options())
            for _ in range(100):
                if not app.current:break
                time.sleep(.02)
        self.assertIsNone(app.current)
        self.assertEqual(json.loads((studio.JOBS/row['id']/'job.json').read_text())['status'],'completed')
    def test_http_upload_auth_and_video_ranges(self):
        server=studio.ThreadingHTTPServer(('127.0.0.1',0),studio.Handler)
        server.studio=studio.Studio()
        port=server.server_address[1]
        with patch.object(studio,'PORT',port):
            threading.Thread(target=server.serve_forever,daemon=True).start()
            conn=http.client.HTTPConnection('127.0.0.1',port)
            conn.request('POST','/api/cancel',body='{}')
            response=conn.getresponse();self.assertEqual(response.status,403);response.read()
            headers={'X-Studio-Token':studio.TOKEN,'Origin':f'http://127.0.0.1:{port}','X-Media-Kind':'image','X-File-Extension':'.png'}
            conn.request('POST','/api/upload',body=b'local-image',headers=headers)
            response=conn.getresponse();self.assertEqual(response.status,200)
            identifier=json.loads(response.read())['id']
            self.assertEqual((studio.UPLOADS/identifier).read_bytes(),b'local-image')
            folder=studio.JOBS/'saved';folder.mkdir();(folder/'video.mp4').write_bytes(b'0123456789')
            conn.request('GET','/video/saved',headers={'Range':'bytes=2-5'})
            response=conn.getresponse();self.assertEqual(response.status,206);self.assertEqual(response.read(),b'2345')
            (folder/'combined.mp4').write_bytes(b'joined-video')
            conn.request('GET','/combined/saved',headers={'Range':'bytes=0-5'})
            response=conn.getresponse();self.assertEqual(response.status,206);self.assertEqual(response.read(),b'joined')
            conn.request('GET','/image/'+identifier)
            response=conn.getresponse();self.assertEqual(response.status,200);self.assertEqual(response.read(),b'local-image')
            voice_folder=server.studio.voice.jobs/('a'*32);voice_folder.mkdir();(voice_folder/'combined.wav').write_bytes(b'RIFFjoined-wave')
            conn.request('GET','/audio-chain/'+('a'*32),headers={'Range':'bytes=4-9'})
            response=conn.getresponse();self.assertEqual(response.status,206);self.assertEqual(response.read(),b'joined')
            conn.close();server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
