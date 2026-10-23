const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(jobs){
 class El{constructor(){this.children=[];this.dataset={};this.hidden=false;this.textContent='';}prepend(...items){this.children.unshift(...items)}append(...items){for(const item of items)item.parentElement=this;this.children.push(...items)}replaceChildren(){this.children=[]}setAttribute(k,v){this[k]=v}removeAttribute(k){delete this[k]}querySelectorAll(selector){return this.children.flatMap(c=>[...(c.className===selector.slice(1)?[c]:[]),...c.querySelectorAll(selector)])}}
 const main=new El(),head=new El(),footer=new El(),controls=new El(),requests=[];for(const id of ['cancel','imageCancel','voiceCancel','message','imageError','voiceError']){const el=new El();el.id=id;controls.append(el);}const find=(parent,id)=>parent.id===id?parent:parent.children.map(c=>find(c,id)).find(Boolean);const classes=new Set(),intervals=[];let open;
 const context=vm.createContext({document:{getElementById:id=>find(controls,id),createElement:()=>new El(),head,querySelector:s=>s==='main'?main:footer,body:{classList:{add:c=>classes.add(c),remove:c=>classes.delete(c)}}},window:{addEventListener:(_,fn)=>{open=fn},StudioSettings:{open(){},close(){}}},show(){},renderImages(){},renderVoices(){},refresh:async()=>{},token:'test',AbortSignal,Date,confirm:()=>false,setInterval:(fn,ms)=>intervals.push({fn,ms}),workspaceFetch:async(url,options)=>{if(options?.body)requests.push(JSON.parse(options.body));return {ok:true,json:async()=>url==='/api/state'?{jobs:[{id:'run',phase:'Encoding reference and prompt: image encoder',progress:null}]}:{checkpoint_support:true,paused:false,revision:1,jobs}}}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'studio-queue.js'),'utf8'),context);open();context.StudioQueue=context.window.StudioQueue;context.window.StudioQueue.open();return {main,intervals,context,controls,find,requests};
}
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve()};
test('queue renders compact live stages and ticking elapsed time without changing workspace',async()=>{
 const rows=[{id:'run',status:'running',engine:'video',name:'Test video',workspace:'project-a',project:'Project A',started:Date.now()/1000-65}];const {main,intervals}=harness(rows);await settle();
 assert.match(main.querySelectorAll('.queue-stage')[0].textContent,/Encoding reference/);assert.match(main.querySelectorAll('.queue-time')[0].textContent,/1:0[5-9]/);assert.equal(main.querySelectorAll('.queue-row is-active').length,1);assert.equal(intervals.find(i=>i.ms===1000).fn.name,'updateTimers');
 rows[0].started-=5;intervals.find(i=>i.ms===1000).fn();assert.match(main.querySelectorAll('.queue-time')[0].textContent,/1:1[0-4]/);
});
test('finished duration stays fixed and pending rows have no generation timer',async()=>{
 const {main,intervals}=harness([{id:'done',status:'completed',engine:'image',name:'Still',project:'A',started:100,finished:170},{id:'pending',status:'queued',engine:'voice',name:'Voice',project:'B'}]);await settle();const times=main.querySelectorAll('.queue-time');assert.deepEqual(times.map(t=>t.textContent),['','1:10']);intervals.find(i=>i.ms===1000).fn();assert.equal(times[1].textContent,'1:10');
});

test('paused jobs show STP and Continue while saving jobs cannot continue',async()=>{
 const {main}=harness([{id:'paused',status:'paused',engine:'image',name:'Still',project:'A',started:100,finished:170,elapsed:70},{id:'saving',status:'pausing',engine:'voice',name:'Audio',project:'B',started:Date.now()/1000}]);await settle();
 assert.ok(main.querySelectorAll('.job-badge').some(b=>b.textContent==='STP'));
 const all=(el)=>[el,...el.children.flatMap(all)];assert.ok(all(main).some(b=>b.textContent==='Continue'));assert.ok(all(main).some(b=>b.textContent==='Saving…'&&b.disabled));
});
test('work-screen controls track selected video image and audio jobs',async()=>{
 const {context,controls,find,requests}=harness([]);await settle();context.row={id:'selected-video',status:'running',settings:{}};vm.runInContext('show(row)',context);assert.equal(find(controls,'videoCheckpoint').textContent,'Pause');await find(controls,'videoCheckpoint').onclick();assert.equal(requests[0].action,'pause');assert.equal(requests[0].id,'selected-video');
 context.row.status='paused';vm.runInContext('show(row)',context);assert.equal(find(controls,'videoCheckpoint').textContent,'Continue');await find(controls,'videoCheckpoint').onclick();assert.equal(requests[1].action,'resume');
 context.row.status='pausing';vm.runInContext('show(row)',context);assert.equal(find(controls,'videoCheckpoint').disabled,true);
 context.imageSelected='image';context.selectedVoiceJob='audio';context.value={images:[{id:'image',status:'paused',settings:{}}],voices:{jobs:[{id:'audio',status:'running',settings:{}}]}};vm.runInContext('renderImages(value);renderVoices(value)',context);assert.equal(find(controls,'imageCheckpoint').textContent,'Continue');assert.equal(find(controls,'voiceCheckpoint').textContent,'Pause');
 context.row.status='completed';vm.runInContext('show(row)',context);assert.equal(find(controls,'videoCheckpoint').hidden,true);
});
