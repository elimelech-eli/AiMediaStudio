(async()=>{
 const wait=ms=>new Promise(r=>setTimeout(r,ms));for(let i=0;i<100&&!window.studioTree;i++)await wait(50);
 if(!window.studioTree)throw Error('Tree did not initialize');
 const originalOwner=currentWorkspace,oldPrompt=prompt,oldConfirm=confirm;let first,second;
 const api=async(owner,path,body)=>{const r=await workspaceFetch(path,{method:'POST',headers:{'X-Studio-Token':token,'X-Studio-Workspace':owner,'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await r.json();if(!r.ok)throw Error(value.error);return value;};
 try{
  first=await api(originalOwner,'/api/workspaces/create',{name:'Disposable tree A'});second=await api(originalOwner,'/api/workspaces/create',{name:'Disposable tree B'});
  const a=await api(first.id,'/api/chats/action',{action:'create',name:'Tree chat A'}),b=await api(first.id,'/api/chats/action',{action:'create',name:'Tree chat B'});
  console.log('TREE: projects created');await studioTree.reload();console.log('TREE: open chat');await studioTree.activate(first.id,'chats',a.id,'Tree chat A');document.getElementById('chatInput').value='Independent named chat draft';
  console.log('TREE: open done');const summary=[...document.querySelectorAll('#projectTree summary')].find(x=>x.textContent.includes('Disposable tree B'));summary.click();
  if(currentWorkspace!==first.id||window.studioChatId!==a.id||document.getElementById('chatInput').value!=='Independent named chat draft')throw Error('Browsing changed current work');
  await studioTree.activate(first.id,'chats',b.id,'Tree chat B');if(document.getElementById('chatInput').value)throw Error('Named chat inherited another draft');
  await studioTree.activate(first.id,'chats',a.id,'Tree chat A');if(document.getElementById('chatInput').value!=='Independent named chat draft')throw Error('Named chat draft lost');
  console.log('TREE: drafts checked');const item=[...document.querySelectorAll('#projectTree [data-item]')].find(x=>JSON.parse(x.dataset.item).id===b.id);item.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:180,clientY:200}));
  const labels=[...document.querySelectorAll('#treeMenu button')].map(x=>x.textContent);if(!['Rename','Duplicate','Delete'].every(x=>labels.includes(x))||labels.some(x=>/^Move to project/.test(x)))throw Error('Incorrect item menu');
  const namedPrompt=window.prompt;document.querySelectorAll('#treeMenu button')[labels.indexOf('Duplicate')].click();await wait(100);const nameDialog=document.querySelector('.tree-name-dialog');if(!nameDialog)throw Error('Native name dialog missing');nameDialog.querySelector('input').value='Duplicated chat';nameDialog.close('save');for(let i=0;i<30;i++){await wait(300);await studioTree.reload();if(studioTree.data.projects.find(x=>x.id===first.id)?.chats.some(x=>x.name==='Duplicated chat'))break;}window.prompt=namedPrompt;
  if(!studioTree.data.projects.find(x=>x.id===first.id).chats.some(x=>x.name==='Duplicated chat'))throw Error('Context duplicate failed');
  console.log('TREE: duplicate checked');const data=new DataTransfer();data.setData('application/x-ams-items',JSON.stringify([{owner:first.id,kind:'chats',id:b.id,name:'Tree chat B'}]));window.confirm=()=>true;summary.dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:data}));for(let i=0;i<30;i++){await wait(300);await studioTree.reload();if(studioTree.data.projects.find(x=>x.id===second.id)?.chats.some(x=>x.name==='Tree chat B'))break;}
  if(!studioTree.data.projects.find(x=>x.id===second.id).chats.some(x=>x.name==='Tree chat B'))throw Error('Drop move failed');
  if(window.studioChatId!==a.id)throw Error('Drop replaced current chat');
  if(getComputedStyle(document.getElementById('engineTabs')).display!=='none'||[...document.querySelectorAll('.workspace-media')].some(x=>getComputedStyle(x).display!=='none'))throw Error('Legacy navigation/recents visible');
  await studioTree.activate(first.id,'videos',null,'New video',true);if(selected!=='tree-new')throw Error('New video did not clear its prior selection');console.log('TREE: drop checked');return {tree:true,browsingIndependent:true,namedDrafts:true,contextMenus:true,duplicate:true,dragMove:true,recentsRemoved:true};
 }finally{
  window.prompt=oldPrompt;window.confirm=oldConfirm;window.studioChatId=null;await switchWorkspace(originalOwner);
  for(const p of [first,second].filter(Boolean)){await api(p.id,'/api/workspace/update',{deleted:true});await api('free-work','/api/workspaces/purge',{id:p.id});}
  await studioTree.reload();
 }
})()
