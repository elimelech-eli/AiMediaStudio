const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto'),os=require('node:os');

const {spawn}=require('node:child_process');

const MODEL='Hermes-3-Llama-3.1-8B.Q4_K_M.gguf';

class ToolText{

 constructor(emit=()=>{}){this.emit=emit;this.buffer='';this.tool=false;this.calls=[];this.raw='';this.text='';}

 push(delta,final=false){this.raw+=delta;this.buffer+=delta;while(this.buffer){if(this.tool){const end=this.buffer.indexOf('</tool_call>');if(end<0){if(final)throw Error('Incomplete local tool call');break;}const raw=this.buffer.slice(0,end);this.buffer=this.buffer.slice(end+12);this.tool=false;let call;try{call=JSON.parse(raw);}catch{throw Error('Local model returned invalid tool JSON');}if(typeof call.name!=='string'||!call.arguments||typeof call.arguments!=='object')throw Error('Invalid local tool call');this.calls.push(call);}else{const start=this.buffer.indexOf('<tool_call>');if(start>=0){this.output(this.buffer.slice(0,start));this.buffer=this.buffer.slice(start+11);this.tool=true;continue;}let keep=0;if(!final)for(let n=1;n<Math.min(11,this.buffer.length+1);n++)if('<tool_call>'.startsWith(this.buffer.slice(-n)))keep=n;this.output(this.buffer.slice(0,this.buffer.length-keep));this.buffer=this.buffer.slice(this.buffer.length-keep);break;}}}

 output(value){if(value){this.text+=value;this.emit(value);}}

}

async function parseStream(body,onDelta){const reader=body.getReader(),decoder=new TextDecoder();let buffer='',finished=false,reason='stop';try{while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value,{stream:!done});buffer=buffer.replace(/\r\n/g,'\n');let index;while((index=buffer.indexOf('\n\n'))>=0){const block=buffer.slice(0,index);buffer=buffer.slice(index+2);for(const line of block.split('\n'))if(line.startsWith('data:')){const raw=line.slice(5).trim();if(raw==='[DONE]'){finished=true;continue;}if(!raw)continue;const row=JSON.parse(raw);if(row.error)throw Error(row.error.message||'Local inference failed');const choice=row.choices?.[0];if(choice?.delta?.content)onDelta(choice.delta.content);if(choice?.finish_reason==='length'){finished=true;reason='length';}if(choice?.finish_reason==='stop')finished=true;}}if(done)break;}if(!finished)throw Error('Local reply stream ended early');return reason;}finally{reader.releaseLock();}}

class LocalConversation{

 constructor({project=path.join(__dirname,'..'),notify=()=>{},launch=spawn,memory=()=>os.freemem()}={}){this.root=path.join(project,'conversation-engine');this.dir=path.join(project,'desktop/data/local-conversation');this.notify=notify;this.launch=launch;this.memory=memory;this.mode='cpu';this.installed=false;this.child=null;this.starting=null;this.status='unloaded';this.epoch=0;this.serial=Promise.resolve();this.modelPath=path.join(this.root,'models',MODEL);this.modelName='Hermes 3 · Llama 3.1 8B · Q4_K_M';this.chatTemplate='chatml';this.gpuMinMiB=5500;this.key=crypto.randomBytes(32).toString('hex');this.base='http://127.0.0.1:57847';}

 async init(){await fs.mkdir(this.dir,{recursive:true});await fs.mkdir(path.join(this.root,'tmp'),{recursive:true});try{const s=JSON.parse(await fs.readFile(path.join(this.dir,'settings.json'),'utf8'));if(['cpu','gpu'].includes(s.mode))this.mode=s.mode;}catch(e){if(e.code!=='ENOENT')throw e;}try{const manifest=JSON.parse(await fs.readFile(path.join(this.root,'installation.json'),'utf8'));const info=await fs.stat(path.join(this.root,'models',MODEL));this.installed=manifest.verified===true&&info.size===4920733824;await fs.access(path.join(this.root,'runtime',this.mode==='gpu'?'cuda':'cpu','llama-server.exe'));}catch{this.installed=false;}return this;}

 snapshot(){return {installed:this.installed,mode:this.mode,status:this.status,model:this.modelName,local:true};}

 update(status){this.status=status;this.notify(this.snapshot());}

