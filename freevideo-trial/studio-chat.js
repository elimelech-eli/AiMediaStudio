let chatSending=false,chatStopTarget=null,chatPendingScope=null;
async function stopChatReply(){const target=chatStopTarget;if(!target?.request_id)return;const button=$('chatStop');button.disabled=true;try{const r=await workspaceFetch('/api/chat/stop',{method:'POST',headers:{'X-Studio-Token':token,'X-Studio-Workspace':target.owner,'X-Studio-Chat':target.chat,'Content-Type':'application/json'},body:JSON.stringify({request_id:target.request_id})});const value=await r.json();if(!r.ok)throw Error(value.error);$('chatStatus').textContent='Stopping reply…';}catch(error){$('chatStatus').textContent=error.message;button.disabled=false;}}
const chatAttachmentDrafts=new Map();
function chatAttachmentScope(){return currentWorkspace+':'+(window.studioChatId||'legacy');}
function restoreChatAttachments(){const files=chatAttachmentDrafts.get(chatAttachmentScope());$('chatAttachments').value='';if(files)$('chatAttachments').files=files;if(typeof updateChatAttachmentChips==='function')updateChatAttachmentChips();}
$('chatAttachments').onchange=()=>chatAttachmentDrafts.set(chatAttachmentScope(),$('chatAttachments').files);
const chatOldMode=studioMode;
studioMode=function(images){$('chatStudio').hidden=true;$('chatTab').classList.remove('primary');chatOldMode(images);};
const chatOldVoice=$('voiceTab').onclick;
$('voiceTab').onclick=()=>{$('chatStudio').hidden=true;$('chatTab').classList.remove('primary');chatOldVoice();};
$('chatTab').onclick=()=>{location.hash='chat';for(const id of ['videoStudio','imageStudio','voiceStudio'])$(id).hidden=true;for(const id of ['videoTab','imageTab','voiceTab'])$(id).classList.remove('primary');$('chatStudio').hidden=false;$('chatTab').classList.add('primary');loadChat();};
let lastPaintedChat=null,chatLoadEpoch=0;
function paintChat(messages){const scope=chatAttachmentScope();paintStudioChat(messages);if(scope!==lastPaintedChat)$('chatHistory').scrollTop=$('chatHistory').scrollHeight;lastPaintedChat=scope;}

async function loadChat(){const loadEpoch=++chatLoadEpoch;restoreChatAttachments();if(typeof resizeChatComposer==='function')resizeChatComposer();try{const response=await fetch('/api/chat/state'),data=await response.json();if(loadEpoch!==chatLoadEpoch||response.workspace!==currentWorkspace||response.chatIdentity!==window.studioChatId)return;if(chatSending&&chatPendingScope===chatAttachmentScope()&&document.querySelector('#chatHistory .chat-transient'))return;paintChat(data.chat?.messages||[]);$('chatStatus').textContent=data.chat?.busy?'Preparing a local reply…':data.active?'Media generation is active; chat will be available afterward.':'Local history saved on this machine.';}catch(e){$('chatStatus').textContent=e.message;}}
function chatEnterSends(event){return event.key==='Enter'&&!event.shiftKey&&!event.isComposing&&event.keyCode!==229;}
$('chatInput').addEventListener('keydown',event=>{if(chatEnterSends(event)){event.preventDefault();if(!chatSending)$('chatForm').requestSubmit();}});
$('chatAttachmentsClear').onclick=()=>{chatAttachmentDrafts.delete(chatAttachmentScope());$('chatAttachments').value='';};
$('chatForm').onsubmit=async event=>{
 event.preventDefault();if(chatSending)return;
 const owner=currentWorkspace,chatOwner=window.studioChatId,text=$('chatInput').value,mode=$('chatMode').value,files=[...$('chatAttachments').files];
 if(files.length>4){$('chatStatus').textContent='Attach at most four files.';return;}
 chatSending=true;chatPendingScope=chatAttachmentScope();chatStopTarget=null;$('chatSend').disabled=true;if($('chatStop')){$('chatStop').hidden=false;$('chatStop').disabled=true;}showPendingChat(text,files);
 let progressTimer=null,progressBusy=false,progressDone=false;
 const headers={'X-Studio-Token':token,'X-Studio-Workspace':owner,...(chatOwner?{'X-Studio-Chat':chatOwner}:{})};
 try{
  const attachments=[];
  for(const file of files){
   $('chatStatus').textContent='Uploading '+file.name+' locally…';const suffix='.'+file.name.split('.').pop().toLowerCase();
   const kind=['.png','.jpg','.jpeg','.webp'].includes(suffix)?'image':['.mp4','.mov','.webm','.mkv'].includes(suffix)?'video':'document';
   const response=await workspaceFetch('/api/chat/upload',{method:'POST',headers:{...headers,'X-Media-Kind':kind,'X-File-Extension':suffix,'X-Attachment-Name':encodeURIComponent(file.name)},body:file});const output=await response.json();if(!response.ok)throw Error(output.error||'Attachment upload failed');attachments.push({asset:output.asset});
  }
  if(owner!==currentWorkspace||chatOwner!==window.studioChatId)throw Error('Chat changed during upload. Files were saved in the original project; send the message there.');
  $('chatStatus').textContent=files.length?'Reading attachments / thinking locally… Visual analysis can take time.':'Thinking locally…';
  progressTimer=setInterval(async()=>{if(progressBusy)return;progressBusy=true;try{const r=await workspaceFetch('/api/chat/state',{headers,signal:AbortSignal.timeout(3000)});const data=await r.json();if(!progressDone&&data.chat?.busy&&data.chat.request_id){chatStopTarget={owner,chat:chatOwner,request_id:data.chat.request_id};if($('chatStop'))$('chatStop').disabled=false;}if(!progressDone&&r.ok&&owner===currentWorkspace&&chatOwner===window.studioChatId&&data.chat?.busy&&typeof updatePendingChat==='function'){if(!document.querySelector('#chatHistory .chat-pending')){paintChat(data.chat.messages||[]);showPendingChat(text,files);}updatePendingChat(data.chat);}}catch{}finally{progressBusy=false;}},700);
  const response=await workspaceFetch('/api/chat/send',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({text,mode,attachments})});const output=await response.json();if(!response.ok)throw Error(output.error||'Chat failed');
  if(owner===currentWorkspace&&chatOwner===window.studioChatId){chatPendingScope=null;$('chatInput').value='';chatAttachmentDrafts.delete(owner+':'+(chatOwner||'legacy'));$('chatAttachments').value='';clearPendingChat();if(typeof resizeChatComposer==='function')resizeChatComposer();await loadChat();}
 }catch(error){if(owner===currentWorkspace&&chatOwner===window.studioChatId)$('chatStatus').textContent=error.message;}
 finally{progressDone=true;clearInterval(progressTimer);chatStopTarget=null;chatPendingScope=null;if($('chatStop'))$('chatStop').hidden=true;clearPendingChat();chatSending=false;$('chatSend').disabled=false;}
};
$('chatUnload').onclick=async()=>{startupChatWarmup=false;try{await request('/api/chat/unload');$('chatStatus').textContent='Chat model unloaded.';}catch(e){$('chatStatus').textContent=e.message;}};
$('chatClear').onclick=async()=>{if(!confirm('Clear all messages in this conversation?'))return;try{await request('/api/chat/clear');await loadChat();}catch(e){$('chatStatus').textContent=e.message;}};
if(location.hash==='#chat')$('chatTab').onclick();

