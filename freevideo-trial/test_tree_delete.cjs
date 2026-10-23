const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(__dirname+'/studio-tree.js','utf8');
function setup(trash=false){
 const calls=[],notices=[],p={id:'p',assets:[],chats:[],jobs:[]};
 const c={treeTrash:trash,treeData:{projects:[p]},kinds:{chats:1,images:1,audio:1,videos:1,documents:1},selection:[],activeItem:null,Map,Set,confirm:()=>true,project:id=>c.treeData.projects.find(p=>p.id===id),targetKey:t=>t.owner+':'+t.kind+':'+t.id,notify:t=>notices.push(t),api:async(...args)=>calls.push(args),reload:async()=>{},emptyWork:()=>{c.activeItem=null}};
 c.isSelected=t=>c.selection.some(x=>c.targetKey(x)===c.targetKey(t));vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('function collectionItems('),source.indexOf('\nfunction download')),c);
 vm.runInContext(source.slice(source.indexOf('function actions('),source.indexOf('\nasync function deleteProject')),c);
 return {c,p,calls,notices};
}
test('Delete on any selected asset removes the full mixed selection',async()=>{
 const {c,calls}=setup();c.selection=[{owner:'p',kind:'images',id:'a',name:'A'},{owner:'p',kind:'chats',id:'b',name:'B'}];await c.removeItems(c.selection[1]);assert.equal(calls.length,2);assert.equal(calls[0][2].action,'trash');assert.equal(calls[1][1],'/api/chats/action');assert.equal(c.selection.length,0);
});
test('Trash context menu permanently deletes every selected item',async()=>{
 const {c,p,calls}=setup(true);p.chats=[{id:'a'}];p.assets=[{id:'b'}];c.selection=[{owner:'p',kind:'chats',id:'a',name:'A'},{owner:'p',kind:'images',id:'b',name:'B'}];await c.actions(c.selection[0]).find(([label])=>label==='Permanently delete')[1]();assert.equal(calls.length,2);assert.ok(calls.every(call=>call[2].action==='purge'));
});
test('Failed-record deletion also applies to the selection',async()=>{
 const {c,p,calls}=setup();p.jobs=[{id:'j',status:'failed'}];c.selection=[{owner:'p',kind:'videos',id:'j',job:true},{owner:'p',kind:'audio',id:'a'}];await c.actions(c.selection[0]).find(([label])=>label==='Delete failed record')[1]();assert.equal(calls.length,2);assert.equal(calls[0][1],'/api/jobs/hide');
});
test('Collection Delete all includes only its type and excludes active jobs',async()=>{
 for(const kind of ['images','videos','audio','documents','chats']){const {c,p,calls}=setup();p.assets=[{id:'a',kind},{id:'t',kind,trashed:true},{id:'other',kind:'unrelated'}];p.chats=[{id:'chat'}];p.jobs=[{id:'run',kind,status:'running'},{id:'fail',kind,status:'failed'}];await c.deleteCollection({owner:'p',id:kind,name:kind});assert.equal(calls.length,2);assert.ok(calls.every(call=>!['t','other','run'].includes(call[2].id)));}
});
test('Empty Trash includes trashed assets/chats and deleted projects only',async()=>{
 const {c,p,calls}=setup(true);p.assets=[{id:'live',kind:'images'},{id:'trash',kind:'images',trashed:true}];p.chats=[{id:'chat',trashed:true}];c.treeData.projects.push({id:'deleted',name:'Deleted',deleted:true});await c.emptyTrash();assert.equal(calls.length,3);assert.equal(calls[2][1],'/api/workspaces/purge');assert.ok(calls.every(call=>call[2].id!=='live'));
});
test('Cancellation makes no calls; partial failures retain failed selection',async()=>{
 const {c,calls,notices}=setup();c.selection=[{owner:'p',kind:'images',id:'a',name:'A'},{owner:'p',kind:'images',id:'b',name:'B'}];c.confirm=()=>false;await c.removeItems(c.selection[0]);assert.equal(calls.length,0);c.confirm=()=>true;c.api=async(owner,path,value)=>{if(value.id==='a')throw Error('Retained by snapshot')};await c.removeItems(c.selection[0]);assert.equal(c.selection.length,1);assert.equal(c.selection[0].id,'a');assert.match(notices.at(-1),/Deleted 1 of 2.*snapshot/);
});
