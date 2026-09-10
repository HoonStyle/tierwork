import {test} from 'node:test';
import assert from 'node:assert/strict';
import {latestRows} from './server.mjs';
test('new start supersedes older completion, completed wins time tie',()=>{
 const row=(ts,status)=>({session_id:'s',agent_id:'a',ts,status});
 assert.equal(latestRows([row('2026-01-01','done'),row('2026-01-02','running')]).rows[0].status,'running');
 assert.equal(latestRows([row('2026-01-01','done'),row('2026-01-01','running')]).rows[0].status,'done');
});
test('invalid identity, timestamp and future records cannot become active work',()=>{
 const result=latestRows([{session_id:'s',agent_id:'a',ts:'2999-01-01'},{ts:'2026-01-01'},{session_id:'s',agent_id:'a',ts:'bad'}]);assert.equal(result.rows.length,0);assert.equal(result.skipped,3);
});