// Load weights without generating a message or changing any conversation.
let startupChatWarmup=true,chatWarmRequest=false,nextChatWarmRetry=0;
function paintChatRuntime(state){
 let label=document.getElementById('chatModelStatus');if(!label){label=document.createElement('div');label.id='chatModelStatus';label.setAttribute('role','status');label.style='font-size:12px;color:#a5a5b8;padding:8px;overflow-wrap:anywhere';(document.getElementById('projectSidebar')||document.querySelector('header')).append(label);}
 const sidebar=document.getElementById('projectSidebar');if(sidebar&&label.parentElement!==sidebar)sidebar.append(label);
 const mode=state.mode?state.mode.toUpperCase():'';
 label.textContent=state.status==='ready'?'Chat ready · '+mode:state.status==='loading'?'Loading chat model · '+mode+'…':state.status==='replying'?'Chat is responding…':state.status==='deferred'?'Chat loading deferred · '+(state.message||'Waiting for resources'):state.status==='error'?'Chat load failed · '+state.message:'Chat model unloaded';
 if(state.mode){window.studioChatMode=state.mode;$('chatMode').value=state.mode;}
 if(state.status==='ready')startupChatWarmup=false;
 $('chatMode').disabled=state.status==='loading'||state.status==='replying';
 $('chatUnload').disabled=state.status==='loading'||state.status==='replying';
}
async function warmChatAtStartup(){
 if(chatWarmRequest)return;chatWarmRequest=true;nextChatWarmRetry=Date.now()+30000;
 try{const mode=localStorage.getItem('ams-chat-mode');const state=await request('/api/chat/preload',mode?{mode}:{});paintChatRuntime(state);}catch(error){paintChatRuntime({status:'error',message:error.message});startupChatWarmup=false;}finally{chatWarmRequest=false;}
}
async function pollChatRuntime(){try{const response=await workspaceFetch('/api/chat/runtime');if(!response.ok)return;const state=await response.json();paintChatRuntime(state);if(startupChatWarmup&&['deferred','unloaded'].includes(state.status)&&Date.now()>=nextChatWarmRetry)await warmChatAtStartup();}catch{}}
$('chatMode').onchange=()=>{window.studioChatMode=$('chatMode').value;localStorage.setItem('ams-chat-mode',window.studioChatMode);startupChatWarmup=true;warmChatAtStartup();};
window.addEventListener('DOMContentLoaded',()=>{if(new URLSearchParams(location.search).has('no-chat-preload'))return;warmChatAtStartup();setInterval(pollChatRuntime,2500);});
