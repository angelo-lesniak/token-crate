// Exercise installed session writers/readers across a container restart.
import assert from 'node:assert/strict';
import fs from 'node:fs';
const agent = process.env.TOKENCRATE_AGENT;
const modulePath = agent === 'pi'
  ? '/usr/local/lib/node_modules/@earendil-works/pi-coding-agent/dist/core/session-manager.js'
  : '/usr/local/bun/install/global/node_modules/@oh-my-pi/pi-coding-agent/src/session/session-manager.ts';
const {SessionManager} = await import(modulePath);
const pathFile = `${process.cwd()}/session-path-${agent}`;
const image = Buffer.from('retained image payload'.repeat(100)).toString('base64');
if (!fs.existsSync(pathFile)) {
  const manager = SessionManager.create(process.cwd());
  manager.appendMessage({role:'user', content:[{type:'text', text:'retained conversation'},
    {type:'image', mimeType:'image/png', data:image}], timestamp:Date.now()});
  // pi waits for an assistant response before writing a session file.
  manager.appendMessage({role:'assistant', content:[{type:'text',text:'saved reply'}],
    api:'openai-completions',provider:'tokencrate',model:'home-check',stopReason:'stop',
    usage:{input:1,output:1,cacheRead:0,cacheWrite:0,totalTokens:2,
      cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},timestamp:Date.now()});
  await manager.flush?.();
  fs.writeFileSync(pathFile, manager.getSessionFile());
  await manager.close?.();
}
const file = fs.readFileSync(pathFile,'utf8');
assert.ok(file.startsWith(`/home/agent/.${agent}/agent/sessions/`),file);
const opened = await SessionManager.open(file);
const context = opened.buildSessionContext();
assert.equal(context.messages[0].content[0].text,'retained conversation');
assert.equal(context.messages[0].content[1].data,image);
assert.equal(context.messages[1].content[0].text,'saved reply');
await opened.close?.();
if (agent === 'omp') {
  assert.match(fs.readFileSync(file,'utf8'),/blob:sha256:/);
  assert.ok(fs.readdirSync('/home/agent/.omp/agent/blobs').length);
}
console.log(`PASS ${agent}: saved session reopens with text and image data`);
