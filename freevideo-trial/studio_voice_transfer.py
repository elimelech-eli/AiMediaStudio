"""Journaled saved-voice transfers; retain source references for existing recordings."""
import json,shutil
from pathlib import Path
from workspace_store import atomic,contained,digest,identifier,key
from voice_studio import VoiceStudio

def reader(store,w):
 voice=VoiceStudio.__new__(VoiceStudio);voice.local_profiles=store.folder(w)/'voices/profiles';voice.local_profiles.mkdir(parents=True,exist_ok=True);return voice

def finish(store,operation):
 source=store.folder(operation['source']);destination=store.folder(operation['destination']);journal=store.root/'operations'/(operation['id']+'.json')
 for item in operation['voices']:
  original=contained(source,source/'voices/profiles'/identifier(item['source']))
  target=contained(destination,destination/'voices/profiles'/identifier(item['profile']['id']))
  if target.exists():
   if digest(contained(destination,target/'reference.wav'))!=item['sha256']:raise ValueError('Destination voice differs; source was retained')
   if json.loads((target/'profile.json').read_text(encoding='utf-8'))!=item['profile']:raise ValueError('Destination voice metadata differs; source was retained')
  else:
   if digest(contained(source,original/'reference.wav'))!=item['sha256']:raise ValueError('Saved voice changed; source was retained')
   stage=contained(destination,target.parent/('.transfer-'+operation['id']+'-'+target.name));stage.mkdir(exist_ok=True)
   shutil.copyfile(original/'reference.wav',stage/'reference.wav');atomic(stage/'profile.json',item['profile'])
   if digest(stage/'reference.wav')!=item['sha256']:raise ValueError('Voice copy verification failed; source was retained')
   stage.rename(target)
 operation['state']='copied';atomic(journal,operation)
 if operation['move']:
  doc=store.get(operation['source']);changed=False
  for item in operation['voices']:
   original=contained(source,source/'voices/profiles'/identifier(item['source'])/'profile.json');row=json.loads(original.read_text(encoding='utf-8'));row['library_hidden']=True;atomic(original,row)
   if doc['context'].get('voice')==item['source']:doc['context']['voice']=None;doc['context']['revision']+=1;changed=True
  if changed:store.save(doc)
 operation['state']='complete';atomic(journal,operation)
 return {'voices':[{'source':item['source'],'id':item['profile']['id'],'name':item['profile']['name']} for item in operation['voices']]}

def transfer(hub,w,value):
 store=hub.store;destination=identifier(value.get('destination'));ids=value.get('id');ids=ids if isinstance(ids,list) else [ids]
 if w==destination:raise ValueError('Choose another project')
 if not ids or len(set(ids))!=len(ids):raise ValueError('Choose unique saved voices')
 with hub.gate,store.lock:
  for owner in (w,destination):
   doc=store.get(owner)
   if doc.get('archived') or doc.get('deleted'):raise ValueError('Restore both projects before transferring voices')
   if owner in hub.queue.protected_owners() or owner in store.operation_pins or (hub.active() or {}).get('workspace')==owner or hub.conversations.busy(owner):raise ValueError('Wait for active or paused work in these projects before transferring voices')
  voice=reader(store,w);target_root=reader(store,destination).local_profiles;items=[]
  for id in ids:
   identifier(id);row=voice.valid_profile(contained(store.folder(w),voice.local_profiles/id))
   if not row or row.get('library_hidden'):raise ValueError('Saved voice not found in this project')
   sha=digest(voice.local_profiles/id/'reference.wav')
   if row.get('sha256')!=sha:raise ValueError('Saved voice reference failed verification')
   new=id if value['action']=='move' and not (target_root/id).exists() else key()
   profile=dict(row,id=new,trashed=False,library_hidden=False);profile.pop('hidden',None)
   items.append(dict(source=id,profile=profile,sha256=sha))
  operation=dict(id=key(),kind='voice-transfer',state='copying',source=w,destination=destination,move=value['action']=='move',voices=items)
  atomic(store.root/'operations'/(operation['id']+'.json'),operation);store.operation_pins.update((w,destination))
  result=finish(store,operation)
  store.operation_pins.difference_update((w,destination));return result

def recover(store):
 for file in (store.root/'operations').glob('*.json'):
  operation=json.loads(file.read_text(encoding='utf-8'))
  if operation.get('kind')=='voice-transfer' and operation.get('state')!='complete':
   owners=(operation['source'],operation['destination']);store.operation_pins.update(owners)
   try:finish(store,operation)
   except (OSError,ValueError,KeyError) as error:
    store.recovery_errors.append({'operation':operation['id'],'error':str(error)})
    from studio_diagnostics import LOG
    LOG.record('error','voice','Saved voice transfer recovery needs attention',job=operation['id'],details=str(error))
   else:store.operation_pins.difference_update(owners)
