const {app,BrowserWindow,dialog}=require('electron');
const {spawn}=require('node:child_process');
const http=require('node:http');
const path=require('node:path'),fs=require('node:fs/promises');
const root=path.resolve(__dirname,'..'),data=path.join(root,'studio-data'),base='http://127.0.0.1:57846';
app.setName('FreeVideo Studio');app.setAppUserModelId('local.freevideo.studio');
app.setPath('userData',path.join(data,'desktop-runtime'));
app.setPath('sessionData',path.join(data,'desktop-session'));
app.setPath('crashDumps',path.join(data,'desktop-crashes'));
app.setAppLogsPath(path.join(data,'desktop-logs'));
let win;
if(!app.requestSingleInstanceLock())app.quit();
else{
 app.on('second-instance',()=>{if(win){if(win.isMinimized())win.restore();win.show();win.focus();}});
 app.whenReady().then(async()=>{
  await fs.mkdir(path.join(data,'exports'),{recursive:true});
  win=new BrowserWindow({width:1280,height:940,minWidth:850,minHeight:650,title:'FreeVideo Studio',backgroundColor:'#100f17',autoHideMenuBar:true,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
  win.removeMenu();
  if(process.argv.includes('--studio-app-check'))win.webContents.on('console-message',event=>{if(event?.message)fs.appendFile(path.join(data,'desktop-renderer-check.log'),event.message+'\n').catch(()=>{});});
  win.webContents.on('before-input-event',(event,input)=>{if(input.type==='keyDown'&&(input.key==='F5'||input.control&&input.key.toLowerCase()==='r')){event.preventDefault();win.webContents.reload();}});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',(event,url)=>{if(new URL(url).origin!==base)event.preventDefault();});
  win.webContents.session.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
  win.webContents.session.on('will-download',(_event,item)=>item.setSaveDialogOptions({defaultPath:path.join(data,'exports',path.basename(item.getFilename()))}));
  win.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent('<body style="background:#100f17;color:#f3edf7;font:18px Segoe UI;padding:48px"><h1>FreeVideo Studio</h1><p>Starting your local studio…</p><p>Existing renders continue when this window closes.</p></body>')).catch(()=>{});
  let ready=false;
  function probe(){return new Promise(resolve=>{let ended=false;const finish=value=>{if(!ended){ended=true;clearTimeout(timer);resolve(value);}};const request=http.get(base+'/api/state',response=>{response.resume();finish(response.statusCode===200);});const timer=setTimeout(()=>{request.destroy();finish(false);},2000);request.on('error',()=>finish(false));});}
  ready=await probe();
  if(!ready){
   const log=await fs.open(path.join(root,'logs','studio-startup.log'),'a');
   const env={...process.env};
   const configuration=await fs.readFile(path.join(root,'env.ps1'),'utf8');
   for(const match of configuration.matchAll(/^\$env:([A-Z0-9_]+)\s*=\s*'([^']*)'/gm))env[match[1]]=match[2];
   const child=spawn(path.join(root,'runtime','envs','unified','Scripts','python.exe'),['-B','-u',path.join(root,'studio.py')],{cwd:root,env,windowsHide:true,detached:true,stdio:['ignore',log.fd,log.fd]});
   if(child.pid)await fs.writeFile(path.join(root,'studio.pid'),String(child.pid));
   await log.close();
   let error;child.on('error',value=>{error=value;});child.unref();
   const deadline=Date.now()+60000;while(Date.now()<deadline&&!ready){if(error)throw error;await new Promise(resolve=>setTimeout(resolve,500));ready=await probe();}
  }
  if(!ready)throw Error('Studio did not start. Check freevideo-trial/logs/studio.err.log, then reopen the launcher.');
  await win.loadURL(base+(process.argv.includes('--studio-app-check')?'/?no-chat-preload=1#video':'/#video'));win.show();win.focus();
  if(process.argv.includes('--studio-app-check')){
   const watchdog=setTimeout(async()=>{try{await fs.writeFile(path.join(data,'desktop-tree-timeout.png'),(await win.webContents.capturePage()).toPNG());console.error(await win.webContents.executeJavaScript('JSON.stringify({owner:currentWorkspace,active:window.studioTree?.active,title:document.getElementById("workTitle")?.textContent})'));}finally{app.quit();}},180000);
   console.log('CHECK: layouts');
   const result=await win.webContents.executeJavaScript('({title:document.title,url:location.href,videoTab:!!document.getElementById("videoTab"),imageTab:!!document.getElementById("imageTab"),nodeIsolated:typeof require==="undefined"})');
   result.views=await win.webContents.executeJavaScript(`(()=>{const picker=document.getElementById('workspaceView'),prompt=document.getElementById('prompt'),chat=document.getElementById('chatInput');if(!picker)throw Error('Missing workspace view picker');const original=picker.value,draft=prompt.value,chatDraft=chat.value,history=document.getElementById('jobs'),file=document.getElementById('image'),selectedBefore=selected,voiceBefore=selectedVoiceJob;const results=[];try{prompt.value='view-switch verification';chat.value='unsent chat verification';for(const view of ['desk','library','director']){picker.value=view;picker.dispatchEvent(new Event('change'));if(document.querySelector('main').dataset.view!==view||document.getElementById('prompt')!==prompt||prompt.value!=='view-switch verification'||document.getElementById('chatInput')!==chat||chat.value!=='unsent chat verification'||document.getElementById('jobs')!==history||document.getElementById('image')!==file||selected!==selectedBefore||selectedVoiceJob!==voiceBefore)throw Error('View switch lost state');results.push({view,preserved:true});}return results;}finally{prompt.value=draft;chat.value=chatDraft;picker.value=original;picker.dispatchEvent(new Event('change'));}})()`);
   console.log('CHECK: project isolation');
   result.projects=await win.webContents.executeJavaScript(`(async()=>{for(let n=0;n<100&&!workspaceData;n++)await new Promise(r=>setTimeout(r,50));if(!workspaceData||!document.getElementById('contextPanel')||!document.getElementById('assetCards'))throw Error('Project UI did not initialize');const owner=currentWorkspace,originalPrompt=document.getElementById('prompt').value,originalChat=document.getElementById('chatInput').value;let test;try{document.getElementById('prompt').value='project draft verification';document.getElementById('chatInput').value='project chat draft verification';test=await request('/api/workspaces/create',{name:'Disposable renderer verification'});await switchWorkspace(test.id);if(currentWorkspace!==test.id||workspaceData.assets.length)throw Error('New project is not isolated');document.getElementById('prompt').value='Independent project draft';document.getElementById('contextBrief').value='Unsaved project brief';document.getElementById('contextBrief').dispatchEvent(new Event('input',{bubbles:true}));await switchWorkspace(owner);if(document.getElementById('prompt').value!=='project draft verification'||document.getElementById('chatInput').value!=='project chat draft verification')throw Error('Workspace switch lost drafts');await switchWorkspace(test.id);if(document.getElementById('prompt').value!=='Independent project draft'||document.getElementById('contextBrief').value!=='Unsaved project brief')throw Error('Project draft not restored');await request('/api/workspace/update',{deleted:true});await switchWorkspace(owner);await request('/api/workspaces/purge',{id:test.id});return {selector:true,context:true,library:true,drafts:true,contextDraft:true,models:!!document.getElementById('modelSettings'),isolated:true};}finally{if(currentWorkspace!==owner)await switchWorkspace(owner);document.getElementById('prompt').value=originalPrompt;document.getElementById('chatInput').value=originalChat;rememberWorkspace();}})().catch(error=>{console.error(error.stack);throw error;})`);
   console.log('CHECK: tree interactions');
   result.tree=await win.webContents.executeJavaScript(await fs.readFile(path.join(__dirname,'tree-check.js'),'utf8'));
   await win.webContents.executeJavaScript('window.studioTree.close()');
   await fs.writeFile(path.join(data,'desktop-tree-preview.png'),(await win.webContents.capturePage()).toPNG());
   clearTimeout(watchdog);
   await fs.writeFile(path.join(data,'desktop-check.json'),JSON.stringify(result,null,2));await fs.rm(path.join(data,'desktop-check-error.json'),{force:true});app.quit();
  }
 }).catch(async error=>{console.error(error.message);if(process.argv.includes('--studio-app-check')){await fs.writeFile(path.join(data,'desktop-check-error.json'),JSON.stringify({message:error.message,stack:error.stack}));app.quit();return;}await dialog.showMessageBox({type:'error',title:'FreeVideo Studio',message:'Could not open FreeVideo Studio',detail:error.message});app.quit();});
 app.on('window-all-closed',()=>app.quit());
}
