const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'studio.html'),'utf8'),inline=html.split('<script>')[1].split('</script>')[0],tools=fs.readFileSync(path.join(__dirname,'studio-video-tools.js'),'utf8');
function harness(){
 const nodes={};for(const [,id] of html.matchAll(/id="([^"]+)"/g))nodes[id]={value:'',src:'',files:[],hidden:false,disabled:false,textContent:'',append(){},removeAttribute(){},replaceChildren(){this.value='';},focus(){}};
 const context=vm.createContext({nodes,location:{hash:'#video'},document:{createElement:()=>({style:{},append(){},setAttribute(){}})}});
 vm.runInContext("const $=id=>nodes[id];let selected=null,lastShown=null,previewChoice='chain',uploading=false;function mediaURL(p){return p}function duration(s){return String(s)}function readableFailure(s){return s}function clearContinuation(){}",context);
 vm.runInContext(inline.slice(inline.indexOf('function show(job)'),inline.indexOf('async function refresh()')),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'studio-admin.js'),'utf8'),context);vm.runInContext(tools,context);return {context,nodes};
}
const clip=(id,combined=true)=>({id,status:'completed',combined,settings:{resolution:[640,576],seconds:15,quality:'high',seed:1,prompt:'Neutral test scene'}});
test('joined preview defaults to full chain, respects segment selection and resets for a new job',()=>{
 const {context,nodes}=harness();context.a=clip('a');context.b=clip('b');
 vm.runInContext('renderVideoTools({jobs:[a,b],active:null});show(a)',context);assert.equal(nodes.player.src,'/combined/a');
 nodes.previewMode.value='segment';vm.runInContext("$('previewMode').onchange();show(a)",context);assert.equal(nodes.player.src,'/video/a');
 vm.runInContext('show(b)',context);assert.equal(nodes.player.src,'/combined/b');
 assert.equal(nodes.download.href,'/video/b');assert.equal(nodes.combinedDownload.href,'/combined/b');
});
test('completed attachment focuses the assembled chain and presets are generic',()=>{
 const {context,nodes}=harness();context.a=clip('a');context.b=clip('joined');context.b.settings.joined_from=[{id:'a'}];
 vm.runInContext("show(a);pendingJoinedJob='joined';renderVideoTools({jobs:[a,b],active:null});show(videoRows.find(j=>j.id===selected))",context);
 assert.equal(nodes.player.src,'/combined/joined');assert.equal(nodes.previewMode.hidden,true);
 assert.match(nodes.joinMessage.textContent,/full chain/);
 assert.ok(!html.includes('approvedIdentity'));assert.ok(!tools.includes('Adult Lexi'));
});
test('audio preview and submitted script follow full-chain or segment selection',()=>{
 const {context,nodes}=harness();
 vm.runInContext(fs.readFileSync(path.join(__dirname,'studio-voice.js'),'utf8'),context);
 context.voiceData={active:null,voices:{active:null,profiles:[],jobs:[{id:'voice',status:'completed',combined:true,seconds:5,combined_seconds:12,combined_text:'First clip. Second clip.',settings:{action:'read',text:'Second clip.',profile:'profile'}}]}};
 vm.runInContext('function refresh(){renderVoices(voiceData)};renderVoices(voiceData)',context);
 assert.equal(nodes.voicePlayer.src,'/audio-chain/voice');assert.equal(nodes.voiceSourceText.textContent,'First clip. Second clip.');
 nodes.voicePreviewMode.value='segment';vm.runInContext("$('voicePreviewMode').onchange()",context);
 assert.equal(nodes.voicePlayer.src,'/audio/voice');assert.equal(nodes.voiceSourceText.textContent,'Second clip.');
});
test('delete controls block active jobs and cancelled confirmation never sends a request',async()=>{
 const {context}=harness();context.confirm=()=>false;context.request=()=>{throw Error('Unexpected deletion request');};context.a=clip('a');
 const button=vm.runInContext("deleteMediaButton('video',a,false)",context);assert.equal(button.disabled,false);await button.onclick();
 assert.equal(vm.runInContext("deleteMediaButton('video',a,true).disabled",context),true);
 context.a.status='running';assert.equal(vm.runInContext("deleteMediaButton('video',a,false).disabled",context),true);
});

test('unloading the local model waits for its owned worker to exit',async()=>{
 const {spawn}=require('node:child_process');const {once}=require('node:events');const {LocalConversation}=require('./local-conversation.cjs');
 const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{windowsHide:true,stdio:'ignore'});await once(child,'spawn');let closed=false;child.once('close',()=>closed=true);const model=new LocalConversation({project:path.resolve(__dirname,'..')});model.child=child;model.status='ready';await model.stop();assert.equal(closed,true);assert.equal(model.snapshot().status,'unloaded');assert.equal(model.child,null);
});
