"""Project characters, immutable job snapshots and adapter-aware identity guidance."""
import copy,json,re,time
from workspace_store import key,identifier

def definitions(doc):return doc.get('characters',{})
def asset_ids(character):
 refs=[r['asset'] for r in character.get('references',[])];refs += [a for outfit in character.get('outfits',[]) for a in outfit.get('references',[])]
 return list(dict.fromkeys(refs))
def retained_assets(doc):
 return set(a for row in definitions(doc).values() for version in [row,*row.get('history',[])] for a in asset_ids(version))
def remap_character(row,assets,voices):
 row=copy.deepcopy(row)
 for version in [row,*row.get('history',[])]:
  for ref in version.get('references',[]):ref['asset']=assets.get(ref['asset'],ref['asset'])
  for outfit in version.get('outfits',[]):outfit['references']=[assets.get(a,a) for a in outfit.get('references',[])]
  if version.get('voice'):version['voice']=voices.get(version['voice'],version['voice'])
  if 'active_references' in version:version['active_references']=[assets.get(a,a) for a in version['active_references']]
  if version.get('asset_fingerprints'):version['asset_fingerprints']={assets.get(a,a):sha for a,sha in version['asset_fingerprints'].items()}
 return row

def remap_settings(settings,assets,voices):
 for role in (settings.get('scene_snapshot') or {}).get('roles',[]):
  speech=role.get('speech',{})
  if speech.get('recording'):speech['recording']=assets.get(speech['recording'],speech['recording'])
  if speech.get('voice'):speech['voice']=voices.get(speech['voice'],speech['voice'])
 for target in (settings,settings.get('context_snapshot',{})):
  snapshot=target.get('character_snapshot')
  if snapshot:snapshot['characters']=[remap_character(row,assets,voices) for row in snapshot.get('characters',[])]
 if settings.get('character_reference_ids'):settings['character_reference_ids']={id:[assets.get(a,a) for a in ids] for id,ids in settings['character_reference_ids'].items()}
 # Compatibility aliases belong to the source workspace; reconstruct them at admission.
 settings.pop('character_guidance',None)

def voice_ids(settings):
 return {r['speech']['voice'] for r in (settings.get('scene_snapshot') or {}).get('roles',[]) if r.get('speech',{}).get('voice')} | {r['voice'] for r in (settings.get('character_snapshot') or {}).get('characters',[]) if r.get('voice')} | ({settings['profile']} if settings.get('profile') else set())

def legacy_description(ref):
 return {'face':'Face and facial identity','body':'Body and proportions','image':'','motion':'Motion reference','sound':'Sound reference','outfit':'Outfit and clothing'}.get(ref.get('role'),'')

def reference_description(ref):return ref.get('description',legacy_description(ref)) or 'General character reference; infer relevant visual features'

def image_references(row):return [r for r in row.get('references',[]) if r.get('role','image') in ('face','body','image')]

