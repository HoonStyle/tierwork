import {test} from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import {latestRows, resolveSpecDir} from './server.mjs';
test('new start supersedes older completion, completed wins time tie',()=>{
 const row=(ts,status)=>({session_id:'s',agent_id:'a',ts,status});
 assert.equal(latestRows([row('2026-01-01','done'),row('2026-01-02','running')]).rows[0].status,'running');
 assert.equal(latestRows([row('2026-01-01','done'),row('2026-01-01','running')]).rows[0].status,'done');
});
test('invalid identity, timestamp and future records cannot become active work',()=>{
 const result=latestRows([{session_id:'s',agent_id:'a',ts:'2999-01-01'},{ts:'2026-01-01'},{session_id:'s',agent_id:'a',ts:'bad'}]);assert.equal(result.rows.length,0);assert.equal(result.skipped,3);
});

test('spec directory CLI, environment and config precedence uses each source base',()=>{
 const cwd=path.resolve('fixtures','cli-cwd');
 const configDir=path.resolve('fixtures','config-dir');
 assert.equal(resolveSpecDir('from-config',[],{},cwd,configDir),path.resolve(configDir,'from-config'));
 assert.equal(resolveSpecDir('from-config',[],{TIERWORK_SPEC_DIR:'from-env'},cwd,configDir),path.resolve(cwd,'from-env'));
 assert.equal(resolveSpecDir('from-config',['--spec-dir','from-cli'],{TIERWORK_SPEC_DIR:'from-env'},cwd,configDir),path.resolve(cwd,'from-cli'));
});

test('spec directory expands home and rejects malformed CLI options',()=>{
 const cwd=path.resolve('fixtures','cli-cwd');
 const configDir=path.resolve('fixtures','config-dir');
 assert.equal(resolveSpecDir('ignored',['--spec-dir','~/specs'],{},cwd,configDir),path.resolve(os.homedir(),'specs'));
 assert.throws(()=>resolveSpecDir('fallback',['--spec-dir'],{},cwd,configDir));
 assert.throws(()=>resolveSpecDir('fallback',['--spec-dir',''],{},cwd,configDir));
 assert.throws(()=>resolveSpecDir('fallback',['--spec-dir','one','--spec-dir','two'],{},cwd,configDir));
 assert.throws(()=>resolveSpecDir('fallback',['--unknown'],{},cwd,configDir));
});
