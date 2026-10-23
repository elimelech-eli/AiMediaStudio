"""Validate project-scoped scene plans and compile visual-only direction."""
from workspace_store import identifier
from studio_characters import text,parent_snapshot

def capture(hub,w,value):
 scene=value.get('scene')
 if scene is None:return value
 if not isinstance(scene,dict):raise ValueError('Invalid scene plan')
 doc=hub.store.get(w);roles=scene.get('roles',[]);beats=scene.get('beats',[])
 if not isinstance(roles,list) or len(roles)>3:raise ValueError('Use up to three characters per scene')
 if not isinstance(beats,list) or len(beats)>24:raise ValueError('Use up to 24 scene beats')
 previous={r['id']:r for r in (parent_snapshot(hub,w,'video',value) or {}).get('characters',[])} if not value.get('refresh_characters') else {}
 normalized=[];seen=set();role_ids=set();has_speech=False
 for role in roles:
  if not isinstance(role,dict):raise ValueError('Invalid scene character')
  rid=identifier(role.get('id'));cid=identifier(role.get('character'));character=previous.get(cid) or doc.get('characters',{}).get(cid)
  if not character or character.get('trashed'):raise ValueError('Choose a character from this project for every scene card')
  if rid in role_ids or cid in seen:raise ValueError('Each character must have one scene card')
  role_ids.add(rid);seen.add(cid);speech=role.get('speech',{})
  if not isinstance(speech,dict) or speech.get('mode','none') not in ('none','text','recording','native'):raise ValueError('Invalid scene speech mode')
  mode=speech.get('mode','none');line=text(speech.get('text',''),4000,'Dialogue');recording=speech.get('recording') or None;voice=speech.get('voice') or None
  if mode=='text':
   if not line:raise ValueError('Enter the dialogue or choose No speech')
   if voice:
    identifier(voice)
    if not hub.studio(w).voice.valid_profile(hub.studio(w).voice.local_profiles/voice):raise ValueError('Choose a saved voice from this project')
  if mode=='recording':
   recording=identifier(recording);asset,_=hub.store.asset(w,recording)
   if asset['kind']!='audio':raise ValueError('Choose a project audio recording')
  has_speech=has_speech or mode in ('text','recording')
  normalized.append(dict(id=rid,character=cid,name=character['name'],actions=text(role.get('actions',''),4000,'Character actions'),speech=dict(mode=mode,text=line if mode in ('text','native') else '',voice=voice if mode=='text' else None,recording=recording if mode=='recording' else None)))
 ordered=[]
 for beat in beats:
  if not isinstance(beat,dict):raise ValueError('Invalid scene beat')
  rid=beat.get('role','')
  if rid and rid not in role_ids:raise ValueError('A scene beat refers to a removed character')
  action=text(beat.get('action',''),2000,'Scene beat')
  if not action:raise ValueError('Describe every scene beat or remove the empty beat')
  ordered.append(dict(role=rid,action=action))
 visual_only=scene.get('visual_only',False)
 if type(visual_only) is not bool:raise ValueError('Invalid scene output choice')
 if has_speech and any(r['speech']['mode']=='native' for r in normalized):raise ValueError('Native generator audio cannot be combined with unrendered Text or Recording speech plans. Choose one speech approach for this scene.')
 if has_speech and not visual_only:raise ValueError('Speech assembly and lip-sync are not connected yet. Choose Generate actions only to render the visual scene while retaining this speech plan.')
 direction=text(value.get('prompt',''),16000,'Scene direction');lines=[direction] if direction else []
 if normalized:lines.append('Cast and character direction:\n'+'\n'.join(r['name']+': '+(r['actions'] or 'Follow the scene direction and ordered beats.') for r in normalized))
 names={r['id']:r['name'] for r in normalized}
 if ordered:lines.append('Ordered scene beats (in this order):\n'+'\n'.join(str(i)+'. '+names.get(b['role'],'Scene')+': '+b['action'] for i,b in enumerate(ordered,1)))
 if not direction and not ordered and not any(r['actions'] for r in normalized):raise ValueError('Describe the scene or add character actions or scene beats')
 native=[r for r in normalized if r['speech']['mode']=='native']
 if native:lines.append('Native character audio direction:\n'+'\n'.join(r['name']+': '+('Says: '+r['speech']['text'] if r['speech']['text'] else 'Generate natural speech and vocal delivery matching this character and the scene.') for r in native))
 prompt='\n\n'.join(lines)
 if len(prompt)>16000:raise ValueError('Scene direction and actions exceed the video prompt limit; shorten the plan')
 result=dict(value,prompt=prompt,scene_snapshot=dict(version=1,direction=direction,roles=normalized,beats=ordered,visual_only=visual_only,speech_pending=has_speech))
 if normalized:result['character_ids']=[r['character'] for r in normalized]
 if native:result['audio_mode']='generated'
 elif has_speech:result['audio_mode']='silent'
 return result