 async selectModel(value){if(!value)return;if(!value.verified||typeof value.path!=='string'||!value.path.endsWith('.gguf'))throw Error('Model must be an installed verified GGUF');const selected=path.resolve(value.path),project=path.resolve(this.root,'..')+path.sep;if(!selected.startsWith(project))throw Error('Model path is outside the project');if(selected!==this.modelPath){await this.stop();const info=await fs.stat(selected);if(value.bytes&&info.size!==value.bytes)throw Error('Selected model size changed');this.modelPath=selected;this.gpuMinMiB=value.gpu_mib||5500;this.installed=true;}this.modelName=value.name||path.basename(selected);this.chatTemplate=value.chat_template||'chatml';this.projector=value.projector||null;}

 async setMode(value){if(!['cpu','gpu'].includes(value))throw Error('Invalid local model resource mode');await this.stop();this.mode=value;await fs.writeFile(path.join(this.dir,'settings.json'),JSON.stringify({mode:value}));return this.snapshot();}

 async resourceCheck(){try{const r=await fetch('http://127.0.0.1:57846/api/state',{signal:AbortSignal.timeout(1200)});if(r.ok&&(await r.json()).active)throw Error('FreeVideo is rendering. Finish the render before loading the chat model; both need substantial RAM.');}catch(e){if(e.message.startsWith('FreeVideo'))throw e;}if(this.memory()<8*1024**3)throw Error('The chat model needs more free memory. Free at least 8 GB RAM before loading it.');if(this.mode==='gpu'){const {execFile}=require('node:child_process'),{promisify}=require('node:util');try{const {stdout}=await promisify(execFile)('nvidia-smi',['--query-gpu=memory.total,memory.used,utilization.gpu','--format=csv,noheader,nounits'],{windowsHide:true,timeout:5000});const [total,memory,util]=stdout.trim().split(/[\s,]+/).map(Number);if(!Number.isFinite(total)||total-memory<this.gpuMinMiB||util>30)throw Error('GPU is busy. Use CPU mode or unload other GPU models first.');}catch(e){throw Error(e.message.startsWith('GPU is busy')?e.message:'Could not verify that the GPU is free. Use CPU mode.');}}}

 async start(signal){clearTimeout(this.idle);if(this.child&&this.status==='ready'){try{const r=await fetch('http://127.0.0.1:57846/api/state',{signal:AbortSignal.timeout(1200)});if(r.ok&&(await r.json()).active){await this.stop();throw Error('FreeVideo is rendering. The chat model has been unloaded to release its memory.');}}catch(e){if(e.message.startsWith('FreeVideo'))throw e;}return;}if(this.starting)return this.starting;const epoch=this.epoch;this.starting=this.startWorker(signal,epoch).finally(()=>{if(epoch===this.epoch)this.starting=null;});return this.starting;}

 async startWorker(signal,epoch){if(!this.installed)throw Error('Chat model installation is not finished.');await this.resourceCheck();if(signal?.aborted||epoch!==this.epoch)throw Error('Local model loading cancelled');this.update('loading');

  const exe=path.join(this.root,'runtime',this.mode==='gpu'?'cuda':'cpu','llama-server.exe');

  const args=['--model',this.modelPath,'--alias','hermes3-local','--host','127.0.0.1','--port','57847','--ctx-size','8192','--parallel','1','--threads','4','--threads-batch','4','--gpu-layers',this.mode==='gpu'?'99':'0','--api-key',this.key,'--no-webui'];

  if(this.projector)args.push('--mmproj',this.projector,'--no-mmproj-offload','--image-max-tokens','1024');

  if(this.chatTemplate!=='embedded')args.push('--chat-template',this.chatTemplate);

  if(this.mode==='gpu')args.push('--flash-attn','on','--cache-type-k','q8_0','--cache-type-v','q8_0','--batch-size','256','--ubatch-size','256');

  const child=this.launch(exe,args,{cwd:this.root,windowsHide:true,shell:false,stdio:['ignore','pipe','pipe'],env:{...process.env,TEMP:path.join(this.root,'tmp'),TMP:path.join(this.root,'tmp')}});this.child=child;let log='',failure;

  const append=data=>{log=(log+data.toString().split(this.key).join('[redacted]')).slice(-16000);};child.stdout.on('data',append);child.stderr.on('data',append);child.on('error',error=>{failure=error;});child.once('close',()=>{if(this.child===child){this.child=null;this.update('unloaded');}fs.writeFile(path.join(this.dir,'worker.log'),log).catch(()=>{});});

  const deadline=Date.now()+180000;

  try{while(Date.now()<deadline){if(signal?.aborted||epoch!==this.epoch)throw Error('Local model loading cancelled');if(failure)throw failure;if(child.exitCode!==null)throw Error('Local runtime stopped; see freevideo-trial/studio-data/chat-runtime/worker.log');try{const r=await this.api('/health',undefined,signal?AbortSignal.any([signal,AbortSignal.timeout(2000)]):AbortSignal.timeout(2000));if(r.ok){const models=await this.api('/v1/models',undefined,AbortSignal.timeout(2000));if(models.ok&&(await models.json()).data?.some(m=>m.id==='hermes3-local')){this.update('ready');return;}}}catch{}await new Promise(resolve=>setTimeout(resolve,250));}throw Error('Local model startup timed out');}catch(e){await this.stop();throw e;}

 }

