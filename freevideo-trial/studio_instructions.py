"""Editable global and workspace behavior layers, captured afresh for every chat turn."""
import json,threading
from pathlib import Path
from workspace_store import atomic

def empty():return dict(text='',name='',enabled=True,revision=0)
def validate(value):
 if not isinstance(value,dict):raise ValueError('Invalid behavior instructions')
 text=value.get('text','');name=value.get('name','');enabled=value.get('enabled',True)
 if not isinstance(text,str) or len(text)>16000 or '\0' in text:raise ValueError('Instructions must be text, up to 16,000 characters per layer')
 if not isinstance(name,str) or len(name)>120 or type(enabled) is not bool:raise ValueError('Invalid instruction name or enabled state')
 return dict(text=text,name=name,enabled=enabled)

class Instructions:
 def __init__(self,store):self.store=store;self.path=store.root/'shared/chat-instructions.json';self.lock=threading.RLock()
 def global_layer(self):
  try:return json.loads(self.path.read_text(encoding='utf-8'))
  except FileNotFoundError:return empty()
 def state(self,w):
  with self.lock,self.store.lock:
   doc=self.store.get(w);return dict(workspace=w,workspace_name=doc['name'],readonly=bool(doc.get('archived') or doc.get('deleted')),global_layer=self.global_layer(),project_layer=doc.get('chat_behavior',empty()))
 def save(self,w,scope,value):
  layer=validate(value)
  with self.lock,self.store.lock:
   doc=self.store.get(w)
   if scope not in ('global','project'):raise ValueError('Choose global or project instructions')
   if scope=='project' and (doc.get('archived') or doc.get('deleted')):raise ValueError('Restore the project before editing its instructions')
   old=self.global_layer() if scope=='global' else doc.get('chat_behavior',empty())
   if value.get('revision')!=old['revision']:raise ValueError('Instructions changed elsewhere. Reload before saving.')
   layer['revision']=old['revision']+1
   if scope=='global':atomic(self.path,layer)
   else:doc['chat_behavior']=layer;self.store.save(doc)
   return self.state(w)
 def capture(self,w):
  state=self.state(w)
  return {key:dict(state[key]) for key in ('global_layer','project_layer')}

def behavior_prompt(layers):
 blocks=[]
 for key,title in (('global_layer','Global behavior instructions'),('project_layer','Project behavior instructions')):
  layer=(layers or {}).get(key,{})
  if layer.get('enabled',True) and layer.get('text','').strip():blocks.append(title+' ('+(layer.get('name') or 'edited in Settings')+'):\n'+layer['text'])
 if not blocks:return ''
 return '\n\nFollow these behavior instructions in conversation. Project behavior takes precedence over conflicting global behavior preferences. Stay consistent with the configured personality; do not replace it with the default writing-assistant identity. Studio tool formats and honest capability reporting still apply.\n\n'+'\n\n'.join(blocks)
