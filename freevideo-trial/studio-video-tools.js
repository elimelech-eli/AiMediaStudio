let videoRows=[],videoIdentity=null,capturedFrame=null,pendingJoinedJob=null;
function inheritConsistency(id){const settings=videoRows.find(job=>job.id===id)?.settings||{};$('appearance').value=settings.appearance||'';if($('videoAudio'))$('videoAudio').value=settings.audio_mode||'generated';videoIdentity=settings.identity_image||settings.image||null;$('identityImage').value='';$('identityMode').checked=!!settings.identity_mode;$('identityName').textContent=videoIdentity?'Inherited identity reference: '+videoIdentity:'No identity reference selected.';}
$('identityImage').onchange=()=>{videoIdentity=null;$('identityName').textContent=$('identityImage').files[0]?.name||'No identity reference selected.';};
$('clearIdentity').onclick=()=>{videoIdentity=null;$('identityImage').value='';$('identityMode').checked=false;$('appearance').value='';$('identityName').textContent='No identity reference selected.';};
$('captureFrame').onclick=async()=>{try{$('captureFrame').disabled=true;const result=await request('/api/frame',{id:selected});capturedFrame=result.image;$('frameDownload').href=mediaURL('/image/'+capturedFrame);$('frameDownload').download=selected+'-last-frame.png';$('frameDownload').hidden=false;$('frameUse').hidden=false;}catch(error){$('message').textContent=error.message;}finally{$('captureFrame').disabled=false;}};
$('frameUse').onclick=()=>{if(!capturedFrame)return;clearContinuation();imageChoice=capturedFrame;$('image').value='';$('reference').value='';$('imageName').textContent='Captured final frame selected. Enter the next motion prompt.';$('prompt').focus();};
$('joinVideos').onclick=async()=>{try{$('joinVideos').disabled=true;$('joinMessage').textContent='Preparing clips…';const clips=[];for(const [selectId,fileId,chain]of [['joinBase','joinBaseFile',true],['joinAppend','joinAppendFile',false]]){const file=$(fileId).files[0];if(file)clips.push({kind:'upload',id:await upload(file,'video')});else{if(!$(selectId).value)throw Error('Select a base video and a clip to append.');clips.push({kind:'job',id:$(selectId).value,chain});}}const job=await request('/api/join',{clips});selected=job.id;pendingJoinedJob=job.id;previewChoice='chain';$('joinMessage').textContent='Joining locally. The result will appear in Recent creations.';await refresh();}catch(error){$('joinMessage').textContent=error.message;}finally{$('joinVideos').disabled=false;}};
function renderVideoTools(data){videoRows=data.jobs||[];if(pendingJoinedJob){const joined=videoRows.find(job=>job.id===pendingJoinedJob);if(joined?.status==='completed'){selected=joined.id;previewChoice='chain';pendingJoinedJob=null;$('joinMessage').textContent='Joined video ready. Preview shows the full chain.';}else if(joined?.status==='failed'){pendingJoinedJob=null;$('joinMessage').textContent=joined.message||'Joining failed.';}}const completed=videoRows.filter(job=>job.status==='completed');for(const id of ['joinBase','joinAppend']){const field=$(id),previous=field.value;field.replaceChildren();for(const job of completed){const option=document.createElement('option');option.value=job.id;option.textContent=`${job.id} · ${job.settings.prompt.slice(0,55)}${id==='joinBase'&&job.combined?' · whole chain':''}`;field.append(option);}if(completed.some(job=>job.id===previous))field.value=previous;else if(id==='joinAppend'&&completed.some(job=>job.id===selected))field.value=selected;}$('joinVideos').disabled=!!data.active;$('captureFrame').disabled=!!data.active;}
$('previewMode').onchange=()=>{previewChoice=$('previewMode').value;const job=videoRows.find(job=>job.id===selected);if(job)show(job);};

// Workspace layouts reuse the exact same nodes: switching never reloads or resets a job/form.
function initStudioViews(){
 const main=document.querySelector('main'),picker=document.getElementById('workspaceView');
 if(!main||!picker)return;
 const sections=[['videoStudio','jobs'],['imageStudio','imageHistory'],['voiceStudio','voiceHistory']];
 for(const [id,historyId] of sections){
  const section=document.getElementById(id),panels=[...section.children].filter(n=>n.classList.contains('panel'));
  if(panels.length!==2)continue;
  panels[0].classList.add('workspace-controls');panels[1].classList.add('workspace-preview');
  const list=document.getElementById(historyId),media=document.createElement('section');media.className='panel workspace-media';
  const heading=id==='videoStudio'?document.querySelector('#history h2'):list.previousElementSibling;
  if(heading?.tagName==='H2')media.append(heading);
  media.append(list);section.append(media);
  if(id==='videoStudio')document.getElementById('history').remove();
 }
 const allowed=['desk','library','director'];let current='desk',lastChatState='';
 try{const saved=localStorage.getItem('ams-workspace-view');if(allowed.includes(saved))current=saved;}catch{}
 function sync(){
  const engine=location.hash.replace('#','')||'video';main.dataset.view=current;main.dataset.engine=engine;picker.value=current;
  const chat=document.getElementById('chatStudio'),show=engine==='chat'||(!window.studioTree&&current==='director');
  if(chat.hidden===show)chat.hidden=!show;
  // Opening a dock should reveal existing history without clearing the message draft.
  const state=current+':'+engine;if(show&&lastChatState!==state&&typeof loadChat==='function')loadChat();lastChatState=state;
 }
 picker.onchange=()=>{if(!allowed.includes(picker.value))return;current=picker.value;try{localStorage.setItem('ams-workspace-view',current);}catch{}sync();};
 window.addEventListener('hashchange',sync);
 // Engine helpers also select tabs programmatically (e.g. image -> video).
 const observer=new MutationObserver(sync);observer.observe(document.getElementById('chatStudio'),{attributes:true,attributeFilter:['hidden']});
 sync();
}
if(typeof window!=='undefined')window.addEventListener('DOMContentLoaded',initStudioViews);