def choose_references(hub,w,engine,result,value,rows,previous,strict):
 """Fit automatic choices to adapter capacity; explicit/inherited choices never silently shrink."""
 choices=value.get('character_reference_ids',{})
 if not isinstance(choices,dict):raise ValueError('Invalid character reference selection')
 if any(id not in {r['id'] for r in rows} for id in choices):raise ValueError('Reference selection belongs to an unselected character')
 existing=set(result.get('images',[]) if engine=='image' else [v for v in [result.get('image'),result.get('identity_image') if result.get('identity_mode') else None] if v])
 used=set(existing);reserved=1 if engine=='video' and value.get('continue_from') else 0
 refs=[];automatic=[];cache={}
 def alias(a):
  if a not in cache:cache[a]=hub.use_asset(w,a)['image']
  return cache[a]
 def append(ref,row,required):
  image=alias(ref['asset']);fits=image in used or len(used)+reserved<4
  if not fits:
   if required:raise ValueError('Selected character references and existing inputs exceed four images; choose fewer references')
   return False
  used.add(image);refs.append(dict(ref,character=row['name'],description=reference_description(ref)));return True
 for row in rows:
  available=image_references(row);by_id={r['asset']:r for r in available};id=row['id']
  explicit=id in choices
  inherited=id in previous and not value.get('refresh_characters') and previous[id].get('reference_selection_mode')=='manual'
  selected=choices[id] if explicit else previous[id]['active_references'] if inherited else None
  if selected is not None:
   if not isinstance(selected,list) or len(selected)>10 or any(not isinstance(a,str) or a not in by_id for a in selected):raise ValueError('Choose reference images from this captured character version')
   selected=list(dict.fromkeys(selected))
   if strict and not selected:raise ValueError(row['name']+' needs at least one reference image for Strict continuity')
   for a in selected:append(by_id[a],row,True)
  else:
   if strict and not available:raise ValueError(row['name']+' needs at least one reference image for Strict continuity')
   order=previous.get(id,{}).get('active_references',[]) if not value.get('refresh_characters') else []
   available=sorted(available,key=lambda r:order.index(r['asset']) if r['asset'] in order else len(order))
   automatic.append((row,available));selected=[]
  row['reference_selection_mode']='manual' if explicit or inherited else 'automatic'
  row['active_references']=list(selected)
 # Allocate one identity image per character before filling the remaining slots.
 for row,available in automatic:
  if available and append(available[0],row,strict):row['active_references'].append(available[0]['asset'])
 for row in rows:
  outfit=next((o for o in row.get('outfits',[]) if o['id']==row['state'].get('outfit')),None)
  if outfit:
   for a in outfit.get('references',[])[:1]:append(dict(asset=a,role='image',description='Selected outfit: '+outfit['name']+'; '+outfit['description']),row,True)
 for row,available in automatic:
  for ref in available[1:]:
   if append(ref,row,False):row['active_references'].append(ref['asset'])
 return refs

def text(value,limit,label):
 if not isinstance(value,str) or len(value)>limit:raise ValueError(label+' is too long or invalid')
 return value.strip()
def validate(value,doc,voice_exists=None):
 if not isinstance(value,dict):raise ValueError('Invalid character definition')
 name=text(value.get('name',''),80,'Character name')
 if not name:raise ValueError('Give the character a name')
 aliases=value.get('aliases',[])
 if not isinstance(aliases,list) or len(aliases)>12:raise ValueError('Use at most 12 aliases')
 aliases=list(dict.fromkeys(text(a,80,'Alias') for a in aliases if a))
 refs=value.get('references',[])
 if not isinstance(refs,list) or len(refs)>26:raise ValueError('Use at most 10 reference images')
 normalized=[];image_count=0;seen=set()
 for ref in refs:
  if not isinstance(ref,dict):raise ValueError('Invalid character reference')
  a=identifier(ref.get('asset'));role=ref.get('role','image');asset=doc['assets'].get(a)
  expected={'face':'images','body':'images','image':'images','motion':'videos','sound':'audio'}.get(role)
  if not expected or not asset or asset.get('trashed') or asset.get('kind')!=expected:raise ValueError('Character references must be matching assets from this project')
  description=text(ref.get('description',legacy_description(ref)),1000,'Reference description')
  if a in seen:
   previous=next(r for r in normalized if r['asset']==a)
   previous['description']=text('; '.join(dict.fromkeys(x for x in [previous['description'],description] if x)),1000,'Combined reference description')
   continue
  seen.add(a)
  if expected=='images':image_count+=1
  if image_count>10:raise ValueError('Use at most 10 reference images')
  normalized.append(dict(asset=a,role='image' if expected=='images' else role,description=description))
 outfits=value.get('outfits',[])
 if not isinstance(outfits,list) or len(outfits)>12:raise ValueError('Use at most 12 outfits')
 outfits=copy.deepcopy(outfits)
 for outfit in outfits:
  if not isinstance(outfit,dict):raise ValueError('Invalid outfit')
  outfit['id']=identifier(outfit.get('id') or key());outfit['name']=text(outfit.get('name',''),80,'Outfit name');outfit['description']=text(outfit.get('description',''),2000,'Outfit description')
  if not outfit['name']:raise ValueError('Name each outfit')
  if not isinstance(outfit.get('references',[]),list) or len(outfit.get('references',[]))>4:raise ValueError('Use at most four outfit references')
  outfit['references']=list(dict.fromkeys(outfit.get('references',[])))
  for a in outfit['references']:
   if doc['assets'].get(a,{}).get('kind')!='images' or doc['assets'][a].get('trashed'):raise ValueError('Outfit references must be project images')
 if len({o['id'] for o in outfits})!=len(outfits):raise ValueError('Outfit IDs must be unique')
 state=value.get('state',{})
 if not isinstance(state,dict):raise ValueError('Invalid character state')
 outfit=state.get('outfit') or None
 if outfit and outfit not in {o['id'] for o in outfits}:raise ValueError('Choose an existing outfit')
 voice=value.get('voice') or None
 if voice:
  identifier(voice)
  if voice_exists and not voice_exists(voice):raise ValueError('Choose a saved voice from this project')
 return dict(name=name,aliases=aliases,appearance=text(value.get('appearance',''),4000,'Appearance'),body_language=text(value.get('body_language',''),2000,'Body language'),behavior=text(value.get('behavior',''),16000,'Behavior instructions'),voice=voice,voice_notes=text(value.get('voice_notes',''),2000,'Voice notes'),references=normalized,outfits=outfits,state=dict(outfit=outfit,location=text(state.get('location',''),200,'Location'),hairstyle=text(state.get('hairstyle',''),200,'Hairstyle'),props=text(state.get('props',''),500,'Props'),notes=text(state.get('notes',''),2000,'Scene notes')))

