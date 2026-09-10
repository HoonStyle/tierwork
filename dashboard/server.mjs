import http from 'node:http';
import {readFile, readdir, stat, realpath} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
export function latestRows(rows, now=Date.now()) {
  const map=new Map(); let skipped=0;
  for(const r of rows){
    const t=Date.parse(r.ts); if(typeof r.session_id!=='string'||!r.session_id.trim()||typeof r.agent_id!=='string'||!r.agent_id.trim()||!Number.isFinite(t)||t>now){skipped++;continue;}
    const key=JSON.stringify([r.session_id,r.agent_id]), old=map.get(key);
    const done=r.status==null||r.status==='done';
    if(!old||t>Date.parse(old.ts)||(t===Date.parse(old.ts)&&(done||!(old.status==null||old.status==='done'))))map.set(key,r);
  }
  return {rows:[...map.values()].sort((a,b)=>Date.parse(b.ts)-Date.parse(a.ts)),skipped};
}
const resolve=p=>path.resolve(root,p.startsWith('~/')?path.join(os.homedir(),p.slice(2)):p);
async function jsonl(file){
  try {const body=await readFile(file,'utf8'); let malformed=0;const rows=[];
    for(const line of body.split(/\r?\n/)){if(!line.trim())continue;try{const r=JSON.parse(line);if(r&&typeof r==='object'&&!Array.isArray(r))rows.push(r);else malformed++;}catch{malformed++;}}
    return {rows,malformed,error:null};
  }catch(e){return {rows:[],malformed:0,error:e.code==='ENOENT'?'파일 없음':e.message};}
}
async function remote(base,route){try{const res=await fetch(new URL(route,base),{signal:AbortSignal.timeout(3500),redirect:'error'});if(!res.ok)throw Error(`HTTP ${res.status}`);return {data:await res.json(),error:null};}catch(e){return {data:null,error:e.message};}}
export async function snapshot(config){
  const [status,workspaces,activity]=await Promise.all(['/api/status','/api/workspaces','/api/activity'].map(r=>remote(config.grepletUrl,r)));
  const dir=resolve(config.specDir);let documents=[],specError=null;
  try{for(const entry of await readdir(dir,{withFileTypes:true})){if(entry.isFile()&&/\.(md|html|json|jsonl)$/i.test(entry.name)){const s=await stat(path.join(dir,entry.name));documents.push({name:entry.name,bytes:s.size,modified:s.mtime.toISOString()});}}documents.sort((a,b)=>b.modified.localeCompare(a.modified));}catch(e){specError=e.message;}
  const audit=await jsonl(path.join(dir,'audit_log.jsonl'));
  const logs=await Promise.all(config.tierworkLogs.map(async p=>({path:resolve(p),...await jsonl(resolve(p))})));
  const merged=latestRows(logs.flatMap(l=>l.rows));
  return {updated:new Date().toISOString(),greplet:{url:config.grepletUrl,status,workspaces,activity},spec:{dir,documents,error:specError,audit:audit.rows.slice(-30).reverse(),auditError:audit.error,malformed:audit.malformed},tierwork:{...merged,logs:logs.map(({path,error,malformed})=>({path,error,malformed}))}};
}
async function main(){
 const config=JSON.parse(await readFile(path.join(root,'config.json'),'utf8'));
 const upstream=new URL(config.grepletUrl);if(!['127.0.0.1','localhost','[::1]'].includes(upstream.hostname)||upstream.protocol!=='http:')throw Error('grepletUrl must be local HTTP');
 let cached=null,pending=null;
 const server=http.createServer(async(req,res)=>{
  const send=(code,type,body)=>{res.writeHead(code,{'Content-Type':type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"});res.end(body);};
  if(![`127.0.0.1:${config.port}`,`localhost:${config.port}`].includes(req.headers.host))return send(403,'text/plain','Invalid host');
  if(req.method!=='GET')return send(405,'text/plain','Read only');
  try{const url=new URL(req.url,'http://localhost');
   if(url.pathname==='/api/snapshot'){
    if(!cached||Date.now()-cached.time>3000){pending??=snapshot(config).then(data=>(cached={data,time:Date.now()})).finally(()=>pending=null);await pending;}
    return send(200,'application/json; charset=utf-8',JSON.stringify(cached.data));
   }
   if(url.pathname==='/api/document'){
    const name=url.searchParams.get('name')||'';
    if(name!==path.basename(name)||! /\.(md|html|json|jsonl)$/i.test(name))return send(400,'text/plain','Invalid document');
    const dir=await realpath(resolve(config.specDir)),file=await realpath(path.join(dir,name));
    if(path.dirname(file)!==dir)return send(403,'text/plain','Outside configured directory');
    if((await stat(file)).size>2*1024*1024)return send(413,'text/plain','문서가 2 MB를 초과합니다. 로컬 파일에서 확인하세요.');
    return send(200,'text/plain; charset=utf-8',await readFile(file,'utf8'));
   }
   const assets={'/':['index.html','text/html; charset=utf-8'],'/app.js':['app.js','text/javascript; charset=utf-8'],'/style.css':['style.css','text/css; charset=utf-8']};
   if(!assets[url.pathname])return send(404,'text/plain','Not found');
   const [file,type]=assets[url.pathname];send(200,type,await readFile(path.join(root,'dist',file)));
  }catch(e){send(500,'text/plain; charset=utf-8',e.message);}
 });server.listen(config.port,'127.0.0.1',()=>console.log(`http://127.0.0.1:${config.port}`));
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))await main();
