const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');

test('worker loads without generating text, reuses weights and unloads explicitly',async()=>{

 const requests=[{preload:true,mode:'cpu',model:{id:'selected'}},{mode:'cpu',messages:[{role:'user',content:'Real message'}]},{stop:true}],events=[],output=[];let instance;

 class Model{

  constructor(){instance=this;this.mode='cpu';this.launch=()=>{};this.idle={};}

  async init(){}async selectModel(model){events.push(['select',model?.id]);}async setMode(mode){this.mode=mode;}

  async start(){events.push(['load']);}snapshot(){return {status:'ready',mode:this.mode};}

  async complete(messages,delta){events.push(['reply',messages]);delta('Real answer');}async stop(){events.push(['stop']);}

 }

 const context={AbortController,setInterval,clearInterval,require:name=>name==='./local-conversation.cjs'?{LocalConversation:Model}:name==='node:readline'?{createInterface:()=>({async *[Symbol.asyncIterator](){yield* requests.map(x=>JSON.stringify(x));}})}:require(name),__dirname:__dirname,process:{stdin:{}},console:{log:line=>output.push(JSON.parse(line))},clearTimeout:value=>events.push(['clearIdle',value])};

 await vm.runInNewContext(fs.readFileSync(__dirname+'/studio-chat-worker.cjs','utf8'),context);

 assert.equal(events.filter(x=>x[0]==='load').length,1);assert.equal(events.filter(x=>x[0]==='reply').length,1);assert.equal(output[0].loaded,true);assert.equal(output[1].text,'Real answer');assert.equal(output[2].ok,true);assert.ok(events.some(x=>x[0]==='clearIdle'&&x[1]===instance.idle));

});

const {LocalConversation}=require('./local-conversation.cjs');

test('worker emits progressive text before final answer only when requested',async()=>{
 const output=[];class Model{constructor({notify}){this.notify=notify;this.mode='cpu';this.launch=()=>{};}async init(){}async selectModel(){}async stop(){}async complete(messages,delta){this.notify({status:'loading'});delta('First ');await new Promise(r=>setTimeout(r,100));delta('second');} }
 const context={AbortController,setInterval,clearInterval,require:name=>name==='./local-conversation.cjs'?{LocalConversation:Model}:name==='node:readline'?{createInterface:()=>({async *[Symbol.asyncIterator](){yield JSON.stringify({stream_updates:true,mode:'cpu',messages:[]});}})}:require(name),__dirname,process:{stdin:{}},console:{log:line=>output.push(JSON.parse(line))},clearTimeout};
 await vm.runInNewContext(fs.readFileSync(__dirname+'/studio-chat-worker.cjs','utf8'),context);
 assert.ok(output.some(row=>row.event==='phase'&&row.phase==='Loading local model'));assert.equal(output.filter(row=>row.event==='delta').map(row=>row.text).join(''),'First second');assert.equal(output.at(-1).text,'First second');assert.ok(!output.at(-1).event);
});

test('selected writing model supplies its own name and template without changing Hermes fallback',async()=>{

 const os=require('node:os'),path=require('node:path'),fsp=require('node:fs/promises');

 const root=await fsp.mkdtemp(path.join(__dirname,'tmp','rocinante-'));

 try{

  const file=path.join(root,'rocinante.gguf');await fsp.writeFile(file,'GGUF');

  const model=new LocalConversation({project:root});

  assert.equal(model.chatTemplate,'chatml');

  await model.selectModel({verified:true,path:file,bytes:4,name:'Rocinante-X 12B',chat_template:'embedded',gpu_mib:9500});

  assert.equal(model.snapshot().model,'Rocinante-X 12B');assert.equal(model.chatTemplate,'embedded');assert.equal(model.gpuMinMiB,9500);

  const bad=path.join(root,'bad.gguf');await fsp.writeFile(bad,'GGUF');await assert.rejects(model.selectModel({verified:true,path:bad,bytes:99}),/size changed/);

 }finally{await fsp.rm(root,{recursive:true,force:true});}

});