def action(hub,w,value):
 with hub.gate,hub.store.lock:
  doc=hub.store.get(w)
  if doc.get('archived') or doc.get('deleted') or w in hub.store.operation_pins:raise ValueError('Restore the project or wait for its file operation')
  rows=doc.setdefault('characters',{});kind=value.get('action');id=value.get('id')
  if kind=='save':
   id=identifier(id) if id else key();old=rows.get(id)
   if old and value.get('revision')!=old['revision']:raise ValueError('Character changed; reopen it before saving')
   row=validate(value.get('character',{}),doc,lambda v:hub.studio(w).voice.valid_profile(hub.studio(w).voice.local_profiles/v) is not None)
   names={x.casefold() for x in [row['name'],*row['aliases']]}
   for other in rows.values():
    if other['id']!=id and not other.get('trashed') and names.intersection(x.casefold() for x in [other['name'],*other.get('aliases',[])]):raise ValueError('Another character already uses that name or alias')
   history=copy.deepcopy(old.get('history',[])) if old else []
   if old:history.append({k:copy.deepcopy(v) for k,v in old.items() if k!='history'})
   row.update(id=id,revision=(old or {}).get('revision',0)+1,trashed=False,updated=time.time(),history=history);rows[id]=row
  elif kind in ('trash','restore','duplicate','purge'):
   id=identifier(id);row=rows.get(id)
   if not row:raise ValueError('Character not found')
   if kind=='purge':
    if not row.get('trashed') or w in hub.queue.protected_owners():raise ValueError('Only inactive trashed characters can be purged')
    if any(id in s.get('characters',{}) for s in doc.get('snapshots',{}).values()):raise ValueError('Character is retained by a project snapshot')
    del rows[id];hub.store.save(doc);return {'ok':True}
   if kind=='duplicate':
    row=copy.deepcopy(row);base=row['name'][:65]+' copy';name=base;index=2
    used={n.casefold() for c in rows.values() if not c.get('trashed') for n in [c['name'],*c.get('aliases',[])]}
    while name.casefold() in used:name=base+' '+str(index);index+=1
    row.update(id=key(),name=name,aliases=[],revision=1,history=[],trashed=False);rows[row['id']]=row
   else:
    if kind=='restore':
     names={n.casefold() for n in [row['name'],*row.get('aliases',[])]}
     if any(other['id']!=id and not other.get('trashed') and names.intersection(n.casefold() for n in [other['name'],*other.get('aliases',[])]) for other in rows.values()):raise ValueError('Another character uses this name or alias; rename it before restoring')
    row['trashed']=kind=='trash'
  else:raise ValueError('Unknown character action')
  hub.store.save(doc);return row

