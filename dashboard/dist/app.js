
const $=s=>document.querySelector(s);
const modes=['all','greplet','spec','tierwork'];
let data,mode=modes.includes(location.hash.slice(1))?location.hash.slice(1):'all',busy=false,paused=false,selected='',requestId=0,lastHtml='',lastEvents=new Set();
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>v!=null&&v!==''&&Number.isFinite(Number(v))?Number(v).toLocaleString('ko-KR'):'—';
const date=v=>v&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';
const tag=(v,w=false)=>'<span class="badge '+(w?'warn':'')+'">'+esc(v)+'</span>';
const empty=v=>'<p class="empty">'+esc(v||'표시할 기록이 없습니다.')+'</p>';
const table=(heads,rows)=>rows.length?'<div class="table-wrap"><table><thead><tr>'+heads.map(h=>'<th scope="col">'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>':empty();
const panel=(title,body,meta='')=>'<section class="panel"><div class="section-head"><h2>'+title+'</h2><span class="muted">'+esc(meta)+'</span></div>'+body+'</section>';
const metric=(name,value,sub)=>'<div class="metric-cell"><label>'+esc(name)+'</label><strong>'+esc(value)+'</strong><small>'+esc(sub)+'</small></div>';
const ws=()=>Array.isArray(data.greplet.workspaces.data)?data.greplet.workspaces.data:[];
const searches=()=>Array.isArray(data.greplet.activity.data?.recent)?data.greplet.activity.data.recent:[];
const state=r=>r.status==null||r.status==='done'?'완료 기록':r.status==='running'?'시작 기록':'미확인';
const doc=name=>'<button class="doc" data-doc="'+esc(name)+'">'+esc(name)+'</button>';
function total(rows,key){const valid=rows.filter(r=>typeof r[key]==='number'&&Number.isFinite(r[key])&&r[key]>=0);return {value:valid.length?num(valid.reduce((n,r)=>n+r[key],0)):'—',count:valid.length};}
function events(){return [...searches().slice(0,8).map(r=>({id:'g'+r.id,time:r.ts,tool:'GREPLET',kind:'search',text:esc(r.query),note:num(r.hits)+' hits · '+num(r.ms)+' ms'})),...data.spec.documents.slice(0,8).map(d=>({id:'s'+d.name+d.modified,time:d.modified,tool:'SPEC',kind:'file',text:doc(d.name),note:'파일 수정'})),...data.tierwork.rows.slice(0,8).map(r=>({id:'t'+r.session_id+r.agent_id+r.ts,time:r.ts,tool:'TIERWORK',kind:'agent',text:esc(r.description||r.agent_type||r.agent_id),note:state(r)}))].sort((a,b)=>(Date.parse(b.time)||0)-(Date.parse(a.time)||0)).slice(0,12);}
function feed(){const list=events();return panel('활동 스트림',list.length?'<div class="feed">'+list.map(e=>'<article class="event" data-event="'+esc(e.id)+'"><time>'+esc(date(e.time))+'</time><span class="event-tool '+e.kind+'">'+e.tool+'</span><div><div class="event-text">'+e.text+'</div><small>'+esc(e.note)+'</small></div></article>').join('')+'</div>':empty(),'최근 12건 · 원본 시각 기준');}
function overview(){const g=data.greplet,s=data.spec,t=data.tierwork;
const stages=[['01','greplet','GREPLET','근거 검색',g.workspaces.error?'—':num(ws().length),'워크스페이스',g.status.error?'API 연결 안 됨':'API 연결됨',!!g.status.error,'인덱싱 '+num(ws().filter(w=>w.indexing).length)+'개'],['02','spec','LEGACY SPEC','스펙 문서화',s.error?'—':num(s.documents.length),'결과 파일',s.error?'경로 확인 필요':'로컬 결과 읽음',!!s.error,'인용 · 검증 기록'],['03','tierwork','TIERWORK','위임 · 검증',t.logs.every(l=>l.error)?'—':num(t.rows.length),'작업 기록',t.logs.every(l=>l.error)?'로그 없음':'로그 읽음',t.logs.every(l=>l.error),'완료 기록 '+num(t.rows.filter(r=>state(r)==='완료 기록').length)+'건']];
const flow=panel('작업 흐름','<div class="workflow">'+stages.map(([i,m,name,role,n,unit,status,w,detail])=>'<article class="lane '+m+'"><div class="lane-top"><span>'+i+' / '+name+'</span><span class="lane-port" aria-hidden="true"></span></div><h3>'+role+'</h3><div class="lane-number">'+n+'<small>'+unit+'</small></div>'+tag(status,w)+'<p>'+esc(detail)+'</p><button data-mode="'+m+'">상세 보기 <span aria-hidden="true">↗</span></button></article>').join('')+'</div><div class="flow-note">'+tag('연결 미확인',true)+'<span>공통 작업 ID가 없어 각 단계의 결과를 독립적으로 표시합니다.</span></div>','SEARCH → SPEC → VERIFY');
const running=t.rows.filter(r=>r.status==='running');
const attention=panel('기록 상태','<div class="status-list"><div><span>Greplet 인덱싱</span><strong>'+ (g.workspaces.error?'—':num(ws().filter(w=>w.indexing).length))+'</strong></div><div><span>Tierwork 시작 기록</span><strong>'+num(running.length)+'</strong></div><div><span>감사 로그 손상 행</span><strong>'+num(s.malformed)+'</strong></div><div><span>제외된 작업 기록</span><strong>'+num(t.skipped)+'</strong></div></div><p class="muted">시작 기록은 마지막 훅 상태입니다. 현재 실행 중이라는 뜻은 아닙니다.</p><details><summary>데이터 연결 정보</summary><p class="path">'+esc(s.dir)+'</p>'+t.logs.map(l=>'<p class="path">'+esc(l.path)+'<br>'+esc(l.error||'읽기 성공')+' · 손상 '+l.malformed+'행</p>').join('')+'<p>'+esc(g.status.error||'Greplet API 응답 확인')+'</p></details>');
return flow+'<div class="columns">'+feed()+attention+'</div>';}
function greplet(){const g=data.greplet,w=ws();return '<div class="metrics">'+metric('워크스페이스',g.workspaces.error?'—':num(w.length),'등록된 검색 범위')+metric('인덱스 파일',g.workspaces.error?'—':total(w,'files').value,'워크스페이스 합계')+metric('검색 청크',g.workspaces.error?'—':total(w,'chunks').value,'저장된 검색 단위')+metric('인덱싱 중',g.workspaces.error?'—':num(w.filter(r=>r.indexing).length),'현재 API 응답')+'</div>'+panel('워크스페이스 인덱스',g.workspaces.error?empty(g.workspaces.error):table(['워크스페이스','파일 / 청크','상태','마지막 인덱싱'],w.map(r=>['<strong>'+esc(r.label||r.slug)+'</strong><br><small>'+esc(r.slug)+' · '+esc(r.kind)+'</small>',num(r.files)+' / '+num(r.chunks),tag(r.indexing?'인덱싱 중':'대기',!!r.indexing),esc(date(r.lastRun))])))+'<div class="columns">'+panel('최근 검색',g.activity.error?empty(g.activity.error):table(['검색어','모드','결과','소요 시간'],searches().slice(0,20).map(r=>[esc(r.query)+'<br><small>'+esc(date(r.ts))+'</small>',esc(r.mode),r.error?tag('오류',true):num(r.hits),num(r.ms)+' ms'])))+panel('서비스 상태','<div class="status-list"><div><span>API</span>'+tag(g.status.error?'연결 안 됨':'연결됨',!!g.status.error)+'</div><div><span>Ollama</span>'+tag(g.status.error?'미확인':g.status.data?.ollama?.ok?'연결됨':'연결 안 됨',!g.status.data?.ollama?.ok)+'</div><div><span>Extractor</span>'+tag(g.status.error?'미확인':g.status.data?.extractor?.ok?'사용 가능':'사용 불가',!g.status.data?.extractor?.ok)+'</div></div><p><a href="'+esc(g.url)+'" target="_blank" rel="noreferrer">Greplet 원본 화면 ↗</a></p>')+'</div>';}
function spec(){const s=data.spec;return '<div class="columns docs-layout">'+panel('문서 라이브러리',s.error?empty(s.error):'<div class="files">'+s.documents.map(d=>'<button class="file" data-doc="'+esc(d.name)+'" aria-pressed="'+(selected===d.name)+'"><span class="file-type">'+esc(d.name.split('.').pop().toUpperCase())+'</span><strong>'+esc(d.name)+'</strong><small>'+num(Math.ceil(d.bytes/1024))+' KB · '+esc(date(d.modified))+'</small></button>').join('')+'</div><p class="muted">파일을 선택하면 아래에서 원문을 읽을 수 있습니다.</p>',num(s.documents.length)+'개 결과 파일')+panel('인용 · 검증 기록','<p class="muted">기존 감사 기록이며 현재 코드에 대한 재검증 결과는 아닙니다.</p>'+(s.auditError?empty(s.auditError):s.audit.slice(0,12).map(r=>'<article class="audit"><strong>'+esc(r.item_id||r.document)+'</strong><p>'+esc(r.evidence)+'</p>'+tag(r.action)+'<small> '+esc(date(r.timestamp))+'</small></article>').join('')||empty()),'최근 12건')+'</div>';}
function tierwork(){const t=data.tierwork,rows=t.rows,input=total(rows,'input_tokens'),output=total(rows,'output_tokens'),sessions=new Map();for(const r of rows)sessions.set(r.session_id,(sessions.get(r.session_id)||0)+1);return '<div class="metrics">'+metric('에이전트 기록',t.logs.every(l=>l.error)?'—':num(rows.length),'세션 + 에이전트별 최신 상태')+metric('완료 기록',num(rows.filter(r=>state(r)==='완료 기록').length),'프로세스 상태 아님')+metric('입력 토큰',input.value,input.count+' / '+rows.length+'건에 값 있음')+metric('출력 토큰',output.value,output.count+' / '+rows.length+'건에 값 있음')+'</div><div class="columns">'+panel('에이전트 작업',table(['작업','기록 상태','입력 / 출력','판정'],rows.slice(0,60).map(r=>['<strong>'+esc(r.description||r.agent_type||r.agent_id)+'</strong><br><small>'+esc(r.agent_type)+' · '+esc(date(r.ts))+'</small>',tag(state(r),r.status==='running'),num(r.input_tokens)+' / '+num(r.output_tokens),esc(r.verdict)])),'최신 60건')+panel('세션별 작업','<p class="muted">훅에 남은 마지막 상태입니다. 실행 여부는 원본 도구에서 확인하세요.</p>'+[...sessions].slice(0,10).map(([id,n])=>'<div class="session"><code>'+esc(id)+'</code><p>'+n+'개 에이전트</p></div>').join('')+'<details><summary>로그 연결 정보</summary>'+t.logs.map(l=>'<p class="path">'+esc(l.path)+'<br>'+esc(l.error||'읽기 성공')+'</p>').join('')+'<p>제외 기록 '+t.skipped+'건</p></details>')+'</div>';}
function render(){const titles={all:['작업 관제','근거 검색부터 문서화와 검증까지, 각 도구의 활동을 확인합니다.'],greplet:['Greplet / 검색 관제','워크스페이스 인덱스와 최근 검색 활동'],spec:['Legacy Spec / 문서 작업','생성 문서와 인용 · 검증 근거'],tierwork:['Tierwork / 에이전트 작업','작업 기록과 토큰 사용량 · 검증 판정']};$('#title').textContent=titles[mode][0];$('#subtitle').textContent=titles[mode][1];document.title='Plugin Desk · '+titles[mode][0];document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
const html=mode==='all'?overview():mode==='greplet'?greplet():mode==='spec'?spec():tierwork();if(html===lastHtml)return;
const focused=document.activeElement,focusDoc=focused?.dataset?.doc,focusMode=focused?.dataset?.mode;const opened=[...$('#content').querySelectorAll('details')].map(d=>d.open);const scrolls=[...$('#content').querySelectorAll('.table-wrap')].map(e=>e.scrollLeft);
$('#content').innerHTML=html;lastHtml=html;$('#content').querySelectorAll('details').forEach((d,i)=>d.open=opened[i]||false);$('#content').querySelectorAll('.table-wrap').forEach((d,i)=>d.scrollLeft=scrolls[i]||0);
if(focusDoc)[...$('#content').querySelectorAll('[data-doc]')].find(b=>b.dataset.doc===focusDoc)?.focus({preventScroll:true});else if(focusMode&&focused.closest('#content'))$('#content').querySelector('[data-mode="'+focusMode+'"]')?.focus({preventScroll:true});
const current=new Set();$('#content').querySelectorAll('[data-event]').forEach(e=>{current.add(e.dataset.event);if(lastEvents.size&&!lastEvents.has(e.dataset.event))e.classList.add('arrived');});if(mode==='all')lastEvents=current;}
async function refresh(){if(busy)return;busy=true;$('#refresh').disabled=true;try{const r=await fetch('/api/snapshot');if(!r.ok)throw Error('HTTP '+r.status);data=await r.json();enqueueRunner(collectRunnerEvents(data));render();$('#updated').textContent='마지막 수집 '+date(data.updated);$('#error').hidden=true;}catch(e){$('#error').hidden=false;$('#error').textContent='갱신 실패 · '+e.message+'. 기존 화면은 마지막 수집 결과입니다.';}finally{busy=false;$('#refresh').disabled=false;}}
function change(next){mode=modes.includes(next)?next:'all';requestId++;selected='';$('#reader').hidden=true;lastHtml='';if(data)render();}
window.addEventListener('hashchange',()=>change(location.hash.slice(1)));
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.mode){if(location.hash!=='#'+b.dataset.mode)location.hash=b.dataset.mode;return;}if(!b.dataset.doc)return;selected=b.dataset.doc;const id=++requestId;$('#reader').hidden=false;$('#doc-title').textContent=selected;$('#doc-body').textContent='문서를 읽고 있습니다…';render();$('#doc-title').setAttribute('tabindex','-1');$('#doc-title').focus({preventScroll:true});$('#reader').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});try{const r=await fetch('/api/document?name='+encodeURIComponent(selected));const text=await r.text();if(!r.ok)throw Error(text);if(id===requestId)$('#doc-body').textContent=text;}catch(err){if(id===requestId)$('#doc-body').textContent=err.message;}});
$('#refresh').onclick=refresh;$('#close').onclick=()=>{requestId++;$('#reader').hidden=true;[...$('#content').querySelectorAll('[data-doc]')].find(b=>b.dataset.doc===selected)?.focus();};$('#pause').onclick=()=>{paused=!paused;$('#pause').textContent=paused?'자동 갱신 꺼짐':'자동 갱신 켜짐';$('#pause').setAttribute('aria-pressed',String(paused));$('footer').textContent=paused?'자동 갱신 일시 정지 · 마지막 수집 결과 표시':'5초마다 자동 갱신 · 로컬 API와 파일 기반 조회';if(!paused)refresh();};refresh();setInterval(()=>{if(!paused&&!document.hidden)refresh();},5000);document.addEventListener('visibilitychange',()=>{if(!paused&&!document.hidden)refresh();});

