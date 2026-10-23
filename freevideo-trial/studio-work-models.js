/* Only installed adapter-compatible models are selectable in each work area. */

function installedStudioModels(data,engine){return (data?.catalog||[]).filter(model=>model.installed&&model.available!==false&&model.engine===engine);}

function renderWorkModels(data,busy=false){

 for(const field of document.querySelectorAll('select[data-model-engine]')){

  const engine=field.dataset.modelEngine,models=installedStudioModels(data,engine),signature=JSON.stringify([data?.selected?.[engine],models.map(m=>[m.id,m.name,m.selected])]);

  if(field.dataset.signature!==signature){field.replaceChildren();for(const model of models){const option=document.createElement('option');option.value=model.id;option.textContent=model.name;field.append(option);}if(!models.length){const empty=document.createElement('option');empty.value='';empty.textContent='No compatible model installed';field.append(empty);}field.value=data?.selected?.[engine]||'';field.dataset.signature=signature;}

  field.disabled=busy||models.length<2||field.dataset.changing==='true';

 }

}

window.addEventListener('DOMContentLoaded',()=>{

 for(const [section,engine,label] of [['chatStudio','writing','Chat model'],['videoStudio','video','Video model'],['imageStudio','image','Image model'],['voiceDesignForm','voice-design','Voice design model'],['voiceReadForm','voice-read','Narration model'],['voiceReadForm','sound-effects','Sound effects model'],['chatStudio','vision','Image / video understanding model']]){

  const root=document.getElementById(section),box=document.createElement('div');box.style='margin-bottom:16px';const caption=document.createElement('label'),field=document.createElement('select');field.id='workModel-'+engine;field.dataset.modelEngine=engine;caption.htmlFor=field.id;caption.textContent=label;box.append(caption,field);(root.querySelector('.workspace-controls')||(['videoStudio','imageStudio'].includes(section)?root.querySelector('form'):root)).prepend(box);

  field.onchange=async()=>{field.dataset.changing='true';field.disabled=true;const status=document.getElementById('workModelStatus');try{await request('/api/settings/models/select',{id:field.value});status.textContent='Model changed for future jobs across Studio.';if(engine==='writing'){startupChatWarmup=true;await warmChatAtStartup();}await refresh();}catch(error){status.textContent=error.message;field.dataset.signature='';if(workspaceData?.models)renderWorkModels(workspaceData.models);}finally{field.dataset.changing='false';if(workspaceData?.models)renderWorkModels(workspaceData.models,!!workspaceData.global_busy);}};

 }

 const status=document.createElement('p');status.id='workModelStatus';status.setAttribute('role','status');status.className='hint';document.getElementById('workHeader')?.after(status);

 if(!status.isConnected)document.querySelector('main').prepend(status);

 if(workspaceData?.models)renderWorkModels(workspaceData.models);

});

if(typeof module!=='undefined')module.exports={installedStudioModels};