 api(route,body,signal){const timeout=route==='/v1/chat/completions'&&this.mode==='cpu'?600000:180000;return fetch(this.base+route,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+this.key,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:signal?AbortSignal.any([signal,AbortSignal.timeout(timeout)]):AbortSignal.timeout(timeout)});}

 async fit(messages,signal,keepLast=1,limit=7000){const copy=messages.map(m=>({...m}));for(;;){const rendered=await this.api('/apply-template',{messages:copy},signal);if(!rendered.ok)throw Error('Local chat template could not be applied');const {prompt}=await rendered.json();const r=await this.api('/tokenize',{content:prompt,add_special:true},signal);if(!r.ok)throw Error('Local context could not be counted');const count=(await r.json()).tokens.length;if(count<=limit)return copy;if(copy.length<=keepLast+1)throw Error('Behavior instructions, attachments and current message exceed the local context limit. Shorten an instruction layer, the attachments or the message.');copy.splice(1,Math.min(2,copy.length-1-keepLast));}}

 async complete(messages,onDelta,signal){
  await this.start(signal);const base=await this.fit(messages,signal);let fitted=base,answer='';this.update('replying');
  try{for(;;){let segment='';const r=await this.api('/v1/chat/completions',{model:'hermes3-local',messages:fitted,stream:true,max_tokens:768,temperature:.65,top_p:.9},signal);if(!r.ok)throw Error('Local model returned HTTP '+r.status);
   const reason=await parseStream(r.body,delta=>{segment+=delta;answer+=delta;onDelta(delta)});
   if(reason!=='length'||!segment.trim())return;
   signal?.throwIfAborted();
   // Roll the recent answer forward instead of requiring the full output to fit
   // in the model context. Conversation history is unchanged until final save.
   const inFence=((answer.match(/```/g)||[]).length%2)===1;
   const continuation={role:'user',content:inFence?'Continue exactly from the cutoff inside the fenced block, preserving its syntax. Do not restart the block, repeat content, add commentary, or add unescaped newlines inside strings. Finish naturally.':'Continue the same answer from where it stopped. Start a new paragraph. Do not repeat or restart. Finish naturally when the answer is complete.'};
   let carry=answer.slice(-6000);for(;;){try{fitted=await this.fit([...base,{role:'assistant',content:carry},continuation],signal,3,7300);break;}catch(error){if(!carry||!error.message.includes('exceed the local context limit'))throw error;carry=carry.slice(Math.ceil(carry.length/2));}}
   if(!inFence){answer+='\n\n';onDelta('\n\n');}
  }}finally{if(this.child){this.update('ready');this.idle=setTimeout(()=>this.stop().catch(()=>{}),300000);this.idle.unref();}}
 }

 async stop(){++this.epoch;clearTimeout(this.idle);const child=this.child;this.child=null;this.starting=null;if(child){await new Promise(resolve=>{let done=false;const finish=()=>{if(done)return;done=true;clearTimeout(timer);resolve();};const timer=setTimeout(finish,5000);timer.unref();child.once('close',finish);child.kill();if(child.exitCode!==null)finish();});}this.update('unloaded');return this.snapshot();}

}

module.exports={LocalConversation,ToolText,parseStream};