def mentioned(rows,prompt):
 return [row for row in rows if any(re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',prompt,re.I) for name in [row['name'],*row.get('aliases',[])] if name)]

def parent_snapshot(hub,w,engine,value):
 parent=None
 if value.get('character_source_asset'):
  source,_=hub.store.asset(w,identifier(value['character_source_asset']))
  parent=copy.deepcopy(source.get('metadata',{}).get('settings',{}).get('character_snapshot'))
 if value.get('character_source_job') and engine=='video':
  from workspace_store import contained
  source_id=value['character_source_job']
  if not isinstance(source_id,str) or not re.fullmatch(r'[0-9a-f]{32}|[0-9]{8}-[0-9]{6}-[0-9a-f]{8}',source_id):raise ValueError('Invalid source image job')
  folder=hub.store.folder(w);source=json.loads(contained(folder,folder/'image-jobs'/source_id/'job.json').read_text(encoding='utf-8'))
  if source.get('status')!='completed':raise ValueError('Source image is not completed')
  parent=source.get('settings',{}).get('character_snapshot')
 if value.get('continue_from') and engine in ('video','voice'):
  from workspace_store import contained
  from pathlib import Path
  id=value['continue_from']
  if not isinstance(id,str) or not re.fullmatch(r'[0-9a-f]{32}|[0-9]{8}-[0-9]{6}-[0-9a-f]{8}',id):raise ValueError('Invalid continuation job')
  folder=hub.store.folder(w);sub='jobs' if engine=='video' else 'voices/jobs';file=contained(folder,folder/sub/id/'job.json');parent=json.loads(file.read_text(encoding='utf-8'))['settings'].get('character_snapshot')
 return parent

def enrich(hub,w,engine,result,value):
 doc=hub.store.get(w);available=[r for r in definitions(doc).values() if not r.get('trashed')];prompt=value.get('prompt' if engine in ('video','image') else 'text','')
 if not isinstance(prompt,str):raise ValueError('Enter a text prompt or script')
 if not isinstance(value.get('character_revisions',{}),dict):raise ValueError('Invalid character revision selection')
 selected=value.get('character_ids');parent=parent_snapshot(hub,w,engine,value)
 previous={r['id']:r for r in (parent or {}).get('characters',[])}
 if selected is None:
  rows=mentioned(available,prompt);ids=list(dict.fromkeys([*previous,*[r['id'] for r in rows]]))
 else:
  if not isinstance(selected,list) or len(selected)>3:raise ValueError('Select at most three characters')
  ids=list(dict.fromkeys(selected))
 if len(ids)>3:raise ValueError('Select at most three characters per job')
 strict=value.get('strict_continuity',(parent or {}).get('strict',True));use_refs=value.get('use_character_references',(parent or {}).get('use_references',True))
 if type(strict) is not bool or type(use_refs) is not bool or type(value.get('refresh_characters',False)) is not bool:raise ValueError('Invalid continuity option')
 outfits=value.get('character_outfits',{})
 if not isinstance(outfits,dict):raise ValueError('Invalid character outfit selection')
 rows=[]
 for id in ids:
  identifier(id);row=copy.deepcopy(previous[id]) if id in previous and not value.get('refresh_characters') else next((copy.deepcopy(r) for r in available if r['id']==id),None)
  if row is None:raise ValueError('Selected character is not available in this project')
  if value.get('character_revisions',{}).get(id,row['revision'])!=row['revision']:raise ValueError('Character changed since this proposal; review the character selection again')
  row.pop('history',None)
  if outfits.get(id):
   if outfits[id] not in {o['id'] for o in row.get('outfits',[])}:raise ValueError('Outfit is not part of this captured character version; use latest definitions to change it')
   row['state']['outfit']=outfits[id]
  row['asset_fingerprints']={a:hub.store.asset(w,a)[0]['sha256'] for a in asset_ids(row)}
  for a,sha in row['asset_fingerprints'].items():
   if id in previous and not value.get('refresh_characters') and previous[id].get('asset_fingerprints',{}).get(a,sha)!=sha:raise ValueError('A captured character reference changed')
  rows.append(row)
 if not rows:return result
 if engine=='voice' and value.get('action')=='read':
  if len(rows)!=1:raise ValueError('Narration uses one saved character voice at a time')
  if strict and not rows[0].get('voice') and not result.get('profile'):raise ValueError('Assign this character a saved voice or select a narration voice')
  if rows[0].get('voice') and not value.get('override_character_voice',False):result['profile']=rows[0]['voice']
 if engine in ('video','image') and strict and not use_refs:raise ValueError('Strict continuity requires identity guidance; enable references or turn Strict off')
 refs=[];warnings=[];parts=[]
 for row in rows:
  state=row['state'];outfit=next((o for o in row.get('outfits',[]) if o['id']==state.get('outfit')),None)
  parts.append('Character '+row['name']+' (version '+str(row['revision'])+'): '+row['appearance']+'\nManner while performing the requested action (not a separate activity): '+row.get('body_language','')+('\nCurrent state: '+json.dumps({k:v for k,v in state.items() if v},ensure_ascii=False) if any(state.values()) else '')+('\nOutfit: '+outfit['name']+' — '+outfit['description'] if outfit else ''))
  if row.get('voice') or any(r['role']=='sound' for r in row.get('references',[])):warnings.append('Saved voices apply to narration; video dialogue is not bound to saved voices. Sound references are retained, not automatically cloned into video.')
  if any(r['role']=='motion' for r in row.get('references',[])):warnings.append('Motion reference clips are retained in the character; use an explicit video reference to guide motion.')
 if engine in ('video','image') and use_refs:
  refs=choose_references(hub,w,engine,result,value,rows,previous,strict)
  for row in rows:
   count=len(image_references(row));selected=len(row.get('active_references',[]))
   if selected<count:warnings.append(row['name']+': using '+str(selected)+' of '+str(count)+' reference images within the engine capacity; adjust reference selection to change them.')
 elif engine in ('video','image'):
  for row in rows:row['active_references']=[]
 if engine in ('video','image'):
  result['prompt']=result.get('prompt','')+'\n\nAppearance reference context (preserve identity, proportions and outfit; the requested scene/action takes priority over reference poses):\n'+'\n\n'.join(parts)
  if len(result['prompt'])>(16000 if engine=='video' else 2000):raise ValueError('Prompt plus character descriptions exceeds this engine limit; shorten the descriptions or choose fewer characters')
  if engine=='image':
   images=list(result.get('images',[]))
   for ref in refs:
    alias=hub.use_asset(w,ref['asset'])['image']
    if alias not in images:images.append(alias)
    result['prompt']+='\nReference image '+str(images.index(alias)+1)+' for '+ref['character']+'. Guidance: '+reference_description(ref)+'.' 
   if len(images)>4:raise ValueError('Character and existing references exceed four images; use fewer characters/outfit references')
   result['images']=images
  elif refs:
   guidance=[dict(r,image=hub.use_asset(w,r['asset'])['image']) for r in refs]
   images={r['image'] for r in guidance}
   if result.get('image'):images.add(result['image'])
   if result.get('identity_mode') and result.get('identity_image'):images.add(result['identity_image'])
   if len(images)+(1 if value.get('continue_from') else 0)>4:raise ValueError('Character references plus starting image exceed four images; select fewer characters or outfit references')
   result['character_guidance']=guidance
   warnings.append('Video identity guidance uses reference conditioning; exact last-frame anchoring and identity are not both guaranteed.')
 snapshot=dict(version=1,characters=rows,strict=strict,use_references=use_refs,roles=text(value.get('character_roles',''),1000,'Scene roles'),warnings=list(dict.fromkeys(warnings)))
 if engine in ('video','image') and snapshot['roles']:result['prompt']+='\nScene roles: '+snapshot['roles']
 if engine in ('video','image') and len(result['prompt'])>(16000 if engine=='video' else 2000):raise ValueError('Prompt and character guidance exceed the engine prompt limit; shorten reference descriptions, appearance, state or body language')
 result['character_snapshot']=snapshot
 return result
