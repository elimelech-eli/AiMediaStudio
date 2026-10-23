const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const ctx={Map,JSON,localStorage:{setItem(){throw Error('Storage unavailable');}}};vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/studio-chat-cards.js','utf8'),ctx);
test('internal creation JSON is hidden while normal prose and proposed settings survive',()=>{
 const reply=ctx.parseStudioReply('Here is the image I suggest.\n```studio\n{"engine":"image","settings":{"prompt":"A ladybug","width":768,"height":768,"proposal_workspace":"project-a","context_revision":3}}\n```');assert.equal(reply.text,'Here is the image I suggest.');assert.equal(reply.proposals[0].settings.prompt,'A ladybug');assert.equal(reply.proposals[0].settings.proposal_workspace,'project-a');assert.equal(reply.proposals[0].settings.context_revision,3);
});
test('JSON-labeled and bare creation proposals work, ordinary JSON remains visible',()=>{
 const proposal='{"engine":"video","settings":{"prompt":"A wave"}}';assert.equal(ctx.parseStudioReply('```json\n'+proposal+'\n```').text,'');assert.equal(ctx.parseStudioReply(proposal).proposals.length,1);assert.match(ctx.parseStudioReply('```json\n{"example":true}\n```').text,/example/);
});
test('broken tool syntax becomes an actionable notice instead of raw machine JSON',()=>{
 const reply=ctx.parseStudioReply('Let me prepare it.\n```studio\n{broken}\n```');assert.equal(reply.invalid,true);assert.equal(reply.text,'Let me prepare it.');assert.equal(reply.proposals.length,0);assert.match(ctx.creationError('[WinError 5] Access is denied'),/Windows blocked/);const truncated=ctx.parseStudioReply('Preparing…\n```studio\n{broken');assert.equal(truncated.invalid,true);assert.equal(truncated.text,'Preparing…');
});
test('blocked browser storage never turns a submitted generation into a failure',()=>{assert.doesNotThrow(()=>ctx.saveCreation('key',{job:{id:'running'},proposal:{engine:'image'}}));});
