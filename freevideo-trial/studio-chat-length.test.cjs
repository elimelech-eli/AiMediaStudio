const {test}=require('node:test'),assert=require('node:assert/strict');
const {LocalConversation,parseStream}=require('./local-conversation.cjs');
function stream(text,reason='stop'){return new Response('data: '+JSON.stringify({choices:[{delta:{content:text},finish_reason:reason}]})+'\n\ndata: [DONE]\n\n').body;}
test('token exhaustion preserves a segment and automatically continues as one answer',async()=>{
 const model=new LocalConversation(),calls=[],output=[];model.start=async()=>{};model.fit=async messages=>messages;model.api=async(route,body)=>{calls.push(body);return {ok:true,body:stream(calls.length===1?'First paragraph.':'Second paragraph.',calls.length===1?'length':'stop')}};
 await model.complete([{role:'system',content:'Persona'},{role:'user',content:'Write a long answer'}],text=>output.push(text));assert.equal(calls.length,2);assert.equal(output.join(''),'First paragraph.\n\nSecond paragraph.');assert.equal(calls[1].messages[0].content,'Persona');assert.equal(calls[1].messages[1].content,'Write a long answer');assert.equal(calls[1].messages.at(-2).content,'First paragraph.');
});
test('Stop aborts a running stream while already emitted text survives',async()=>{
 const controller=new AbortController(),model=new LocalConversation(),output=[];model.start=async()=>{};model.fit=async m=>m;
 model.api=async()=>({ok:true,body:new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('data: '+JSON.stringify({choices:[{delta:{content:'Keep this text.'}}]})+'\n\n'));controller.signal.addEventListener('abort',()=>c.error(new DOMException('Stopped','AbortError')))}})});
 await assert.rejects(model.complete([],text=>{output.push(text);controller.abort()},controller.signal),{name:'AbortError'});assert.equal(output.join(''),'Keep this text.');
});
test('broken streams still fail rather than pretending completion',async()=>{await assert.rejects(parseStream(new Response('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n').body,()=>{}),/ended early/)});
test('continuation inside a creation block does not insert invalid JSON newlines',async()=>{
 const model=new LocalConversation(),output=[],calls=[];model.start=async()=>{};model.fit=async m=>m;model.api=async(route,body)=>{calls.push(body);return {ok:true,body:stream(calls.length===1?'```studio\n{"engine":"image","settings":{"prompt":"A scene':' with trees"}}\n```',calls.length===1?'length':'stop')}};
 await model.complete([{role:'user',content:'Create an image'}],d=>output.push(d));assert.equal(JSON.parse(output.join('').split('```studio\n')[1].split('\n```')[0]).settings.prompt,'A scene with trees');assert.match(calls[1].messages.at(-1).content,/preserving its syntax/);
});
