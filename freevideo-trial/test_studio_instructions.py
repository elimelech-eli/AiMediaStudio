import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from workspace_store import WorkspaceStore
from studio_instructions import Instructions,behavior_prompt
from workspace_portable import PortableProjects

class InstructionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=WorkspaceStore(Path(self.temp.name)/'work');self.instructions=Instructions(self.store);self.a=self.store.create('A')['id'];self.b=self.store.create('B')['id']
 def save(self,scope,text,w=None,**extra):
  w=w or self.a;old=self.instructions.state(w)[scope+'_layer' if scope=='global' else 'project_layer']
  return self.instructions.save(w,scope,dict(text=text,name=scope+'.md',enabled=True,revision=old['revision'],**extra))
 def test_global_and_project_layers_are_recaptured_without_cross_project_leaks(self):
  self.save('global','Use a dry, witty tone.');self.save('project','Your name is Mira.')
  a=self.instructions.capture(self.a);b=self.instructions.capture(self.b);free=self.instructions.capture('free-work')
  self.assertIn('Mira',behavior_prompt(a));self.assertNotIn('Mira',behavior_prompt(b));self.assertNotIn('Mira',behavior_prompt(free));self.assertIn('witty',behavior_prompt(b))
  self.save('global','Use short answers.');self.assertIn('short answers',behavior_prompt(self.instructions.capture(self.a)));self.assertIn('witty',behavior_prompt(a))
  self.assertLess(behavior_prompt(a).index('Global behavior instructions'),behavior_prompt(a).index('Project behavior instructions'))
 def test_disabled_layer_conflicts_and_oversized_input(self):
  self.save('project','Mira')
  old=self.instructions.state(self.a)['project_layer'];self.instructions.save(self.a,'project',dict(old,enabled=False));self.assertNotIn('Mira',behavior_prompt(self.instructions.capture(self.a)))
  with self.assertRaises(ValueError):self.instructions.save(self.a,'project',dict(old,text='Stale overwrite'))
  with self.assertRaises(ValueError):self.save('global','x'*16001)
  self.store.update(self.a,{'archived':True})
  with self.assertRaises(ValueError):self.save('project','Cannot edit archived project')
 def test_project_instructions_survive_branch_export_and_source_changes(self):
  self.save('global','Global should stay global');self.save('project','Original project personality')
  portable=PortableProjects(self.store,self.store.root/'shared/voices/profiles');snapshot=self.store.snapshot(self.a,'Original');self.save('project','Changed personality')
  branch=portable.branch(self.a,'Branch',snapshot['id']);self.assertEqual(branch['chat_behavior']['text'],'Original project personality')
  archive=portable.export(self.a);imported=portable.import_zip(portable.exports/archive['file']);self.assertEqual(imported['chat_behavior']['text'],'Changed personality');self.assertNotIn('Global should stay global',json.dumps(imported))
 def test_real_chat_message_assembly_receives_both_layers_and_retains_tool_contract(self):
  import studio_chat
  self.save('global','GLOBAL_SENTINEL');self.save('project','PROJECT_SENTINEL')
  class Process:
   stdin=io.StringIO();stdout=io.StringIO(json.dumps({'text':'Neutral test reply'})+'\n')
   def poll(self):return None
  process=Process();chat=studio_chat.StudioChat(Path(self.temp.name)/'chat.json')
  with patch.object(studio_chat.StudioChat,'worker',return_value=process),patch.object(studio_chat.StudioChat,'_shared_process',process),patch.object(studio_chat.StudioChat,'_active_chat',None),patch.object(studio_chat.StudioChat,'_warming',False):
   chat.reply({'text':'Hello','mode':'cpu','behavior_layers':self.instructions.capture(self.a)},[])
  message=json.loads(process.stdin.getvalue())['messages'][0]['content'];self.assertIn('GLOBAL_SENTINEL',message);self.assertIn('PROJECT_SENTINEL',message);self.assertIn('studio block',message)