/* Event Runner: baseline each source independently; polling history never becomes a demo event. */
const runnerSeen = {greplet:new Set(), spec:new Set(), tierwork:new Set()};
const runnerReady = new Set();
function collectRunnerEvents(snapshot) {
  const groups = [
    ['greplet', !snapshot.greplet.activity.error, (snapshot.greplet.activity.data?.recent || []).map(r=>({key:JSON.stringify([r.id,r.ts]),label:'GREPLET · 검색',time:r.ts}))],
    ['spec', !snapshot.spec.error, snapshot.spec.documents.map(r=>({key:JSON.stringify([r.name,r.modified]),label:'SPEC · '+r.name,time:r.modified}))],
    ['tierwork', snapshot.tierwork.logs.some(l=>!l.error), snapshot.tierwork.rows.map(r=>({key:JSON.stringify([r.session_id,r.agent_id,r.ts,r.status??'done']),label:'TIERWORK · '+(r.status==='running'?'시작 기록':'작업 기록'),time:r.ts}))]
  ];
  const fresh=[];
  for(const [source,ok,rows] of groups){
    if(!ok)continue;
    for(const r of rows){if(runnerReady.has(source)&&!runnerSeen[source].has(r.key))fresh.push(r);runnerSeen[source].add(r.key);}
    runnerReady.add(source);
  }
  return fresh.sort((a,b)=>(Date.parse(a.time)||0)-(Date.parse(b.time)||0));
}
const runnerCanvas = $('#runner');
const runnerContext = runnerCanvas?.getContext?.('2d');
let runnerQueue=[], runnerCurrent=null, runnerCount=0, runnerStart=null, runnerFrame=null;
const dinosaur=['0000000011111110','0000000011110111','0000000011111111','0000000011110000','1000000111111100','1100011111100000','1111111111110000','0111111111011000','0011111111000000','0001111110000000','0000110110000000','0000110011000000'];
function paintRunner(progress=0, active=false, time=0) {
  if(!runnerContext)return;
  const c=runnerContext,w=1200,h=160,ground=126,x=140;
  c.clearRect(0,0,w,h);c.fillStyle='#12191f';c.fillRect(0,0,w,h);
  c.strokeStyle='#3b4b46';c.lineWidth=1;c.beginPath();c.moveTo(0,ground+1);c.lineTo(w,ground+1);c.stroke();
  c.fillStyle='#455247';for(let i=0;i<30;i++)c.fillRect((i*47-(time*.18)%w+w)%w,ground+10+(i%3)*4,6+(i%4)*3,1);
  const jump=active&&progress>.29&&progress<.85?Math.sin((progress-.29)/.56*Math.PI)*70:0;
  const stride=Math.floor(time/110)%2;
  const bob=jump?0:stride*2;
  c.fillStyle='#c9e999';dinosaur.forEach((row,dy)=>[...row].forEach((pixel,dx)=>{if(pixel==='1'&&(jump||dy<10))c.fillRect(x+dx*4,ground-48-jump+dy*4-bob,4,4);}));
  if(!jump){c.fillRect(x+16,ground-9-bob,4,stride?5:9);c.fillRect(x+16,ground-(stride?6:3)-bob,8,3);c.fillRect(x+28,ground-9-bob,4,stride?9:5);c.fillRect(x+28,ground-(stride?3:6)-bob,8,3);}
  if(active){const obstacleX=1060-progress*1620;c.fillStyle=runnerCurrent?.demo?'#bca4e1':'#91b5d3';c.fillRect(obstacleX,ground-26,23,26);c.fillStyle='#182330';c.fillRect(obstacleX+5,ground-20,13,3);c.fillRect(obstacleX+5,ground-13,8,3);}
  c.font='11px Consolas, monospace';c.fillStyle='#8faaa0';c.fillText('01 / RECEIVE',320,30);c.fillText('02 / JUMP',640,30);c.fillText('03 / CONTINUE',980,30);
}
function runnerTick(time){
  runnerFrame=null;
  if(document.hidden){runnerStart=null;return;}
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){paintRunner();return;}
  if(!runnerCurrent){runnerCurrent=runnerQueue.shift();runnerStart=null;if(!runnerCurrent){paintRunner(0,false,time);runnerFrame=requestAnimationFrame(runnerTick);return;}}
  if(runnerStart===null)runnerStart=time;
  const progress=Math.min(1,(time-runnerStart)/1100);
  $('#runner-note').textContent=(runnerCurrent.demo?'미리보기 · ': '')+runnerCurrent.label+(runnerQueue.length?' · 대기 '+runnerQueue.length+'개':'');
  paintRunner(progress,true,time);
  if(progress===1){runnerCount++;$('#runner-score').textContent=String(runnerCount).padStart(4,'0');runnerCurrent=null;runnerStart=null;if(!runnerQueue.length){$('#runner-note').textContent='달리는 중 · 새 활동을 기다립니다';}}
  runnerFrame=requestAnimationFrame(runnerTick);
}
function enqueueRunner(rows){
  if(!runnerContext||!rows.length)return;
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){$('#runner-score').textContent=String(runnerCount).padStart(4,'0');$('#runner-note').textContent='동작 줄이기 설정 · '+rows.length+'개 기록 수신';paintRunner();return;}
  runnerQueue.push(...rows);if(runnerFrame===null&&!document.hidden)runnerFrame=requestAnimationFrame(runnerTick);
}
if(runnerContext){
  paintRunner();$('#runner-demo').onclick=()=>enqueueRunner([{label:'점프 테스트',demo:true}]);
  if(!document.hidden)runnerFrame=requestAnimationFrame(runnerTick);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&runnerFrame===null)runnerFrame=requestAnimationFrame(runnerTick);});
}

if(runnerContext){ $('#runner-reset').onclick=()=>{runnerCount=0;$('#runner-score').textContent='0000';}; }
