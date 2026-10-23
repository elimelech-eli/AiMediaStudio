let imageSelected=null,imageRows=[],imageUploading=false,referenceUrls=[];
function studioMode(images){$('voiceStudio').hidden=true;$('voiceTab').classList.remove('primary');location.hash=images?'images':'video';$('imageStudio').hidden=!images;$('videoStudio').hidden=images;$('imageTab').classList.toggle('primary',images);$('videoTab').classList.toggle('primary',!images);}
$('videoTab').onclick=()=>studioMode(false);
$('imageTab').onclick=()=>studioMode(true);
$('clearImageRefs').onclick=()=>{$('imageRefs').value='';$('imageRefs').onchange();};
$('imageRefs').onchange=()=>{
 for(const url of referenceUrls)URL.revokeObjectURL(url);referenceUrls=[];$('imageRefList').replaceChildren();
 const files=[...$('imageRefs').files];$('imageError').textContent=files.length>4?'Choose at most four references.':'';
 files.forEach((file,index)=>{const row=document.createElement('div');row.style='display:flex;align-items:center;gap:10px;margin-top:10px';const img=document.createElement('img');const url=URL.createObjectURL(file);referenceUrls.push(url);img.src=url;img.alt='Reference '+(index+1);img.style='width:64px;height:64px;object-fit:contain';const label=document.createElement('span');label.textContent=`Image ${index+1}: ${file.name}`;const use=document.createElement('button');use.type='button';use.textContent='Use as video first frame';use.onclick=async()=>{use.disabled=true;try{await window.studioTree.useImageForVideo(null,file);}catch(error){$('imageError').textContent=error.message;}finally{use.disabled=false;}};row.append(img,label,use);$('imageRefList').append(row);});window.studioTree?.syncImageAction();
};
$('imageForm').onsubmit=async event=>{
 event.preventDefault();if(imageUploading)return;imageUploading=true;$('imageGenerate').disabled=true;$('imageError').textContent='';
 try{const files=[...$('imageRefs').files];if(files.length>4)throw Error('Choose at most four reference images.');$('imageStatus').textContent='Uploading local references…';const images=[];for(const file of files)images.push(await upload(file,'image'));const [width,height]=$('imageSize').value.split(',').map(Number);const seed=$('imageSeed').value.trim();const job=await request('/api/image/generate',{prompt:$('imagePrompt').value,images,width,height,seed:seed?Number(seed):null});imageSelected=job.id;window.studioTree?.trackImageJob(job.id);await refresh();}
 catch(error){$('imageError').textContent=error.message;}finally{imageUploading=false;await refresh();}
};
$('imageCancel').onclick=async()=>{try{await request('/api/image/cancel');await refresh();}catch(error){$('imageError').textContent=error.message;}};
$('imageToVideo').onclick=async()=>{
 if(window.studioTree){try{await window.studioTree.useImageForVideo();}catch(error){$('imageError').textContent=error.message;const notice=document.getElementById('treeStatus');if(notice)notice.textContent=error.message;}return;}
 const job=imageRows.find(row=>row.id===imageSelected);if(!job?.image)return;
 clearContinuation();imageChoice=job.image;$('image').value='';$('reference').value='';$('imageName').textContent='Generated image '+job.id+' selected';studioMode(false);$('prompt').focus();
};
function renderImages(data){
 imageRows=data.images||[];const info=data.image_model||{},install=info.install||{};
 $('imageModel').textContent=info.ready?'Qwen Image 2.1 Turbo · ready locally. Images and videos run one at a time. Unload other GPU models before generating.':`Image model: ${install.state||'not installed'}${install.total?' · '+Math.floor(100*(install.done||0)/install.total)+'%':''}${install.reason?' · '+install.reason:''}`;
 $('imageGenerate').disabled=imageUploading||!info.ready;$('imageCancel').disabled=!data.image_active;
 $('imageHistory').replaceChildren();for(const job of imageRows){const button=document.createElement('button');button.className='history-item';button.textContent=`${job.status} · ${job.settings.width} × ${job.settings.height} · ${job.settings.prompt.slice(0,85)}`;button.onclick=()=>{imageSelected=job.id;renderImages(data);};$('imageHistory').append(button);}
 if(!imageSelected)imageSelected=data.image_active||imageRows[0]?.id;const job=imageRows.find(row=>row.id===imageSelected);if(!job){$('imageToVideo').hidden=true;return;}
 const done=job.status==='completed';$('imagePreview').hidden=!done;$('imageToVideo').hidden=!done;$('imageToVideo').disabled=false;$('imageDownload').hidden=!done;
 if(done){const url=mediaURL('/image/'+job.image);if(!$('imagePreview').src.endsWith(url))$('imagePreview').src=url;$('imageDownload').href=url;$('imageDownload').download=job.id+'.png';}
 $('imageStatus').textContent=`${job.status} · ${job.phase||''}${job.progress!=null?' · '+Math.round(job.progress*100)+'%':''} · ${duration(job.elapsed||0)}`;
 if(job.status==='failed'||job.status==='interrupted')$('imageError').textContent=job.message||'Image generation failed.';
}
if(location.hash==='#images')studioMode(true);
