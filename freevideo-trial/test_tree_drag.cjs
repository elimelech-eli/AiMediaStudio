const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(__dirname+'/studio-tree.js','utf8');
function harness(){
 class El{constructor(){this.children=[];this.dataset={};this.style={};const set=new Set();this.classList={add:(...xs)=>xs.forEach(x=>set.add(x)),remove:(...xs)=>xs.forEach(x=>set.delete(x)),toggle:(x,b)=>b?set.add(x):set.delete(x),contains:x=>set.has(x)};}append(...els){this.children.push(...els)}setAttribute(){}contains(x){return this.children.includes(x)}replaceChildren(){this.children=[];this.replaced=true}}
 const root=new El(),nodes={projectTree:root,treeSearch:{value:''}},notices=[],moves=[],projects=[{id:'a'},{id:'b'},{id:'archive',archived:true}];
 const c={pointerDrag:null,treeDrag:null,dragRefreshPending:false,transferBusy:false,lastDragEnd:0,treeTrash:false,selection:[],activeItem:null,expanded:new Set(),treeData:{projects},Date,document:{createElement:()=>new El(),querySelectorAll:()=>[],getElementById:id=>nodes[id]},$t:id=>nodes[id],project:id=>projects.find(p=>p.id===id),isSelected:t=>c.selection.some(x=>x.id===t.id),nodeButton:()=>new El(),notify:s=>notices.push(s),syncImageAction(){},transfer:async(...args)=>moves.push(args),importFiles:async()=>{},reload:async()=>{}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function itemRow('),source.indexOf('function renderSavedVoices(')),c);vm.runInContext(source.slice(source.indexOf('function render(){'),source.indexOf('async function reload()')),c);
 function event(ctrl=false){const values={};return {ctrlKey:ctrl,preventDefault(){this.prevented=true},stopPropagation(){},dataTransfer:{files:[],types:['application/x-ams-items'],setData:(k,v)=>values[k]=v,getData:k=>values[k]||''}}}
 return {c,El,root,event,notices,moves};
}
test('drag starts from the name button and drops onto expanded collection content',async()=>{
 const {c,El,event,moves}=harness(),parent=new El();c.itemRow(parent,{owner:'a',kind:'images',id:'image',name:'Image'});const row=parent.children[0],button=row.children[0],e=event();assert.equal(button.draggable,false);assert.equal(row.dataset.draggable,'true');button.ondragstart(e);assert.equal(c.treeDrag.items[0].id,'image');
 const destination=new El();c.dropTarget(destination,'b','images');destination.ondragover(e);assert.equal(e.dataTransfer.dropEffect,'move');assert.equal(destination.classList.contains('tree-drop'),true);await destination.ondrop(e);assert.equal(moves.length,1);assert.equal(moves[0][1],'b');assert.equal(moves[0][2],false);assert.equal(c.treeDrag,null);
});
test('Ctrl drop copies and mismatched, archived and same-project destinations reject',async()=>{
 const {c,El,event,moves,notices}=harness();c.treeDrag={items:[{owner:'a',kind:'videos',id:'v',name:'Video'}]};const e=event(true),target=new El();c.dropTarget(target,'b','videos');target.ondragover(e);assert.equal(e.dataTransfer.dropEffect,'copy');await target.ondrop(e);assert.equal(moves[0][2],true);
 for(const [owner,kind]of [['b','images'],['archive','videos'],['a','videos']]){c.treeDrag={items:[{owner:'a',kind:'videos',id:'v'}]};const bad=event();c.dropTarget(target,owner,kind);target.ondragover(bad);assert.equal(bad.dataTransfer.dropEffect,'none');await target.ondrop(bad);}assert.equal(moves.length,1);assert.ok(notices.length>=3);
});
test('progress refresh cannot replace DOM during drag or transfer and renders afterward',()=>{
 const {c,root}=harness();c.treeData.projects=[];c.treeDrag={items:[]};c.render();assert.equal(root.replaced,undefined);assert.equal(c.dragRefreshPending,true);c.endTreeDrag();assert.equal(root.replaced,true);
 root.replaced=false;c.transferBusy=true;c.render();assert.equal(root.replaced,false);c.transferBusy=false;c.endTreeDrag();assert.equal(root.replaced,true);
});
test('unsupported selected jobs are rejected rather than silently moved',()=>{
 const {c,El,event,notices}=harness(),parent=new El(),image={owner:'a',kind:'images',id:'i'};c.selection=[image,{owner:'a',kind:'videos',id:'job',job:true}];c.itemRow(parent,image);const e=event();parent.children[0].ondragstart(e);assert.equal(e.prevented,true);assert.equal(c.treeDrag,null);assert.match(notices.at(-1),/movable/);
});
test('real transfer forwards multi-asset move with required references and opens destination collection',async()=>{
 const {c}=harness(),calls=[];c.confirmTransfer=async()=>true;c.refresh=async()=>{};c.api=async(owner,path,value)=>{calls.push({owner,path,value});return path==='/api/assets/plan'?{assets:[{},{}],bytes:20}:{};};c.project=id=>({name:id});
 vm.runInContext(source.slice(source.indexOf('async function transfer('),source.indexOf('function collectionItems(')),c);
 await c.transfer([{owner:'a',kind:'images',id:'i'},{owner:'a',kind:'videos',id:'v'}],'b',false);assert.equal(calls[1].value.action,'move');assert.deepEqual(Array.from(calls[1].value.id),['i','v']);assert.equal(calls[1].value.include,true);assert.equal(c.expanded.has('b:images'),true);assert.equal(c.expanded.has('b:videos'),true);
});

test('pointer dragging moves a label across projects without native HTML drag events',async()=>{
 const {c,El,moves}=harness(),parent=new El(),target=new El();c.dropTarget(target,'b','images');c.document.elementFromPoint=()=>({closest:()=>target});c.itemRow(parent,{owner:'a',kind:'images',id:'pointer',name:'Pointer image'});const b=parent.children[0].children[0];
 const event={button:0,pointerId:1,clientX:20,clientY:20,preventDefault(){},ctrlKey:false};b.onpointerdown(event);assert.equal(c.treeDrag,null);b.onpointermove({...event,clientY:40});assert.equal(c.treeDrag.items[0].id,'pointer');await b.onpointerup({...event,clientY:200});assert.equal(moves[0][1],'b');assert.equal(c.treeDrag,null);assert.equal(c.pointerDrag,null);
});

test('saved voices drag to Saved voices or Audio and use the voice transfer API',async()=>{
 const {c,El}=harness(),parent=new El();c.itemRow(parent,{owner:'a',kind:'voices',id:'voice',name:'Voice'});assert.equal(parent.children[0].dataset.draggable,'true');assert.equal(c.dropAllowed('b','voices',[{owner:'a',kind:'voices',id:'voice'}]),true);assert.equal(c.dropAllowed('b','audio-root',[{owner:'a',kind:'voices',id:'voice'}]),true);assert.equal(c.dropAllowed('b','images',[{owner:'a',kind:'voices',id:'voice'}]),false);
 const calls=[];c.confirmTransfer=async()=>true;c.refresh=async()=>{};c.api=async(owner,path,value)=>{calls.push({owner,path,value});return {voices:[{source:'voice',id:'new-voice'}]};};c.project=id=>({name:id});vm.runInContext(source.slice(source.indexOf('async function transfer('),source.indexOf('function collectionItems(')),c);await c.transfer([{owner:'a',kind:'voices',id:'voice'}],'b',false);assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/voices/action');assert.equal(calls[0].value.action,'move');assert.equal(c.expanded.has('b:voices'),true);assert.equal(c.expanded.has('b:audio-root'),true);
});
