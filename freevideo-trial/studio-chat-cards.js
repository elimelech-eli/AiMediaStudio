/* Internal tool JSON is rendered as a readable, resumable creation request. */
const chatCreationEntries=new Map();
function parseStudioReply(content){
 const proposals=[];let invalid=false;
 function accept(raw){try{const value=JSON.parse(raw);if(['image','video','voice'].includes(value.engine)&&value.settings&&typeof value.settings==='object'&&!Array.isArray(value.settings)){proposals.push(value);return true;}}catch{}return false;}
 let text=content.replace(/```(studio|json)\s*([\s\S]*?)```/g,(block,tag,raw)=>{if(accept(raw))return '';if(tag==='studio'){invalid=true;return '';}return block;});
 const unfinished=text.indexOf('```studio');if(unfinished>=0){const raw=text.slice(unfinished+9).trim();if(!accept(raw))invalid=true;text=text.slice(0,unfinished);}
 if(!proposals.length&&accept(text.trim()))text='';
 return {text:text.trim(),proposals,invalid};
}
function creationKey(owner,chat,proposal){let hash=2166136261;const value=JSON.stringify(proposal);for(const char of value)hash=Math.imul(hash^char.charCodeAt(0),16777619);return 'ams-creation-'+owner+'-'+(chat||'legacy')+'-'+(hash>>>0).toString(16);}
function saveCreation(key,entry){try{localStorage.setItem(key,JSON.stringify({job:entry.job,engine:entry.proposal.engine}));}catch{}}
function creationError(message){if(/WinError 5|Access is denied|PermissionError/i.test(message))return 'Windows blocked a job file. See Activity & logs for details.';if(/context.*changed|context revision|stale/i.test(message))return 'Project context changed. Review this request in the editor before creating it.';return message;}
function paintStudioChat(messages){
 const root=$('chatHistory'),stick=root.scrollHeight-root.scrollTop-root.clientHeight<100;root.replaceChildren();
 if(!messages.length){const welcome=document.createElement('div');welcome.className='chat-welcome';const title=document.createElement('h2');title.textContent='What are we making?';const intro=document.createElement('p');intro.textContent='Write, explore an idea, or attach a file to talk it through.';welcome.append(title,intro);root.append(welcome);}
 for(const message of messages){
  const box=document.createElement('div');box.className='chat-message '+(message.role==='user'?'chat-user':'chat-assistant');box.style='margin:20px 0;white-space:pre-wrap;overflow-wrap:anywhere';const label=document.createElement('strong');label.textContent=message.role==='user'?'You\n':'Assistant\n';box.append(label);
  const parsed=message.role==='assistant'?parseStudioReply(message.content):{text:message.display_text??message.content,proposals:[]};if(parsed.text)box.append(typeof renderChatRichText==='function'?renderChatRichText(parsed.text):document.createTextNode(parsed.text));
  if(message.attachments?.length){const attachments=document.createElement('p');attachments.className='hint';attachments.textContent='Attached: '+message.attachments.map(item=>item.name).join(', ');box.append(attachments);}
  if(message.stopped){const stopped=document.createElement('p');stopped.className='hint';stopped.textContent='Stopped · Partial response saved';box.append(stopped);}
  if(message.analysis_limits?.length){const limits=document.createElement('p');limits.className='hint';limits.textContent=[...new Set(message.analysis_limits)].join(' ');box.append(limits);}
  if(parsed.invalid){const error=document.createElement('p');error.textContent='I couldn’t prepare that creation request. Ask me to try again.';box.append(error);}
  for(const proposal of parsed.proposals)box.append(creationCard(proposal,currentWorkspace,window.studioChatId));if(message.role==='assistant'){const copy=document.createElement('button');copy.className='chat-copy';copy.type='button';copy.textContent='Copy';copy.onclick=async()=>{try{await navigator.clipboard.writeText(parsed.text);copy.textContent='Copied';}catch{copy.textContent='Copy unavailable';}};box.append(copy);}root.append(box);
 }
 if(stick)root.scrollTop=root.scrollHeight;
}
function creationCard(proposal,owner,chat){
 const key=creationKey(owner,chat,proposal);let entry=chatCreationEntries.get(key);
 if(!entry){entry={proposal,owner,chat,state:'draft'};try{const saved=JSON.parse(localStorage.getItem(key)||'null');if(saved?.job&&saved?.engine===proposal.engine){entry.job=saved.job;entry.state='running';}}catch{}chatCreationEntries.set(key,entry);}
 const card=document.createElement('section');card.className='chat-creation-card';card.style='white-space:normal;border:1px solid #434e5e;border-radius:10px;padding:18px;margin-top:14px;background:#20242d';
 const title=document.createElement('h3');title.style='margin:0 0 8px;font-size:16px';title.textContent={image:'Create an image',video:'Create a video',voice:'Create audio'}[proposal.engine];
 const text=document.createElement('p');text.style='white-space:pre-wrap';text.textContent=proposal.settings.prompt||proposal.settings.text||'Review the request in the editor.';
 const meta=document.createElement('p');meta.className='hint';meta.textContent=(workspaceData?.workspaces?.find(p=>p.id===owner)?.name||owner)+' · '+(proposal.engine==='image'?`${proposal.settings.width||768} × ${proposal.settings.height||768}`:proposal.engine==='video'?`${proposal.settings.seconds||5} seconds`:'Saved voice narration');
 const status=document.createElement('p');status.setAttribute('role','status');const actions=document.createElement('div');actions.className='actions';actions.style.marginTop='12px';
 const create=document.createElement('button');create.className='primary';create.type='button';const edit=document.createElement('button');edit.textContent='Review & edit';edit.type='button';const logs=document.createElement('button');logs.textContent='View logs';logs.type='button';logs.onclick=()=>window.StudioDiagnostics?.open(entry.job?.id||entry.errorId||'');
 const preview=document.createElement('img');preview.hidden=true;preview.alt='Created image';preview.style='display:block;max-width:100%;max-height:320px;object-fit:contain;margin-top:12px;border-radius:8px';
 const open=document.createElement('button');open.textContent='Open result';open.hidden=true;const video=document.createElement('button');video.textContent='Use for video';video.hidden=true;
 const technical=document.createElement('details');technical.hidden=true;const summary=document.createElement('summary');summary.textContent='Technical details';const details=document.createElement('pre');details.style='white-space:pre-wrap;overflow-wrap:anywhere';technical.append(summary,details);
 actions.append(create,edit,open,video,logs);card.append(title,text,meta,status,preview,actions,technical);
 entry.paint=()=>{const busy=['submitting','running'].includes(entry.state);create.disabled=busy;create.textContent=busy?'Creating…':entry.job?'Create another':{image:'Create image',video:'Generate video',voice:'Create audio'}[proposal.engine];edit.disabled=busy;status.textContent=entry.state==='draft'?'Ready when you are.':entry.state==='completed'?'Ready — saved in this project.':entry.state==='error'?creationError(entry.error||'Creation failed.'):entry.state==='submitting'?'Submitting your request…':(entry.job?.phase||'Creating')+(entry.job?.progress!=null?' · '+Math.round(entry.job.progress*100)+'%':'');technical.hidden=!entry.error;details.textContent=entry.error||'';open.hidden=entry.state!=='completed';video.hidden=entry.state!=='completed'||proposal.engine!=='image';if(entry.state==='completed'&&proposal.engine==='image'&&entry.job.image){preview.src='/image/'+entry.job.image+'?workspace='+encodeURIComponent(owner);preview.hidden=false;}else preview.hidden=true;};
 create.onclick=async()=>{if(['submitting','running'].includes(entry.state))return;if(currentWorkspace!==owner){entry.state='error';entry.error='Open this conversation in its original project before creating.';entry.paint();return;}if(entry.job&&!confirm('Create another result from this request?'))return;entry.state='submitting';entry.error=null;entry.paint();try{const job=await request({image:'/api/image/generate',video:'/api/generate',voice:'/api/voice/start'}[proposal.engine],proposal.settings);entry.job=job;entry.state='running';saveCreation(key,entry);entry.paint();monitorCreation(entry,key);await refresh();}catch(error){entry.state='error';entry.error=error.message;entry.errorId=error.errorId;entry.paint();}};
 edit.onclick=()=>editCreation(entry).catch(error=>{entry.error=error.message;entry.state='error';entry.paint();});
 open.onclick=()=>openCreation(entry,false).catch(error=>{entry.error=error.message;entry.state='error';entry.paint();});video.onclick=()=>openCreation(entry,true).catch(error=>{entry.error=error.message;entry.state='error';entry.paint();});
 entry.paint();if(entry.job&&entry.state==='running')monitorCreation(entry,key);return card;
}
async function monitorCreation(entry,key){
 if(entry.monitoring)return;entry.monitoring=true;
 try{while(entry.state==='running'){
  const response=await workspaceFetch('/api/job/status?kind='+entry.proposal.engine+'&id='+encodeURIComponent(entry.job.id),{headers:{'X-Studio-Workspace':entry.owner}});const job=await response.json();if(!response.ok)throw Error(job.error||'Cannot read creation status');entry.job=job;
  if(job.hidden){entry.state='error';entry.error='This result was deleted. Restore it from the project tree’s Trash.';}else if(job.status==='completed')entry.state='completed';else if(['failed','interrupted','cancelled','canceled'].includes(job.status)){entry.state='error';entry.error=job.message||'Creation '+job.status;}
  saveCreation(key,entry);entry.paint?.();if(entry.state!=='running'){await window.studioTree?.reload();break;}await new Promise(r=>setTimeout(r,2000));
 }}catch(error){entry.state='error';entry.error=error.message;entry.paint?.();}finally{entry.monitoring=false;}
}
async function editCreation(entry){
 const p=entry.proposal,kind={image:'images',video:'videos',voice:'audio'}[p.engine];await studioTree.activate(entry.owner,kind,null,'New '+p.engine,true);window.StudioCharacters?.apply(p.engine,p.settings);
 if(p.engine==='image'){$('imagePrompt').value=p.settings.prompt||'';const size=(p.settings.width||768)+','+(p.settings.height||768);if(![...$('imageSize').options].some(o=>o.value===size))$('imageSize').add(new Option(size.replace(',',' × '),size));$('imageSize').value=size;$('imageSeed').value=p.settings.seed??'';if(p.settings.images?.length){const references=new DataTransfer();for(const name of p.settings.images){const response=await workspaceFetch('/image/'+name+'?workspace='+entry.owner);if(!response.ok)throw Error('A reference image is unavailable.');const blob=await response.blob();references.items.add(new File([blob],name.split('/').pop(),{type:blob.type}));}$('imageRefs').files=references.files;$('imageRefs').onchange();}}
 if(p.engine==='video'){$('prompt').value=p.settings.prompt||'';$('seconds').value=p.settings.seconds||5;$('size').value=p.settings.size||'portrait';$('quality').value=p.settings.quality||'high';}
 if(p.engine==='voice'){$('voiceScript').value=p.settings.text||'';if(p.settings.profile)$('voiceProfile').value=p.settings.profile;}
 rememberWorkspace();
}
async function openCreation(entry,forVideo){
 const p=entry.proposal;const response=await workspaceFetch('/api/tree',{headers:{'X-Studio-Workspace':entry.owner}});const tree=await response.json();if(!response.ok)throw Error(tree.error);const asset=tree.projects.find(w=>w.id===entry.owner)?.assets.find(a=>a.metadata.job===entry.job.id&&a.metadata.engine===(p.engine==='voice'?'voice':p.engine)&&!a.trashed);
 await studioTree.activate(entry.owner,{image:'images',video:'videos',voice:'audio'}[p.engine],asset?.id||entry.job.id,asset?.name||'Created '+p.engine,false,!asset);
 if(forVideo)await studioTree.useImageForVideo();
}
