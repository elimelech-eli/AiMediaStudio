/* A conversation-first layout reusing the existing chat controls and requests. */

function renderChatRichText(text){

 const root=document.createElement('div');root.className='chat-prose';

 const inline=(parent,value)=>{for(const part of value.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)){const element=document.createElement(part.startsWith('**')?'strong':part.startsWith('`')?'code':'span');element.textContent=part.startsWith('**')?part.slice(2,-2):part.startsWith('`')?part.slice(1,-1):part;parent.append(element);}};

 const blocks=text.split(/```[^\n]*\n([\s\S]*?)```/g);

 blocks.forEach((block,index)=>{if(index%2){const pre=document.createElement('pre'),code=document.createElement('code');code.textContent=block;pre.append(code);root.append(pre);return;}

  for(const paragraph of block.split(/\n\s*\n/)){if(!paragraph.trim())continue;const lines=paragraph.split('\n');if(lines.every(line=>/^\s*(?:[-*]|\d+\.)\s/.test(line))){const list=document.createElement(/^\s*\d+\./.test(lines[0])?'ol':'ul');for(const line of lines){const item=document.createElement('li');inline(item,line.replace(/^\s*(?:[-*]|\d+\.)\s+/,''));list.append(item);}root.append(list);}else{const heading=paragraph.match(/^(#{1,3})\s+([\s\S]*)/);const element=document.createElement(heading?'h'+(heading[1].length+2):'p');inline(element,heading?heading[2]:paragraph);root.append(element);}}

 });return root;

}

function updateChatAttachmentChips(){

 const root=document.getElementById('chatAttachmentChips');if(!root)return;root.replaceChildren();

 for(const [index,file] of [...$('chatAttachments').files].entries()){

  const chip=document.createElement('span');chip.className='chat-file-chip';const name=document.createElement('span');name.textContent=file.name;const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Remove '+file.name);remove.onclick=()=>{const transfer=new DataTransfer();[...$('chatAttachments').files].forEach((item,i)=>{if(i!==index)transfer.items.add(item);});chatAttachmentDrafts.set(chatAttachmentScope(),transfer.files);$('chatAttachments').files=transfer.files;$('chatAttachments').dispatchEvent(new Event('change'));};chip.append(name,remove);root.append(chip);

 }

}

function clearPendingChat(){document.querySelectorAll('.chat-transient').forEach(node=>node.remove());}

function showPendingChat(text,files){

 clearPendingChat();const root=$('chatHistory');root.querySelector('.chat-welcome')?.remove();

 const message=document.createElement('div');message.className='chat-message chat-user chat-transient';message.append(renderChatRichText(text));if(files.length){const list=document.createElement('p');list.className='hint';list.textContent=files.map(file=>file.name).join(', ');message.append(list);}const pending=document.createElement('div');pending.className='chat-pending chat-transient';pending.textContent=files.length?'Reading your attachments…':'Thinking…';root.append(message,pending);root.scrollTop=root.scrollHeight;

}

function updatePendingChat(state){
 const pending=document.querySelector('#chatHistory .chat-pending');if(!pending)return;
 const text=(state.partial||'').split('```')[0];
 if(text){pending.replaceChildren(renderChatRichText(text));pending.classList.add('chat-streaming');}
 else pending.textContent=(state.phase||'Preparing local reply')+' · '+Math.round(state.elapsed||0)+'s';
 $('chatStatus').textContent=(state.phase||'Preparing local reply')+' · '+Math.round(state.elapsed||0)+'s';
}

const CHAT_FILE_TYPES={image:['png','jpg','jpeg','webp'],video:['mp4','mov','webm','mkv'],document:['pdf','txt','md','markdown','json','jsonl','csv','tsv','yaml','yml','xml','html','htm','log','ini','toml','rst','py','js','css','sql']};
function mergeChatFiles(existing,incoming){
 const result=[...existing];for(const file of incoming){const ext=file.name.split('.').pop().toLowerCase(),kind=Object.keys(CHAT_FILE_TYPES).find(k=>CHAT_FILE_TYPES[k].includes(ext));if(!kind)throw Error('Unsupported attachment: '+file.name);const limit=kind==='video'?256:kind==='image'||ext==='pdf'?32:2;if(file.size>limit*1024*1024)throw Error(file.name+' exceeds the '+limit+' MiB limit.');if(!result.some(f=>f.name===file.name&&f.size===file.size&&f.lastModified===file.lastModified))result.push(file);}
 if(result.length>4)throw Error('Attach at most four files per message.');return result;
}

function resizeChatComposer(){const field=$('chatInput');field.style.height='auto';field.style.height=Math.min(180,Math.max(46,field.scrollHeight))+'px';}

window.addEventListener('DOMContentLoaded',()=>{

 const chat=$('chatStudio'),form=$('chatForm'),history=$('chatHistory');

 const toolbar=document.createElement('div');toolbar.id='chatToolbar';const model=$('workModel-writing');if(model)toolbar.append(model.parentElement);

 const options=document.createElement('details');options.id='chatOptions';const summary=document.createElement('summary');summary.textContent='Chat options';options.append(summary);const settings=document.createElement('div');settings.className='chat-options-panel';

 const vision=$('workModel-vision');if(vision)settings.append(vision.parentElement);

 const modeLabel=document.createElement('label');modeLabel.textContent='Processing';modeLabel.htmlFor='chatMode';settings.append(modeLabel,$('chatMode'));

 const help=document.createElement('p');help.className='hint';help.textContent='Drop files into chat or use +. Up to four attachments. Text: 2 MiB; PDF/images: 32 MiB; video: 256 MiB, up to 120 seconds. PDFs: up to 100 pages, CPU OCR on up to 12 scanned pages; long text uses excerpts. PDF charts/layout are not visually analyzed. Video: four sampled frames, no audio.';settings.append(help,$('chatUnload'),$('chatClear'));options.append(settings);toolbar.append(options);chat.prepend(toolbar);

 for(const node of [...chat.children])if(![toolbar,history,form,$('chatStatus')].includes(node))node.hidden=true;

 history.setAttribute('role','log');history.setAttribute('aria-label','Conversation');history.setAttribute('aria-live','polite');

 const chips=document.createElement('div');chips.id='chatAttachmentChips';

 const actions=document.createElement('div');actions.className='chat-composer-actions';const attach=document.createElement('button');attach.type='button';attach.className='chat-attach';attach.textContent='+';attach.title='Attach files';attach.setAttribute('aria-label','Attach files');attach.onclick=()=>$('chatAttachments').click();

 const hint=document.createElement('span');hint.className='hint';hint.textContent='Enter to send · Shift+Enter for a new line';const send=$('chatSend');send.textContent='↑';send.title='Send message';send.setAttribute('aria-label','Send message');const stop=document.createElement('button');stop.id='chatStop';stop.type='button';stop.textContent='■';stop.title='Stop reply and keep partial text';stop.setAttribute('aria-label','Stop reply');stop.hidden=true;stop.onclick=()=>stopChatReply();actions.append(attach,hint,stop,send);

 const input=$('chatInput'),files=$('chatAttachments');input.placeholder='Message AiMediaStudio…';input.setAttribute('aria-label','Message');input.rows=1;files.hidden=true;

 form.replaceChildren(chips,input,actions,files,$('chatAttachmentsClear'));$('chatAttachmentsClear').hidden=true;

 const attachmentHelp=document.createElement('p');attachmentHelp.className='hint';attachmentHelp.id='chatDropHelp';attachmentHelp.textContent='Drop images, videos, PDFs or text files here · Up to 4 files · PDF/image 32 MiB, text 2 MiB, video 256 MiB';form.before(attachmentHelp);
 const originalChange=files.onchange;
 function assignFiles(values){const transfer=new DataTransfer();for(const file of values)transfer.items.add(file);files.files=transfer.files;originalChange?.call(files);updateChatAttachmentChips();}
 function addFiles(values){const before=[...(chatAttachmentDrafts.get(chatAttachmentScope())||[])];try{assignFiles(mergeChatFiles(before,values));$('chatStatus').textContent='Attachments ready. Write what you want analyzed, then send.';}catch(error){assignFiles(before);$('chatStatus').textContent=error.message;}}
 files.accept=Object.values(CHAT_FILE_TYPES).flat().map(ext=>'.'+ext).join(',');files.onchange=()=>addFiles([...files.files]);
 let dragDepth=0;const dragging=event=>[...(event.dataTransfer?.types||[])].includes('Files');
 chat.addEventListener('dragenter',event=>{if(!dragging(event))return;event.preventDefault();dragDepth++;chat.classList.add('chat-drop-target');});
 chat.addEventListener('dragover',event=>{if(!dragging(event))return;event.preventDefault();event.dataTransfer.dropEffect='copy';});
 chat.addEventListener('dragleave',event=>{if(!dragging(event))return;if(--dragDepth<=0){dragDepth=0;chat.classList.remove('chat-drop-target');}});
 chat.addEventListener('drop',event=>{if(!dragging(event))return;event.preventDefault();event.stopPropagation();dragDepth=0;chat.classList.remove('chat-drop-target');if(chatSending){$('chatStatus').textContent='Wait for the current message before adding attachments.';return;}addFiles([...event.dataTransfer.files]);});
 chat.append(form,$('chatStatus'));input.addEventListener('input',resizeChatComposer);files.addEventListener('change',updateChatAttachmentChips);

 const sync=()=>{document.body.classList.toggle('chat-focused',!chat.hidden&&!document.body.classList.contains('work-empty')&&$('modelSettings').hidden);};new MutationObserver(sync).observe(chat,{attributes:true,attributeFilter:['hidden']});new MutationObserver(sync).observe($('modelSettings'),{attributes:true,attributeFilter:['hidden']});new MutationObserver(sync).observe(document.body,{attributes:true,attributeFilter:['class']});sync();resizeChatComposer();

 document.addEventListener('pointerdown',event=>{if(!options.contains(event.target))options.open=false;});

});

