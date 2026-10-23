const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const s=fs.readFileSync(__dirname+'/studio-chat-layout.js','utf8'),context={};vm.createContext(context);vm.runInContext(s.slice(s.indexOf('const CHAT_FILE_TYPES'),s.indexOf('function resizeChatComposer')),context);
const file=(name,size=100)=>({name,size,lastModified:1});
test('attachment merging supports PDF/image/video/MD and deduplicates',()=>{const a=file('notes.md'),b=file('report.pdf'),c=file('image.png'),d=file('video.mp4');assert.equal(context.mergeChatFiles([a],[a,b,c,d]).length,4)});
test('unsupported files, per-type size limits and excess count fail atomically',()=>{const before=[file('keep.md')];for(const incoming of [[file('x.exe')],[file('x.pdf',33*1024**2)],[file('x.txt',3*1024**2)],[file('x.mp4',257*1024**2)],[file('a.md'),file('b.md'),file('c.md'),file('d.md')]])assert.throws(()=>context.mergeChatFiles(before,incoming));assert.equal(before.length,1)});
