"""One offline GPU job. Design a voice sample or narrate with a saved sample."""
import json,sys,re,time,hashlib,gc,subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
from voice_text import chunks,speech_text

folder=Path(sys.argv[1]).resolve();request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
root=Path(__file__).resolve().parent.parent/'media-runtime/voice';started=time.time()
sys.path.insert(0,str(Path(__file__).resolve().parent/'FreeVideo'))
from freevideo_engine.studio_checkpoint import directory,boundary
checkpoint=directory(str(folder/'checkpoint'))
boundary(checkpoint,'voice-inputs')
design=request['action']=='design'
print(json.dumps(dict(phase='Loading voice design model' if design else 'Loading narration model')),flush=True)
model_path=Path((request.get('model_spec') or {}).get('path') or root/'models'/('VoiceDesign' if design else 'Base'))
from sound_script import parse_script,sound_cues,mix_plan
plan=request.get('sound_plan') or parse_script(request['text'])
needs_speech=(design and not (folder/'design-checkpoint.wav').is_file()) or (not design and any(p['kind']=='speech' and speech_text(p['text']).strip() for p in plan))
if needs_speech:
    import torch
    from qwen_tts import Qwen3TTSModel
    torch.set_num_threads(4);torch.manual_seed(request['seed'])
model=Qwen3TTSModel.from_pretrained(str(model_path),device_map='cuda:0',dtype=torch.bfloat16,attn_implementation='sdpa',local_files_only=True) if needs_speech else None
parts=[];sample_rate=None
if design:
    print(json.dumps(dict(phase='Generating voice sample')),flush=True)
    if (folder/'design-checkpoint.wav').is_file():wave,sample_rate=sf.read(folder/'design-checkpoint.wav',dtype='float32');parts.append(wave)
    else:
        with torch.inference_mode():wavs,sample_rate=model.generate_voice_design(text=speech_text(request['text']),language='English',instruct=request['description'],max_new_tokens=1800)
        parts.append(np.asarray(wavs[0],dtype=np.float32))
        sf.write(folder/'design-checkpoint.wav',parts[0],sample_rate,subtype='PCM_16')
    boundary(checkpoint,'voice-design')
else:
    if needs_speech:
        profile=request['profile_data'];reference=Path(request['profile_root'])/profile['id']/'reference.wav'
        if hashlib.sha256(reference.read_bytes()).hexdigest()!=profile['sha256']:raise ValueError('Saved voice reference changed')
        clone=model.create_voice_clone_prompt(ref_audio=str(reference),ref_text=speech_text(profile['reference_text']),x_vector_only_mode=False)
    sample_rate=24000
    for index,part in enumerate(plan):
        if part['kind']!='speech':continue
        segment=[];sections=chunks(part['text'])
        for section,text in enumerate(sections):
            print(json.dumps(dict(phase='Narrating script',chunk=section+1,total=len(sections))),flush=True)
            cached=folder/f'section-{index}-{section}.wav'
            if cached.is_file():wave,sample_rate=sf.read(cached,dtype='float32')
            else:
                torch.manual_seed((request['seed']+index*10000+section)%2147483647)
                with torch.inference_mode():wavs,sample_rate=model.generate_voice_clone(text=text,language='English',voice_clone_prompt=clone,max_new_tokens=1800)
                wave=np.asarray(wavs[0],dtype=np.float32)
                temporary=cached.with_suffix('.partial.wav');sf.write(temporary,wave,sample_rate,subtype='PCM_16');temporary.replace(cached)
            segment.append(np.zeros(round(sample_rate*.18),dtype=np.float32)) if segment else None
            segment.append(wave)
            boundary(checkpoint,'voice-section',part=index,section=section+1)

        sf.write(folder/f'speech-{index}.wav',np.concatenate(segment) if segment else np.zeros(0,dtype=np.float32),sample_rate,subtype='PCM_16')
    if model is not None:
        del model,clone
        if 'wavs' in globals():del wavs
        gc.collect();torch.cuda.empty_cache()
    if sound_cues(plan):
        print(json.dumps(dict(phase='Preparing local sound effects')),flush=True)
        python=Path(__file__).resolve().parent/'runtime/envs/unified/Scripts/python.exe'
        subprocess.run([str(python),'-B','-u',str(Path(__file__).with_name('sound_effects_job.py')),str(folder)],check=True,timeout=2700)
    sounds=json.loads((folder/'sounds.json').read_text(encoding='utf-8')) if (folder/'sounds.json').exists() else {}
    def load(index,part):return sf.read(folder/(f'speech-{index}.wav' if part['kind']=='speech' else sounds[str(index)]),dtype='float32')
    print(json.dumps(dict(phase='Mixing speech, actions and backgrounds')),flush=True)
    wave,timeline=mix_plan(plan,load,sample_rate)
    (folder/'audio-plan.json').write_text(json.dumps(dict(plan=plan,timeline=timeline)),encoding='utf-8')
if design:wave=np.concatenate(parts)
if not wave.size or not np.isfinite(wave).all() or np.max(np.abs(wave))<1e-5:raise ValueError('Generated audio was silent or invalid')
sf.write(folder/'audio.wav',wave,sample_rate,subtype='PCM_16')
(folder/'result.json').write_text(json.dumps(dict(seconds=len(wave)/sample_rate,sample_rate=sample_rate,generation_seconds=time.time()-started)))
