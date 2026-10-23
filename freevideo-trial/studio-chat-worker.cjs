const {LocalConversation}=require('./local-conversation.cjs');
const readline=require('node:readline'),path=require('node:path');
(async()=>{
 let updates=false;const emit=row=>console.log(JSON.stringify(row));
 const model=new LocalConversation({project:path.resolve(__dirname,'..'),notify:state=>{if(updates)emit({event:'phase',phase:state.status==='loading'?'Loading local model':state.status==='replying'?'Writing reply':'Preparing context'});}});
 model.dir=path.join(__dirname,'studio-data','chat-runtime');model.base='http://127.0.0.1:57848';
 const original=model.launch;model.launch=(exe,args,options)=>{args[args.indexOf('--port')+1]='57848';return original(exe,args,options);};
 await model.init();let keepLoaded=false;
 for await(const line of readline.createInterface({input:process.stdin})){
  try{const request=JSON.parse(line);updates=request.stream_updates===true;if(request.stop){keepLoaded=false;await model.stop();console.log(JSON.stringify({ok:true}));continue;}
   let observations='';if(updates)emit({event:'phase',phase:request.visual?.length?'Analyzing attachments':'Preparing local model'});
   if(request.visual?.length){
    await model.selectModel(request.vision_model);if(model.mode!=='cpu')await model.setMode('cpu');await model.start();
    for(const item of request.visual){
     const response=await model.api('/v1/chat/completions',{model:'hermes3-local',messages:[{role:'user',content:[{type:'text',text:'Describe literal visible shapes, colors, people, objects, actions and readable text. Do not infer why the image exists, its source, signal failure, corruption, missing content or events outside the image. Clearly label uncertainty.'},{type:'image_url',image_url:{url:item.url}}]}],max_tokens:300,temperature:0.2});
     if(!response.ok)throw Error('Local vision analysis failed: HTTP '+response.status);const result=await response.json();observations+=item.label+': '+(result.choices?.[0]?.message?.content||'No reliable description')+'\n';
    }
    request.messages[request.messages.length-1].content+='\n\n<visual-observations>Local vision model observations (fallible; do not invent missing details):\n'+observations+'\n</visual-observations>';
   }
   await model.selectModel(request.model);
   if(request.mode!==model.mode)await model.setMode(request.mode);
   if(request.preload){await model.start();keepLoaded=true;console.log(JSON.stringify({loaded:true,...model.snapshot()}));continue;}
   const controller=new AbortController(),cancelPath=/^[a-f0-9]{32}$/.test(request.request_id||'')?path.join(model.dir,'cancel-'+request.request_id):null;const timer=cancelPath?setInterval(()=>{if(require('node:fs').existsSync(cancelPath))controller.abort();},100):null;
   let stopped=false;let reply='',buffer='',last=0;const flush=()=>{if(buffer){emit({event:'delta',text:buffer});buffer='';last=Date.now();}};try{await model.complete(request.messages,delta=>{reply+=delta;if(updates){buffer+=delta;if(Date.now()-last>=80||buffer.length>=100)flush();}},controller.signal);}catch(error){if(controller.signal.aborted)stopped=true;else throw error;}finally{clearInterval(timer);if(cancelPath)require('node:fs').rmSync(cancelPath,{force:true});}if(updates)flush();if(keepLoaded)clearTimeout(model.idle);console.log(JSON.stringify({text:reply,stopped,runtime_status:model.snapshot?.().status||'ready',...(observations?{observations}:{})}));
  }catch(error){console.log(JSON.stringify({error:error.message}));}
 }
 await model.stop();
})();
