const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('Enter sends while Shift+Enter and IME composition do not',()=>{
 const source=fs.readFileSync(__dirname+'/studio-chat.js','utf8');const code=source.match(/function chatEnterSends\(event\)\{[^}]+\}/)[0];const context={};vm.runInNewContext(code,context);
 assert.equal(context.chatEnterSends({key:'Enter'}),true);
 for(const event of [{key:'Enter',shiftKey:true},{key:'Enter',isComposing:true},{key:'Enter',keyCode:229},{key:'a'}])assert.equal(context.chatEnterSends(event),false);
});
test('work area model lists include only installed models for the exact adapter',()=>{
 const source=fs.readFileSync(__dirname+'/studio-work-models.js','utf8').split('function renderWorkModels')[0],context={};vm.runInNewContext(source,context);
 const data={catalog:[{id:'chat',engine:'writing',installed:true},{id:'future',engine:'writing',installed:false},{id:'missing',engine:'writing',installed:true,available:false},{id:'read',engine:'voice-read',installed:true},{id:'design',engine:'voice-design',installed:true},{id:'image',engine:'image',installed:true}]};
 assert.deepEqual(Array.from(context.installedStudioModels(data,'writing'),x=>x.id),['chat']);assert.deepEqual(Array.from(context.installedStudioModels(data,'voice-read'),x=>x.id),['read']);assert.equal(context.installedStudioModels(data,'video').length,0);
});
