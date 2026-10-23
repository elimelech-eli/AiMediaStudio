const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(__dirname+'/studio-tree.js','utf8');
const helper=source.slice(source.indexOf('async function useImageForVideo('),source.indexOf('function nodeButton('));
function fixture(active,rows=[]){
 const fields=Object.fromEntries(['image','reference','imageName','prompt','imageRefs'].map(id=>[id,{files:[],value:'old',textContent:'',focus(){this.focused=true;}}]));const calls=[];
 const ctx={window:{},notify:()=>{},activeItem:active,project:()=>({archived:false}),uploading:false,imageUploading:false,voiceSubmitting:false,imageRows:rows,imageSelected:rows[0]?.id,imageChoice:'previous.png',$t:id=>fields[id],api:async(owner,path,body)=>{calls.push({owner,path,body});return {image:'owned-reference.png'};},activate:async(owner,kind,id,name,creation)=>{calls.push({owner,kind,creation});ctx.imageChoice=null;},clearContinuation:()=>calls.push('clear'),rememberWorkspace:()=>calls.push('save')};vm.createContext(ctx);vm.runInContext(helper,ctx);return {ctx,fields,calls};
}
test('imported image hands its project-owned reference to a fresh video workspace',async()=>{
 const {ctx,fields,calls}=fixture({owner:'project-a',kind:'images',id:'asset-a',name:'Imported portrait'});await ctx.useImageForVideo();assert.equal(calls[0].owner,'project-a');assert.equal(calls[0].body.id,'asset-a');assert.equal(calls[1].kind,'videos');assert.equal(calls[1].owner,'project-a');assert.equal(ctx.imageChoice,'owned-reference.png');assert.equal(fields.image.value,'');assert.equal(fields.reference.value,'');assert.match(fields.imageName.textContent,/Imported portrait/);assert.equal(fields.prompt.focused,true);
});
test('completed generated image uses its output directly and unfinished output cannot navigate',async()=>{
 const {ctx,calls}=fixture({owner:'project-b',kind:'images',id:'image-job',job:true},[{id:'image-job',status:'completed',image:'generated.png'}]);await ctx.useImageForVideo();assert.equal(ctx.imageChoice,'generated.png');assert.equal(calls[0].owner,'project-b');assert.equal(calls[0].kind,'videos');
 const pending=fixture({owner:'project-b',kind:'images'},[{id:'pending',status:'running'}]);await assert.rejects(pending.ctx.useImageForVideo(),/completed image/);assert.equal(pending.calls.length,0);
});
test('archived and submitting work cannot be redirected',async()=>{
 const f=fixture({owner:'project-a',kind:'images',id:'asset'});f.ctx.project=()=>({archived:true});await assert.rejects(f.ctx.useImageForVideo(),/Restore/);assert.equal(f.calls.length,0);
 f.ctx.project=()=>({archived:false});f.ctx.imageUploading=true;await assert.rejects(f.ctx.useImageForVideo(),/submission/);assert.equal(f.calls.length,0);
});
test('uploaded references can become first frames before image generation',async()=>{
 const {ctx,fields}=fixture({owner:'project-a',kind:'images',id:null});ctx.currentWorkspace='project-a';ctx.upload=async file=>{assert.equal(file.name,'source.png');return 'uploaded.png'};fields.imageRefs.files=[{name:'source.png'}];await ctx.useImageForVideo();assert.equal(ctx.imageChoice,'uploaded.png');assert.match(fields.imageName.textContent,/source.png/);assert.equal(ctx.imageUploading,false);
});
test('multiple uploaded references require choosing one rather than guessing',async()=>{
 const {ctx,fields,calls}=fixture({owner:'project-a',kind:'images',id:null});fields.imageRefs.files=[{name:'one.png'},{name:'two.png'}];await assert.rejects(ctx.useImageForVideo(),/beside the reference/);assert.equal(calls.length,0);
});
