"""Named conversations with independent workers/history and manifest-backed portability."""
import json,time
from studio_chat import StudioChat
from workspace_store import key,identifier,atomic

class Conversations:
 def __init__(self,hub):self.hub=hub;self.instances={}
 def rows(self,w):
  store=self.hub.store
  with store.lock:
   doc=store.get(w)
   if 'chats' not in doc:
    path=store.folder(w)/'conversations/chat.json'
    messages=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    doc['chats']={}
    if messages:
     id=key();doc['chats'][id]=dict(id=id,name='Writing session',messages=messages,created=time.time(),trashed=False)
    store.save(doc)
   return doc['chats']
 def listing(self,w):return [{k:v for k,v in row.items() if k!='messages'} for row in self.rows(w).values()]
 def get(self,w,id):
  row=self.rows(w).get(identifier(id))
  if not row or row.get('trashed'):raise ValueError('Conversation unavailable; restore it from trash')
  return row
 def instance(self,w,id):
  row=self.get(w,id);pair=(w,id)
  with self.hub.store.lock:
   if pair not in self.instances:
    chat=StudioChat(self.hub.store.folder(w)/'conversations'/f'{id}.json');chat.messages=row['messages']
    def save():
     with self.hub.store.lock:
      doc=self.hub.store.get(w);doc['chats'][id]['messages']=chat.messages;self.hub.store.save(doc)
      atomic(chat.path,chat.messages)
    chat.save=save;self.instances[pair]=chat
   return self.instances[pair]
 def busy(self,w=None):return any(c.busy for (owner,_),c in self.instances.items() if w is None or owner==w)
 def action(self,w,value):
  store=self.hub.store;action=value.get('action');id=value.get('id')
  with store.lock:
   doc=store.get(w)
   if doc.get('archived') or doc.get('deleted'):raise ValueError('Restore the project first')
   if self.busy(w) or w in store.operation_pins or (self.hub.active() and self.hub.active()['workspace']==w):raise ValueError('Wait for this project’s active conversation or file operation')
   rows=self.rows(w);doc=store.get(w)
   name=str(value.get('name') or 'Untitled chat').strip()[:100]
   if action=='create':
    id=key();doc['chats'][id]=dict(id=id,name=name,messages=[],created=time.time(),trashed=False)
   else:
    identifier(id)
    if id not in rows:raise ValueError('Conversation not found')
    if action=='rename':doc['chats'][id]['name']=name
    elif action in ('trash','restore'):doc['chats'][id]['trashed']=action=='trash'
    elif action=='purge':
     if not rows[id].get('trashed'):raise ValueError('Delete the conversation first')
     del doc['chats'][id];(store.folder(w)/'conversations'/f'{id}.json').unlink(missing_ok=True)
    elif action in ('duplicate','copy','move'):
     destination=value.get('destination',w);target=store.get(destination)
     if target.get('deleted') or target.get('archived') or self.busy(destination) or destination in store.operation_pins:raise ValueError('Destination unavailable or busy')
     self.rows(destination);target=store.get(destination)
     new=key();target['chats'][new]=dict(rows[id],id=new,name=name if value.get('name') else rows[id]['name']+' copy',created=time.time(),messages=json.loads(json.dumps(rows[id]['messages'])))
     # Historical proposals retain their original ownership guard. They cannot run against unrelated assets.
     if destination==w:doc=target
     else:store.save(target)
     if action=='move':doc['chats'][id]['trashed']=True
     id=new
    else:raise ValueError('Unknown conversation action')
   store.save(doc);return dict(id=id,ok=True)
