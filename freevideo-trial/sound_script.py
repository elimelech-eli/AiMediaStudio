"""Parse narration cues and mix sequential effects with changing background beds."""
import re

def cue(value,kind):
 fields=[part.strip() for part in value.split('|')];prompt=fields.pop(0)
 if not prompt or len(prompt)>240:raise ValueError('Sound descriptions must contain 1–240 characters')
 result=dict(kind=kind,prompt=prompt,seconds=8.0 if kind=='background' else 3.0,db=-20.0 if kind=='background' else -3.0)
 for field in fields:
  if re.fullmatch(r'\d+(?:\.\d+)?s',field):result['seconds']=float(field[:-1])
  elif re.fullmatch(r'-?\d+(?:\.\d+)?dB',field,re.I):result['db']=float(field[:-2])
  else:raise ValueError('Sound options use duration and volume, for example: <car horn | 2s | -6dB>')
 if not .5<=result['seconds']<=10 or not -40<=result['db']<=0:raise ValueError('Sound duration: 0.5–10 seconds; volume: -40–0 dB')
 return result

def parse_script(text):
 if not isinstance(text,str):raise ValueError('Script must be text')
 parts=[];plain=[];i=0;count=0
 def flush():
  value=''.join(plain).strip();plain.clear()
  if value:parts.append(dict(kind='speech',text=value))
 while i<len(text):
  char=text[i]
  if char=='\\' and i+1<len(text) and text[i+1] in '{}<>':plain.append(text[i+1]);i+=2;continue
  if char in '<{':
   flush();end=text.find('>' if char=='<' else '}',i+1)
   if end<0:raise ValueError('Unclosed sound cue. Use <action sound> or {background sound}.')
   value=text[i+1:end].strip()
   if any(c in value for c in '{}<>'):raise ValueError('Nested sound cues are not supported')
   if char=='{' and value.lower() in ('stop','off','stop background'):parts.append(dict(kind='background_stop'))
   elif char=='<' and re.fullmatch(r'pause:\s*\d+(?:\.\d+)?s',value,re.I):
    seconds=float(value.split(':')[1].strip()[:-1])
    if not 0<seconds<=30:raise ValueError('Pauses must be between 0 and 30 seconds')
    parts.append(dict(kind='pause',seconds=seconds))
   else:parts.append(cue(value,'action' if char=='<' else 'background'))
   count+=1
   if count>12:raise ValueError('Use at most twelve sound/pause/background cues per clip')
   i=end+1
  elif char in '>}':raise ValueError('Unmatched sound cue delimiter; escape literal brackets with a backslash')
  else:plain.append(char);i+=1
 flush()
 if not parts:raise ValueError('Enter speech or sound cues')
 return parts

def sound_cues(plan):return [part for part in plan if part['kind'] in ('action','background')]

def resample_mono(audio,source_rate,target_rate):
 import numpy as np
 from scipy.signal import resample_poly
 from math import gcd
 audio=np.asarray(audio,dtype=np.float32)
 if audio.ndim>1:audio=audio.mean(axis=1)
 if source_rate!=target_rate:
  factor=gcd(int(source_rate),int(target_rate));audio=resample_poly(audio,target_rate//factor,source_rate//factor).astype(np.float32)
 return audio

def loop_bed(audio,length,rate):
 import numpy as np
 audio=np.asarray(audio,dtype=np.float32)
 if not len(audio):raise ValueError('Empty sound effect')
 fade=min(round(rate*.04),len(audio)//4)
 output=audio.copy()
 while len(output)<length:
  if fade:
   ramp=np.linspace(0,1,fade,dtype=np.float32);output=np.concatenate((output[:-fade],output[-fade:]*(1-ramp)+audio[:fade]*ramp,audio[fade:]))
  else:output=np.concatenate((output,audio))
 return output[:length]

def mix_plan(plan,load,rate=24000):
 import numpy as np
 pieces=[];cursor=0;active=None;beds=[];timeline=[]
 for index,part in enumerate(plan):
  kind=part['kind']
  if kind in ('background','background_stop'):
   if active:beds.append((*active,cursor))
   active=(index,cursor) if kind=='background' else None
   continue
  if kind=='pause':audio=np.zeros(round(rate*part['seconds']),dtype=np.float32)
  else:
   audio,sample_rate=load(index,part);audio=resample_mono(audio,sample_rate,rate)
   if kind=='action':audio=audio[:round(rate*part['seconds'])]*10**(part['db']/20)
  pieces.append(audio);timeline.append(dict(index=index,kind=kind,start=cursor/rate,end=(cursor+len(audio))/rate));cursor+=len(audio)
 if not cursor and active:cursor=round(rate*plan[active[0]]['seconds']);pieces=[np.zeros(cursor,dtype=np.float32)]
 if active:beds.append((*active,cursor))
 if not cursor:raise ValueError('No playable audio in script')
 result=np.concatenate(pieces)
 for index,start,end in beds:
  if end<=start:continue
  audio,sample_rate=load(index,plan[index]);audio=resample_mono(audio,sample_rate,rate);bed=loop_bed(audio,end-start,rate)*10**(plan[index]['db']/20)
  fade=min(round(rate*.04),len(bed)//2)
  if fade:bed[:fade]*=np.linspace(0,1,fade);bed[-fade:]*=np.linspace(1,0,fade)
  result[start:end]+=bed;timeline.append(dict(index=index,kind='background',start=start/rate,end=end/rate))
 if not np.isfinite(result).all():raise ValueError('Invalid mixed audio')
 peak=np.max(np.abs(result))
 if peak>.98:result*=.98/peak
 return result,timeline
