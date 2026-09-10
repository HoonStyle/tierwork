import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {test} from 'node:test';
import assert from 'node:assert/strict';
const code=await readFile(new URL('./dist/app.js',import.meta.url),'utf8');
test('runner ignores initial history, deduplicates polls, and queues each new record',()=>{
 const start=code.indexOf('const runnerSeen');
 const end=code.indexOf('const runnerCanvas');
 const context=vm.createContext({});
 vm.runInContext(code.slice(start,end),context);
 const collect=d=>{context.snapshot=d;return vm.runInContext('collectRunnerEvents(snapshot)',context);};
 const d=structuredClone(fixture);
 assert.equal(collect(d).length,0);
 assert.equal(collect(d).length,0);
 d.greplet.activity.data.recent.push({id:'2',ts:'2026-09-10T02:00:00Z'},{id:'3',ts:'2026-09-10T02:00:01Z'});
 assert.equal(collect(d).length,2);
 assert.equal(collect(d).length,0);
 d.spec.documents[0].modified='2026-09-10T03:00:00Z';
 assert.equal(collect(d).length,1);
});
const fixture={updated:'2026-09-10T01:00:00Z',greplet:{url:'http://127.0.0.1:7802',status:{data:{ollama:{ok:true},extractor:{ok:true}},error:null},workspaces:{data:[{slug:'source',label:'Source',files:2,chunks:6}],error:null},activity:{data:{recent:[{id:'1',query:'<script>bad</script>',hits:2,ms:10,ts:'2026-09-10T01:00:00Z'}]},error:null}},spec:{documents:[{name:'SPEC.md',bytes:100,modified:'2026-09-10T01:00:00Z'}],audit:[],error:null,auditError:null,malformed:0,dir:'example'},tierwork:{rows:[{session_id:'s',agent_id:'a',ts:'2026-09-10T01:00:00Z',status:'running',input_tokens:null}],logs:[{path:'example',error:null}],skipped:0}};
async function render(mode,data){const elements=new Map();const element=()=>({innerHTML:'',textContent:'',dataset:{},setAttribute(){},querySelectorAll(){return [];},querySelector(){return null;}});const document={hidden:false,querySelector(s){if(!elements.has(s))elements.set(s,element());return elements.get(s);},querySelectorAll(){return [];},addEventListener(){}};
 vm.runInNewContext(code,{document,location:{hash:'#'+mode},window:{addEventListener(){}},fetch:async()=>({ok:true,json:async()=>data}),setInterval(){},console});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(elements.get('#error')?.hidden,true);return elements.get('#content').innerHTML;}
for(const mode of ['all','greplet','spec','tierwork'])test(mode+' renders real contract without raw HTML injection',async()=>{const html=await render(mode,fixture);assert.ok(html.length>100);assert.ok(!html.includes('<script>bad</script>'));});
test('partial service failures render without discarding local results',async()=>{const d=structuredClone(fixture);for(const key of ['status','workspaces','activity'])d.greplet[key]={error:'offline',data:null};for(const mode of ['all','greplet','spec','tierwork'])assert.ok((await render(mode,d)).length>100);});
