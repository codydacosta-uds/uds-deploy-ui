'use strict';
// Shared Apache-2.0 deployment viewer UI; source/asset notices accompany each distribution.
// All lifecycle/operation data comes from the normalized execution model.
// Raw text is used only for display and literal log search, never to infer state.
const $ = id => document.getElementById(id);
const api = new URL('api/deployments', location.href).pathname;
const MAX_ROWS = 1500, MAX_TIMELINE = 200, LOG_PAGE = 500, MAX_HIGHLIGHTS = 3000;
const liveOnly=document.body.dataset.mode==='live';
let run=null, state=null, selected=null, attempt=null, autoAttempt=true, full=true, rawMode=false;
let stream=null, generation=0, refreshTimer=null, logGeneration=0, searchTimer=null;
let logs=[], logIds=new Set(), pendingRows=[], logTimer=null, pausedNew=0;
let logHistory=false, logEarlier=false, logLater=false, logLoading=false;
let logHighlightCount=0, logHighlightsLimited=false;
let logAnchorId=null, logAnchorLabel='';
const activityLogPositions=new Map();
let componentFilter=null, phaseFilter=null, operationFilter=null, activeRunId=null, discoveredRuns=[];
const disclosure=new Map(), flowScroll=new Map(), componentChoices=new Map(), stepChoices=new Map();
const manualPackages=new Set(), finishedViews=new Set();
let quietFinished=false;try{quietFinished=localStorage.getItem('uds-deploy-quiet-finished')==='true';}catch{}
let graphView='pipeline', graphKey='', wireFrame=null, inspectorOpen=false, grouping='stages';
let pageView='history', historyKey='', initialRoute=true, definitionRequest=0, packageLayout='pipeline', pipelineSelection=null;
const svgNode=(tag)=>document.createElementNS('http://www.w3.org/2000/svg',tag);
const title=value=>value ? value[0].toUpperCase()+value.slice(1) : 'Unknown';
const clock=value=>value ? new Date(value*1000).toLocaleTimeString() : '—';
function elapsed(start,end){if(!start)return '—';const s=Math.max(0,Math.floor((end||Date.now()/1000)-start));return [Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(n=>String(n).padStart(2,'0')).join(':');}
function shortDuration(start,end){if(!start)return '—';const s=Math.max(0,Math.floor((end||Date.now()/1000)-start));return s>=3600?`${Math.floor(s/3600)}h ${Math.floor(s/60)%60}m`:s>=60?`${Math.floor(s/60)}m ${s%60}s`:`${s}s`;}
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function setDisclosure(key,open){const detail=[...document.querySelectorAll('details[data-disclosure]')].find(e=>e.dataset.disclosure===key);if(detail)detail.open=open;disclosure.set(key,open);}
function stepIcon(status){const e=node('span',status==='succeeded'?'✓':status==='failed'?'×':'','step-status-icon '+status);e.setAttribute('aria-hidden','true');return e;}
function statusIcon(status){const e=node('span',['completed','succeeded'].includes(status)?'✓':['failed','cancelled','canceled'].includes(status)?'×':status==='unknown'?'?':status==='skipped'?'−':'',`status-icon ${status}`);e.setAttribute('aria-hidden','true');return e;}
async function request(url,options){const r=await fetch(url,options);if(!r.ok){const data=await r.json();throw Error(data.error||r.statusText);}return r.json();}
function notice(message){$('notice').hidden=!message;$('notice').textContent=message||'';}
function packageState(){return state&&state.packages.find(p=>p.id===selected);}
function selectedAttempt(){return packageState()?.attempts.find(a=>a.id===attempt);}
function selectedExecution(){return selectedAttempt()?.execution||{schema_version:0,components:[],observation:packageState()?.attempts.length?'legacy':'awaiting'};}
function updateActiveLink(){const active=discoveredRuns.find(r=>['waiting','deploying'].includes(r.status));activeRunId=active&&active.id!==run?active.id:null;$('active-run').hidden=!activeRunId;}
function clearScope(){componentFilter=phaseFilter=operationFilter=null;}
function outputFeedState(snapshot,live){
  if(!live)return null;
  if(snapshot.completed_at&&!['waiting','deploying'].includes(snapshot.status))return 'Output ended';
  if(snapshot.source?.activity_available===false&&/^Output capture stopped/.test(snapshot.source.note||''))return 'Capture stopped';
  return null;
}
function logURL(extra=''){
  const path=`${api}/${run}${full?'':'/packages/'+encodeURIComponent(selected)}/logs`;
  const q=new URLSearchParams();if(!full&&attempt)q.set('attempt',attempt);
  if(!full&&componentFilter)q.set('component',componentFilter);
  if(!full&&phaseFilter)q.set('phase',phaseFilter);
  if(!full&&operationFilter)q.set('operation_execution',operationFilter);
  if($('log-search').value)q.set('search',$('log-search').value);
  if($('log-level').value)q.set('level',$('log-level').value);
  return path+'?'+q.toString()+'&'+extra;
}
function acceptsLog(item){
  if(!full&&(item.package!==selected||attempt&&item.attempt!==attempt))return false;
  if(!full&&componentFilter&&item.component!==componentFilter)return false;
  if(!full&&phaseFilter&&item.phase!==phaseFilter)return false;
  if(!full&&operationFilter&&item.operation_execution!==operationFilter)return false;
  if($('log-level').value&&item.data.level!==$('log-level').value)return false;
  return !$('log-search').value||item.data.raw.toLocaleLowerCase().includes($('log-search').value.toLocaleLowerCase());
}
function deploymentURL(id){const url=new URL(location.href);url.searchParams.set('deployment',id);return url;}
function showPage(view,navigate=false){
  pageView=view;
  $('deployments-page').hidden=view!=='history';$('workspace').hidden=view!=='pipeline'||!state;$('empty').hidden=true;
  $('history-switcher').hidden=view!=='pipeline';$('breadcrumb-run').hidden=view!=='pipeline';
  $('nav-deployments').classList.toggle('active',view==='history');$('nav-pipeline').classList.toggle('active',view==='pipeline');
  for(const [id,active]of [['nav-deployments',view==='history'],['nav-pipeline',view==='pipeline']]){if(active)$(id).setAttribute('aria-current','page');else $(id).removeAttribute('aria-current');}
  if(navigate){const url=new URL(location.href);if(view==='history')url.searchParams.delete('deployment');else if(run)url.searchParams.set('deployment',run);window.history.pushState(null,'',url);}
  if(view==='history'){notice('');renderHistory();if(!stream){$('connection').textContent='Local viewer';if(liveOnly)$('connection').className='live';}}else if(state){render();scheduleWires();}
}
function renderHistory(){
  const search=$('deployment-search').value.trim().toLocaleLowerCase(),filter=$('deployment-status').value;
  const items=discoveredRuns.filter(r=>`${r.bundle_name} ${r.version} ${r.environment} ${r.target} ${r.id}`.toLocaleLowerCase().includes(search)&&(!filter||filter==='active'&&['waiting','deploying'].includes(r.status)||filter==='unknown'&&['unknown','cancelled'].includes(r.status)||r.status===filter));
  $('deployment-total').textContent=discoveredRuns.length;
  $('deployment-table-scroll').hidden=items.length===0;
  $('history-empty').hidden=discoveredRuns.length!==0;$('history-note').textContent=liveOnly?'Current local tasks only. No database, saved deployment history, or UI-owned retries.':`${items.length} of ${discoveredRuns.length} saved runs · latest 50 shown. Start deployments from the terminal.`;
  const key=JSON.stringify([discoveredRuns,search,filter]);
  if(key!==historyKey){
    historyKey=key;const rows=document.createDocumentFragment();
    for(const item of items){
      const row=node('tr');row.dataset.run=item.id;
      const status=node('td'),badge=node('span',undefined,`history-status ${item.status}`);badge.append(statusIcon(item.status),node('span',item.status==='deploying'?'Running':title(item.status)));status.append(badge);
      const deployment=node('td'),link=node('a',`${item.bundle_name} ${item.version}`,'deployment-link');link.href=deploymentURL(item.id);link.onclick=e=>{if(e.button===0&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey){e.preventDefault();chooseRun(item.id);}};
      deployment.append(link,node('span',`#${item.id.slice(0,8)} · ${new Date(item.created_at*1000).toLocaleString()}`,'cell-secondary'));
      const target=node('td');target.title=item.target;target.append(node('span',item.environment,'environment-label'),node('span',item.target?.includes(':cluster/')?item.target.split(':cluster/').pop():item.target,'cell-secondary'));
      const packages=node('td'),counts=item.package_counts;
      if(counts){packages.append(node('span',`${counts.completed||0} / ${item.package_count}`,'package-total'));const icons=node('span',undefined,'package-summary');for(const state of ['completed','deploying','waiting','failed','unknown','cancelled'])if(counts[state]){const part=node('span',undefined,'summary-status');part.title=`${counts[state]} ${state}`;part.append(statusIcon(state),node('span',String(counts[state])));icons.append(part);}packages.append(icons);}else packages.append(node('span','See pipeline','muted'));
      if(item.unverified_operations)packages.append(node('span',`${item.unverified_operations} unverified operation${item.unverified_operations===1?'':'s'}`,'cell-secondary warning-text'));
      const duration=node('td',undefined,'duration-cell');duration.dataset.durationRun=item.id;
      const actions=node('td',undefined,'history-actions'),view=node('a','View','table-action');view.href=deploymentURL(item.id);view.setAttribute('aria-label','View deployment '+item.id.slice(0,8));view.onclick=e=>{if(e.button===0&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey){e.preventDefault();chooseRun(item.id);}};
      const download=node('a','↓','table-action download-action');download.href=`${api}/${item.id}/logs?download=1`;download.title='Download original deployment output';download.setAttribute('aria-label','Download logs '+item.id.slice(0,8));download.download='deployment.log';actions.append(view,download);
      row.append(status,deployment,target,packages,duration,actions);rows.append(row);
    }
    if(!items.length&&discoveredRuns.length){const row=node('tr'),cell=node('td','No deployments match these filters.','no-matches');cell.colSpan=6;row.append(cell);rows.append(row);}
    $('deployment-rows').replaceChildren(rows);
  }
  for(const el of document.querySelectorAll('[data-duration-run]')){const item=discoveredRuns.find(r=>r.id===el.dataset.durationRun);el.textContent=item.started_at&&(item.completed_at||item.status==='deploying')?shortDuration(item.started_at,item.completed_at):'—';}
}
async function discover(){try{
  const runs=await request(api);discoveredRuns=runs;const previous=$('history').value;
  renderHistory();
  if(liveOnly){
    const processes=await request(new URL('api/processes',location.href).pathname);
    $('processes').replaceChildren();
    for(const process of processes)$('processes').append(node('p',`${process.tool} ${process.kind} · PID ${process.pid} · process detected; detail available only for task-captured output.`));
    if(initialRoute&&!new URL(location.href).searchParams.has('deployment')&&runs.length){initialRoute=false;await chooseRun((runs.find(r=>r.status==='deploying')||runs[0]).id,false);}
  }
  if(!runs.length){$('connection').textContent='Local viewer ready';$('connection').className=liveOnly?'live':'';return;}
  const key=runs.map(r=>`${r.id}:${r.status}`).join('|');
  if($('history').dataset.optionsKey!==key){$('history').replaceChildren();for(const item of runs){const o=node('option',`${item.environment} / ${item.bundle_name} · ${item.status} · ${new Date(item.created_at*1000).toLocaleString()}`);o.value=item.id;$('history').append(o);}$('history').dataset.optionsKey=key;}
  const active=runs.find(r=>['waiting','deploying'].includes(r.status));updateActiveLink();$('history').value=run||previous||(active||runs[0]).id;
  if(initialRoute){initialRoute=false;let id=new URL(location.href).searchParams.get('deployment');if(liveOnly&&id&&!runs.some(r=>r.id===id)){id=(active||runs[0]).id;window.history.replaceState(null,'',deploymentURL(id));}if(id)await chooseRun(id,false);else showPage('history');}
  else if(liveOnly&&active&&state&&active.id!==run&&!runs.some(r=>r.id===run))await chooseRun(active.id,false);
  else if(state&&(liveOnly||runs.some(item=>item.id===run&&item.status!==state.status)))await refreshState();
}catch(e){notice(e.message);}}
async function chooseRun(id,navigate=true){
  generation++;const mine=generation;if(stream)stream.close();if(refreshTimer){clearTimeout(refreshTimer);refreshTimer=null;}
  run=id;state=null;selected=attempt=null;pipelineSelection=null;autoAttempt=true;full=true;rawMode=liveOnly;inspectorOpen=false;clearScope();$('history').value=id;
  $('connection').textContent='Loading deployment…';$('connection').className='';
  if(navigate)window.history.pushState(null,'',deploymentURL(id));else window.history.replaceState(null,'',deploymentURL(id));updateActiveLink();
  graphView='pipeline';
  try{
    const current=await request(`${api}/${id}`);if(mine!==generation)return;state=current;
    selected=(state.packages.find(p=>p.status==='deploying')||state.packages.find(p=>p.status==='failed')||state.packages[0]).id;
    $('nav-pipeline').disabled=false;$('breadcrumb-run').textContent=`/ ${state.bundle_name}${liveOnly?'':' · #'+state.id.slice(0,8)}`;
    showPage('pipeline');await loadLogs();if(mine!==generation)return;
    stream=new EventSource(`${api}/${id}/events?after=${state.cursor}`);
    stream.onopen=()=>{if(mine!==generation)return;$('connection').textContent='● Live';$('connection').className='live';refreshState(mine);};
    stream.onerror=()=>{$('connection').textContent='Reconnecting · missed events will replay';$('connection').className='';};
    stream.addEventListener('change',event=>{
      if(mine!==generation)return;const item=JSON.parse(event.data);
      if(item.type==='log'){if(acceptsLog(item))queueLog(item);return;}
      if(item.type==='observer.gap'){
        if($('follow').checked)loadLogs().catch(e=>notice(e.message));
        else{$('new-lines').hidden=false;$('new-lines').textContent='New output available';pausedNew++;}
      }
      // Log volume never drives lifecycle refreshes. Only typed/state events do.
      if(!refreshTimer)refreshTimer=setTimeout(()=>{refreshTimer=null;refreshState(mine);},150);
    });notice('');
  }catch(e){notice(e.message);}
}
async function refreshState(mine=generation){try{const current=await request(`${api}/${run}`);if(mine!==generation)return;const old=attempt;state=current;render();if(!full&&old!==attempt)await loadLogs();}catch(e){notice(e.message);}}
function selectPackage(id){selected=id;attempt=null;autoAttempt=true;full=false;inspectorOpen=true;clearScope();render();loadLogs().catch(e=>notice(e.message));$('job-inspector').scrollIntoView({block:'start'});}
// Omit only edges already represented by another dependency path. No runtime
// timing, stage position, or log contents can create an edge.
function directDependencies(packages){
  const byId=new Map(packages.map(p=>[p.id,p])),memo=new Map();
  function ancestors(id){if(!memo.has(id)){const found=new Set();for(const parent of byId.get(id).dependencies){found.add(parent);for(const a of ancestors(parent))found.add(a);}memo.set(id,found);}return memo.get(id);}
  return packages.flatMap(p=>p.dependencies.filter(parent=>!p.dependencies.some(other=>other!==parent&&ancestors(other).has(parent))).map(parent=>({from:parent,to:p.id})));
}
function displayedGroups(){
  if(grouping==='dependencies'&&!liveOnly)return state.pipeline?.groups||[];
  // UDS bundles have packages, not invented GitLab stages. The bundle's own
  // name labels its package list. Task policy must not masquerade as metadata.
  return [{id:0,label:state.bundle_name,packages:state.packages.map(p=>p.id)}];
}
function stageNames(groups){return groups.map(g=>grouping==='stages'||liveOnly?g.label:'Task scheduling');}
function inferSequentialCompletion(state,reports){
  // Presentation-only policy: stock UDS/Zarf executes these operations in one
  // sequential CLI stream. Never alter raw reports or use another process,
  // missing output, elapsed time, or process disappearance as success evidence.
  if(state.source?.kind!=='stock-process'||state.source.output_complete!==true||['concurrent','parallel'].includes(state.mode)||(state.packages||[]).filter(p=>p.status==='deploying').length>1)return reports;
  const errors=reports.filter(r=>r.kind==='deployment.error'||r.message==='action failed'),groups=new Map(),assumptions=new Map();
  const sameOwner=(a,b)=>a&&b&&a.package===b.package&&a.component===b.component;
  const noErrorBetween=(start,end)=>!errors.some(r=>r.timestamp>start&&r.timestamp<=end);
  for(const r of reports){
    if(!r.definition_owner?.component||!r.resource||!['helm.prepare','helm.install','helm.upgrade','health.wait'].includes(r.kind))continue;
    const key=JSON.stringify([r.definition_owner.package,r.definition_owner.component,r.resource]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);
  }
  for(const items of groups.values()){
    if(!items.some(r=>['helm.install','helm.upgrade'].includes(r.kind)))continue;
    const last=items.reduce((a,b)=>b.timestamp>=a.timestamp?b:a),owner=last.definition_owner;
    const next=reports.filter(r=>r.timestamp>last.timestamp&&(
      ['component.start','package.start'].includes(r.kind)||
      ['helm.prepare','helm.install','helm.upgrade'].includes(r.kind)&&r.resource!==last.resource&&sameOwner(r.definition_owner,owner)||
      r.kind==='actions.command'&&['running command','action succeeded'].includes(r.message)&&['Post-deploy action','Success action'].includes(r.label)&&sameOwner(r.definition_owner,owner)
    )).sort((a,b)=>a.timestamp-b.timestamp)[0];
    if(next&&noErrorBetween(last.timestamp,next.timestamp))assumptions.set(last,{inferred_complete:true,inference_evidence:'Assumed complete: the same sequential CLI advanced to '+(next.label||next.message)+' without a reported error',inference_boundary:next.id});
  }
  // Some stock actions also omit their success line (e.g. variable-setting
  // commands). Apply the same advancement rule without exposing command bodies.
  for(const action of reports.filter(r=>r.kind==='actions.command'&&!['action succeeded','action failed'].includes(r.message)&&r.definition_owner?.component)){
    const next=reports.filter(r=>r.timestamp>action.timestamp&&(
      ['component.start','package.start'].includes(r.kind)||
      sameOwner(r.definition_owner,action.definition_owner)&&(
        r.kind==='actions.command'&&(r.declaration_id||r.action_id)!==(action.declaration_id||action.action_id)&&r.label===action.label||
        action.label==='Pre-deploy action'&&['images.push','helm.prepare','helm.install','helm.upgrade'].includes(r.kind)
      )
    )).sort((a,b)=>a.timestamp-b.timestamp)[0];
    if(next&&noErrorBetween(action.timestamp,next.timestamp))assumptions.set(action,{inferred_complete:true,inference_evidence:'Assumed complete: the same sequential CLI advanced beyond this action without a reported error',inference_boundary:next.id});
  }
  const starts=reports.filter(r=>r.kind==='package.start'&&r.definition_owner?.package);
  for(const start of starts){
    const next=starts.filter(r=>r.timestamp>start.timestamp&&r.definition_owner.package!==start.definition_owner.package).sort((a,b)=>a.timestamp-b.timestamp)[0];
    if(next&&noErrorBetween(start.timestamp,next.timestamp))assumptions.set(start,{inferred_package_complete:true,inference_evidence:'Assumed complete: the sequential CLI started package '+next.definition_owner.package+' without a reported error'});
  }
  let projected=reports.map(r=>assumptions.has(r)?{...r,...assumptions.get(r)}:r);
  // The final package has no subsequent package-start signal. Require positive
  // final-action evidence and coverage of every declared component as well as
  // completed observed work; CLI disappearance by itself never passes this gate.
  if(state.completed_at&&!['waiting','deploying'].includes(state.status)){
    const finalStart=reports.filter(r=>r.kind==='package.start').reduce((a,b)=>!a||b.timestamp>=a.timestamp?b:a,null),pkg=state.packages?.slice(-1)[0];
    if(finalStart&&pkg&&finalStart.definition_owner?.package===pkg.id&&!errors.some(e=>e.timestamp>=finalStart.timestamp)){
      const components=pkg.attempts?.slice(-1)[0]?.execution?.components||[],own=projected.filter(r=>r.definition_owner?.package===pkg.id&&r.timestamp>=finalStart.timestamp),last=own.filter(r=>!['package.start','component.start'].includes(r.kind)).reduce((a,b)=>!a||b.timestamp>=a.timestamp?b:a,null),groups=new Map();
      for(const r of own){
        if(!r.definition_owner.component||['package.start','component.start'].includes(r.kind))continue;
        const key=JSON.stringify([r.definition_owner.component,(r.kind.startsWith('helm.')||r.kind==='health.wait')&&r.resource?'chart:'+r.resource:r.kind.startsWith('images.')?r.kind:r.kind==='actions.command'?'action:'+(r.declaration_id||r.action_id||r.id):r.id]);
        if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);
      }
      const covered=components.length&&components.every(c=>own.some(r=>r.kind==='component.start'&&r.definition_owner.component===c.id));
      const complete=groups.size&&[...groups.values()].every(items=>{const component=components.find(c=>c.id===items[0].definition_owner.component);return reportedStepState(items,component,state.checks,false,false).state==='succeeded';});
      const finalAction=last?.kind==='actions.command'&&last.message==='action succeeded'&&['Post-deploy action','Success action'].includes(last.label);
      if(covered&&complete&&finalAction)projected=projected.map(r=>r.id===finalStart.id?{...r,inferred_package_complete:true,inference_evidence:'Assumed complete: final post-deploy action succeeded, every declared component was observed, all observed work is complete, and the CLI ended without a reported error'}:r);
    }
  }
  return projected;
}
function reportedStepState(items,component,checks,running,isLatest){
  const last=items.reduce((a,b)=>!a||(b.timestamp||0)>=(a.timestamp||0)?b:a,null);
  if(!last)return {state:'unknown',evidence:'No result observed'};
  // Exact normalized SDK reports are claims, not verified lifecycle callbacks.
  if(last.kind==='actions.command'&&last.message==='action succeeded')return {state:'succeeded',evidence:'CLI reported action success'};
  if(last.kind==='actions.command'&&last.message==='action failed')return {state:'failed',evidence:'CLI reported action failure'};
  if((last.kind==='images.push'&&last.message==='done pushing images')||(last.kind==='images.pull'&&last.message==='done pulling images'))return {state:'succeeded',evidence:'CLI reported image transfer complete'};
  const operation=items.filter(r=>r.kind==='helm.install'||r.kind==='helm.upgrade').reduce((a,b)=>!a||(b.timestamp||0)>=(a.timestamp||0)?b:a,null);
  if(operation){
    const resources=(component?.phases||[]).filter(p=>p.kind.startsWith('helm.')&&p.resource?.chart===operation.resource).map(p=>p.resource);
    const distinct=[...new Map(resources.map(r=>[JSON.stringify([r.namespace,r.release||r.chart]),r])).values()];
    const r=distinct.length===1?distinct[0]:null;
    const check=r&&(checks||[]).find(c=>c.kind==='helm-release'&&c.current_deployment&&c.namespace===r.namespace&&c.name===(r.release||r.chart));
    if(check?.status==='deployed')return {state:'succeeded',evidence:'Kubernetes Helm release deployed · revision '+check.revision};
    if(check?.status==='failed')return {state:'failed',evidence:'Kubernetes Helm release reports failure'};
  }
  if(last.inferred_complete)return {state:'succeeded',inferred:true,evidence:last.inference_evidence};
  if(running&&isLatest)return {state:'running',evidence:'Latest CLI activity; result not yet observed'};
  return {state:'unknown',evidence:'No explicit result observed'};
}
function quietPackageEligible(summary){return summary.appearance.state==='succeeded'&&!summary.unverified&&!summary.failed;}
function currentCliActivity(snapshot){
  if(!['waiting','deploying'].includes(snapshot.status))return null;
  if(snapshot.source?.output_complete===false||snapshot.source?.activity_available===false)return {state:'unknown',label:'Current activity unavailable',detail:'The complete CLI feed is unavailable. Check the deployment terminal.'};
  const report=(snapshot.reports||[]).reduce((a,b)=>!a||b.timestamp>a.timestamp?b:a,null);if(!report)return {state:'unknown',label:'Waiting for CLI activity',detail:'No SDK activity report has been captured yet.'};
  const failed=report.kind==='deployment.error'||report.message==='action failed',done=['action succeeded','done pushing images','done pulling images'].includes(report.message)||report.kind==='cluster.connected';
  const labels={'cluster.connect':'Waiting for cluster connection','cluster.connected':'Cluster connected','package.start':'Starting package deployment','component.start':'Starting component deployment','helm.prepare':'Preparing Helm chart','helm.install':'Installing Helm release','helm.upgrade':'Upgrading Helm release','health.wait':'Checking Helm release readiness','images.push':'Pushing images','images.pull':'Pulling images','actions.command':'Running deployment action'};
  return {state:failed?'failed':done?'succeeded':'running',label:failed?'CLI reported an error':done?'Last reported activity':labels[report.kind]||report.label,detail:report.error||report.message,report};
}
function clusterConnectionState(snapshot){
  const reports=snapshot.reports||[],wait=reports.filter(r=>r.kind==='cluster.connect').reduce((a,b)=>!a||b.timestamp>a.timestamp?b:a,null);
  if(!wait)return null;
  const later=reports.filter(r=>r.timestamp>wait.timestamp),explicit=later.find(r=>r.kind==='cluster.connected');
  if(explicit)return {state:'succeeded',label:'Cluster connected',evidence:'CLI explicitly reported that cluster connection completed'};
  if(['parallel','concurrent'].includes(snapshot.mode)||snapshot.packages?.filter(p=>p.status==='deploying').length>1)return {state:'unknown',label:'Cluster connection reported',evidence:'Concurrent activity cannot establish a single connection handoff'};
  const nextPackage=later.filter(r=>r.kind==='package.start').reduce((a,b)=>Math.min(a,b.timestamp),Infinity),component=later.filter(r=>r.kind==='component.start'&&r.timestamp<nextPackage).sort((a,b)=>a.timestamp-b.timestamp)[0];
  const errors=later.filter(r=>(r.kind==='deployment.error'||r.message==='action failed')&&r.timestamp<(component?.timestamp??nextPackage));
  if(component&&!errors.length)return {state:'succeeded',label:'Cluster connected',evidence:'The same sequential CLI advanced from waiting for cluster connection into component deployment'};
  if(errors.some(r=>/unable to connect to (?:the Kubernetes )?cluster/.test(r.error||'')))return {state:'failed',label:'Cluster connection error',evidence:'The CLI reported a cluster connection error'};
  if(errors.length||snapshot.completed_at||!['waiting','deploying'].includes(snapshot.status)||snapshot.source?.output_complete===false||snapshot.source?.activity_available===false||nextPackage!==Infinity)return {state:'unknown',label:'Connection unconfirmed',evidence:'No connection-complete report or error-free component handoff was captured'};
  return {state:'running',label:'Connecting to cluster',evidence:'CLI reported waiting for cluster connection; no handoff observed yet'};
}
function reportedPackageState(pkg,reports,active){
  if(pkg.status==='completed')return {state:'succeeded',label:'Completed',evidence:'Explicit package result from the command observer'};
  if(pkg.status==='failed'||reports.some(r=>r.message==='action failed'||r.kind==='deployment.error'))return {state:'failed',label:'Error reported',evidence:'Package failure or an owned CLI error was reported'};
  if(active)return {state:'running',label:'Running',evidence:'Current package activity was reported'};
  const inferred=reports.find(r=>r.inferred_package_complete);
  if(inferred)return {state:'succeeded',label:'Done',inferred:true,evidence:inferred.inference_evidence};
  return {state:'unknown',label:reports.length?'Result not reported':'Not reported',evidence:reports.length?'The CLI did not expose a final package result; confirmed steps alone are not package success':'No package activity reported'};
}
function showPackageConnectors(layout,mode,activeCount,packageCount){
  return layout==='pipeline'&&packageCount>1&&activeCount<=1&&!['concurrent','parallel'].includes(mode);
}
function scopeImageReports(reports){
  // Older attached readers left the SDK's resource-less completion unassigned.
  // Project only explicit component-start + same-owner push + completion evidence.
  return reports.map(report=>{
    if(report.kind!=='images.push'||report.message!=='done pushing images'||report.definition_owner)return report;
    const starts=reports.filter(r=>['package.start','component.start'].includes(r.kind)&&r.timestamp<=report.timestamp);
    const boundary=starts.reduce((a,b)=>!a||b.timestamp>=a.timestamp?b:a,null),owner=boundary?.kind==='component.start'?boundary.definition_owner:null;
    if(!owner?.component)return report;
    const pushes=reports.filter(r=>r.kind==='images.push'&&['pushing image','image push in progress'].includes(r.message)&&r.timestamp>=boundary.timestamp&&r.timestamp<=report.timestamp);
    if(!pushes.length||!pushes.every(r=>r.definition_owner?.package===owner.package&&r.definition_owner?.component===owner.component))return report;
    return {...report,definition_owner:owner,scope_evidence:'explicit-cli-component-start-and-image-pushes'};
  });
}
// Lexical colors for the viewer's normalized JSON-compatible YAML, not a YAML parser.
// Unrecognized syntax and the tail of very large documents stay visible as plain text.
function yamlTokens(text,limit=20000){
  const tokens=[],key=/^([ \t]*(?:-[ \t]+)?)([A-Za-z_][A-Za-z0-9_-]*|"(?:\\.|[^"\\])*"|'(?:''|[^'])*'):(?=[ \t]|$)/;
  const scalar=/^("(?:\\.|[^"\\])*"|'(?:''|[^'])*'|true|false|null|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|\[\]|\{\})(?=[ \t]*(?:#|$))/;
  let cursor=0,remaining=Math.max(0,limit);
  function mark(start,end,kind){
    if(!remaining)return;
    if(start>cursor)tokens.push({text:text.slice(cursor,start),kind:null});
    tokens.push({text:text.slice(start,end),kind});cursor=end;remaining--;
  }
  for(const match of text.matchAll(/[^\r\n]+/g)){
    if(!remaining)break;
    const line=match[0],offset=match.index,mapping=key.exec(line);
    if(mapping)mark(offset+mapping[1].length,offset+mapping[1].length+mapping[2].length,'key');
    let start=mapping?mapping[0].length:/^[ \t]*(?:-[ \t]+)?/.exec(line)[0].length;
    start+=/^[ \t]*/.exec(line.slice(start))[0].length;
    const value=scalar.exec(line.slice(start));
    if(value){const raw=value[0],kind=/^["']/.test(raw)?'string':/^(true|false|null)$/.test(raw)?'literal':/^[\[{]/.test(raw)?'punctuation':'number';mark(offset+start,offset+start+raw.length,kind);start+=raw.length;}
    const comment=/^[ \t]*(#.*)$/.exec(line.slice(start));
    if(comment)mark(offset+line.length-comment[1].length,offset+line.length,'comment');
  }
  if(cursor<text.length)tokens.push({text:text.slice(cursor),kind:null});
  return tokens;
}
function renderYaml(parent,text){
  const fragment=document.createDocumentFragment();
  for(const token of yamlTokens(text))fragment.append(token.kind?node('span',token.text,'yaml-'+token.kind):document.createTextNode(token.text));
  parent.replaceChildren(fragment);
}
async function showDefinition(packageId=null){
  const mine=++definitionRequest,dialog=$('definition-dialog'),id=run;
  const packageKind=state.packages.find(p=>p.id===packageId)?.artifact_info?.kind;
  $('definition-title').textContent=packageId?packageId+' · '+(packageKind==='ZarfInitConfig'?'Zarf init config':'Zarf package config'):state.bundle_name+' · Bundle YAML';
  const reference=packageId?state.packages.find(p=>p.id===packageId)?.artifact_info?.reference:null;
  $('definition-reference').textContent=reference?'Reference: '+reference:'';$('definition-reference').hidden=!reference;
  $('definition-note').textContent='Packaged definition, including values and commands. External configuration and CLI overrides are not applied.';
  $('definition-content').textContent='Loading packaged definition…';if(!dialog.open)dialog.showModal();
  try{
    const document=await request(`${api}/${id}${packageId?'/packages/'+encodeURIComponent(packageId):''}/definition`);
    if(mine===definitionRequest&&dialog.open){renderYaml($('definition-content'),document.yaml);if(document.values_hidden)$('definition-note').textContent='Full values were not retained by this older capture. Refreshing the page cannot restore them.';}
  }catch(error){if(mine===definitionRequest&&dialog.open)$('definition-content').textContent='Packaged definition unavailable: '+error.message;}
}
function restoreComponentScroll(list){
  if(!list?.isConnected||!list.clientHeight)return;
  list.scrollTop=flowScroll.get(list.dataset.scrollKey)||0;
  const current=list.querySelector('.component-progress-row.is-current');
  if(current&&!componentChoices.has(list.dataset.choiceKey)){const row=current.getBoundingClientRect(),box=list.getBoundingClientRect();list.scrollTop+=row.top-box.top-list.clientHeight/2+row.height/2;}
}
function renderStockPipeline(){
  $('graph-caption').hidden=true;
  const canvas=$('packages');canvas.classList.add('stock-pipeline');
  const key=JSON.stringify([state.id,state.status,state.completed_at,state.mode,state.source,state.reports,state.checks,inspectorOpen,document.body.dataset.outputFocus,state.artifact_info,state.packages,packageLayout,pipelineSelection,state.packages.map(p=>componentChoices.get(state.id+'/'+p.id)),[...stepChoices],quietFinished]);
  if(canvas.dataset.stockKey===key)return;canvas.dataset.stockKey=key;
  const opened=new Set([...canvas.querySelectorAll('details[open][data-disclosure]')].map(e=>e.dataset.disclosure));
  canvas.replaceChildren();
  const reports=inferSequentialCompletion(state,scopeImageReports(state.reports||[])),errors=reports.filter(r=>r.message==='action failed'||r.kind==='deployment.error'),latest=reports.reduce((last,item)=>!last||item.timestamp>last.timestamp?item:last,null);
  function openOutput(focus,context,activity=null){
    full=true;rawMode=true;inspectorOpen=true;clearScope();clearTimeout(searchTimer);$('log-search').value='';$('log-level').value='';document.body.dataset.outputFocus=focus;document.body.dataset.outputContext=context;
    if(!activity){logAnchorId=null;logAnchorLabel='';}render();(activity?loadActivityLogs(activity.items,activity.label):loadLogs()).catch(e=>notice(e.message));$('job-inspector').scrollIntoView({block:'nearest'});
  }
  function describe(items,component){
    const last=items.reduce((a,b)=>!a||(b.timestamp||0)>=(a.timestamp||0)?b:a,null),chart=items.some(r=>r.kind.startsWith('helm.')||r.kind==='health.wait');
    if(chart){
      const op=items.filter(r=>['helm.install','helm.upgrade'].includes(r.kind)).reduce((a,b)=>!a||(b.timestamp||0)>=(a.timestamp||0)?b:a,null);
      const resource=component?.phases.find(p=>p.resource?.chart===last.resource)?.resource;
      const chart=component?.artifact_info?.charts?.find(c=>c.name===last.resource);
      return {action:op?(resource?.manifest?'Apply manifest':op.kind==='helm.upgrade'?'Upgrade Helm release':'Install Helm release'):last.kind==='health.wait'?'Check readiness':resource?.manifest?'Prepare manifest':'Prepare Helm chart',target:resource?.manifest||resource?.release||last.resource,namespace:resource?.namespace,chart:last.resource,chartVersion:chart?.version,release:resource?.release,manifest:resource?.manifest,detail:last.message,error:last.error};
    }
    if(last.kind.startsWith('images.')){
      const images=[...new Set(items.map(r=>r.resource).filter(Boolean))];
      return {action:last.kind==='images.pull'?'Pull images':'Push images',target:images.length>1?images.length+' images':images[0]||'Images',detail:last.message+(Number.isFinite(last.image_percent)?' · '+last.image_percent.toFixed(1)+'% of this image':''),image_percent:last.image_percent,image:last.resource};
    }
    return {action:last.label==='Pre-deploy action'?'Run pre-deploy action':last.label==='Post-deploy action'?'Run post-deploy action':last.label,target:last.resource||'',detail:last.message,error:last.error};
  }
  function groupedSteps(items){
    const groups=new Map();
    for(const item of items){
      if(['package.start','component.start'].includes(item.kind))continue;
      const key=(item.kind.startsWith('helm.')||item.kind==='health.wait')&&item.resource?'chart:'+item.resource:item.kind.startsWith('images.')?item.kind:item.id;
      if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);
    }
    return groups;
  }
  function steps(items,component,parent,context){
    const groups=groupedSteps(items),choiceKey=state.id+'/step/'+context,detailsKey=state.id+'/activity/'+context;
    const preferred=stepChoices.get(choiceKey),selectedKey=groups.has(preferred)?preferred:[...groups].find(([,rows])=>rows.includes(latest))?.[0]||[...groups].find(([,rows])=>reportedStepState(rows,component,state.checks,false,false).state==='failed')?.[0]||[...groups.keys()].slice(-1)[0];
    const rail=node('div',undefined,'execution-rail');rail.setAttribute('aria-label',context+' CLI activity in first-observed order');
    rail.title='First-observed order; repeated reports for the same activity are grouped. This is not a complete execution trace.';
    for(const [key,items]of groups){
      const text=describe(items,component),appearance=reportedStepState(items,component,state.checks,state.status==='deploying'&&state.source.output_complete!==false,items.includes(latest));
      const job=node('button',undefined,'stock-job reported '+appearance.state);job.dataset.report=key;job.dataset.focusKey=context+':'+key;job.dataset.stepStatus=appearance.state;job.dataset.resultInferred=String(!!appearance.inferred);
      job.setAttribute('aria-label',`${context} · ${text.action}${text.target?' '+text.target:''} · ${appearance.evidence}`);
      const label=node('span',undefined,'stock-job-label'),heading=node('span',undefined,'stock-job-heading');
      const result=appearance.state==='succeeded'?(items.some(r=>r.kind.startsWith('helm.')||r.kind==='health.wait')&&!appearance.inferred?'Deployed':'Done'):appearance.state==='running'?'Running':appearance.state==='failed'?'Failed':'Result unknown';
      heading.append(node('strong',text.action),node('span',result,'stock-job-state'));label.append(heading,node('span',appearance.state==='running'&&Number.isFinite(text.image_percent)?text.image.split('/').pop()+' · '+text.image_percent.toFixed(1)+'%':text.target||title(text.detail)));job.append(stepIcon(appearance.state),label);
      job.title=`${context}\n${text.action}${text.target?' '+text.target:''}${text.namespace?' in namespace '+text.namespace:''}\nCLI report: ${text.detail}\n${appearance.evidence}\nClick to jump to this activity in the full session output.`;
      job.classList.toggle('latest-report',state.status==='deploying'&&state.source.output_complete!==false&&items.includes(latest));job.classList.toggle('selected',key===selectedKey);job.setAttribute('aria-pressed',String(key===selectedKey));
      job.onclick=()=>{stepChoices.set(choiceKey,key);setDisclosure(detailsKey,true);const owner=items.find(r=>r.definition_owner)?.definition_owner?.package;if(owner)manualPackages.add(state.id+'/package/'+owner);openOutput(job.dataset.focusKey,context,{items,label:text.action+(text.target?' · '+text.target:'')});};
      if(rail.childElementCount){const arrow=node('span','→','activity-connector');arrow.setAttribute('aria-hidden','true');rail.append(arrow);}
      rail.append(job);
    }
    parent.classList.toggle('no-observed-steps',!groups.size);
    if(!groups.size)rail.append(node('span',items.some(r=>r.kind==='component.start')?'Component start reported; no action result captured.':'No CLI activity captured for this component.','unobserved-component'));
    const flow=node('div',undefined,'activity-flow');
    flow.append(rail);parent.append(flow);
    const pushed=items.filter(r=>r.kind==='images.push'&&r.resource),batchDone=items.filter(r=>r.kind==='images.push'&&r.message==='done pushing images').reduce((a,b)=>!a||b.timestamp>a.timestamp?b:a,null);
    if(pushed.length){
      const transferKey=state.id+'/image-pushes/'+context,transfers=node('details',undefined,'image-transfer-list'),summary=node('summary'),doneCount=pushed.filter(image=>batchDone&&batchDone.timestamp>=image.timestamp).length;
      transfers.dataset.disclosure=transferKey;transfers.open=disclosure.has(transferKey)?disclosure.get(transferKey):pushed.includes(latest);
      summary.append(node('span','Image pushes · '+pushed.length),node('span',doneCount+' confirmed','image-transfer-count'));transfers.append(summary);
      for(const image of pushed){
        const done=batchDone&&batchDone.timestamp>=image.timestamp,live=state.status==='deploying'&&state.source.output_complete!==false&&!done&&image===latest,appearance=done?'succeeded':live?'running':'unknown',row=node('div',undefined,'image-transfer '+appearance);
        row.dataset.image=image.resource;row.title=image.resource;row.append(stepIcon(appearance),node('span',image.resource.split('/').pop(),'image-transfer-name'),node('span',done?'Done':Number.isFinite(image.image_percent)?image.image_percent.toFixed(1)+'% bytes':live?'Pushing':'Push reported','image-transfer-state'));transfers.append(row);
      }
      if(!batchDone)transfers.append(node('p','Checkmarks appear when the CLI confirms this image batch is complete.','image-transfer-note'));
      flow.append(transfers);
    }
    if(groups.size){
      const selectedItems=groups.get(selectedKey),text=describe(selectedItems,component),appearance=reportedStepState(selectedItems,component,state.checks,state.status==='deploying'&&state.source.output_complete!==false,selectedItems.includes(latest)),details=node('details',undefined,'execution-details selected-step-details');
      details.dataset.disclosure=detailsKey;details.dataset.selectedStep=selectedKey;details.open=disclosure.has(detailsKey)?disclosure.get(detailsKey):appearance.state==='failed';const initiallyOpen=details.open;details.ontoggle=()=>{if(details.isConnected){disclosure.set(detailsKey,details.open);if(details.open&&!initiallyOpen){const owner=selectedItems.find(r=>r.definition_owner)?.definition_owner?.package;if(owner)manualPackages.add(state.id+'/package/'+owner);}}};details.append(node('summary','Step details'));
      const header=node('div',undefined,'step-detail-heading'),result=appearance.state==='succeeded'?'Done':appearance.state==='running'?'Running':appearance.state==='failed'?'Failed':'Result unknown';header.append(node('h3',text.action),node('span',result,'step-detail-result '+appearance.state));details.append(header);
      const facts=node('dl',undefined,'step-detail-facts');function fact(label,value){if(value)facts.append(node('dt',label),node('dd',String(value)));}
      fact(text.manifest?'Manifest':'Target',text.target);fact('Packaged namespace',text.namespace);fact('Release',text.release);if(text.chart)fact('Chart',text.chart+(text.chartVersion?' '+text.chartVersion:''));fact('Last CLI report',text.error||text.detail);fact('Evidence',appearance.evidence);
      if(appearance.inferred)fact('Completion basis','Inferred from sequential CLI advancement, not an explicit success report');
      details.append(facts);const actions=node('div',undefined,'step-detail-actions'),logs=node('button','Go to logs','step-log-link');logs.onclick=()=>openOutput(context+':'+selectedKey,context,{items:selectedItems,label:text.action+(text.target?' · '+text.target:'')});actions.append(logs);details.append(actions);parent.append(details);
    }
  }
  const running=['waiting','deploying'].includes(state.status),limited=state.source.output_complete===false,blind=running&&limited&&(!reports.length||state.source.activity_available===false),banner=node('section',undefined,'deployment-status-bar session-activity-heading'+(blind?' observation-gap':''));
  banner.setAttribute('aria-label','Deployment status');
  const statusHeading=node('div',undefined,'deployment-status-heading'),pipelineTitle=node('div',undefined,'pipeline-title'),titleLine=node('div',undefined,'pipeline-title-line');titleLine.append(node('h2','Package navigation'));pipelineTitle.append(titleLine);statusHeading.append(pipelineTitle);banner.append(statusHeading);
  const scoped=reports.filter(r=>r.definition_owner),focus=scoped.reduce((a,b)=>!a||b.timestamp>=a.timestamp?b:a,null),track=node('div',undefined,'deployment-package-track');track.setAttribute('aria-label','Packages in bundle order');
  const activePackages=new Set(running&&!limited?state.packages.filter(p=>p.status==='deploying').map(p=>p.id):[]);
  if(!activePackages.size&&running&&!limited&&focus)activePackages.add(focus.definition_owner.package);
  let confirmedTotal=0,inferredTotal=0,unknownTotal=0;
  const packageSummaries=new Map(),connected=showPackageConnectors(packageLayout,state.mode,activePackages.size,state.packages.length);track.dataset.connected=String(connected);
  for(const p of state.packages){
    const own=reports.filter(r=>r.definition_owner?.package===p.id),components=p.attempts.slice(-1)[0]?.execution?.components||[],outcomes=[];
    for(const component of components)for(const items of groupedSteps(own.filter(r=>r.definition_owner.component===component.id)).values())outcomes.push(reportedStepState(items,component,state.checks,running&&!limited,items.includes(latest)));
    const confirmed=outcomes.filter(s=>s.state==='succeeded'&&!s.inferred).length,inferred=outcomes.filter(s=>s.state==='succeeded'&&s.inferred).length,unverified=outcomes.filter(s=>s.state==='unknown').length,failed=p.status==='failed'||own.some(r=>r.message==='action failed'||r.kind==='deployment.error'),active=activePackages.has(p.id);
    confirmedTotal+=confirmed;inferredTotal+=inferred;unknownTotal+=unverified;
    const appearance=reportedPackageState(p,own,active),result=appearance.state,item=node('button',undefined,'deployment-package '+result),label=node('span',undefined,'deployment-package-label'),caption=node('span',undefined,'deployment-package-caption');
    packageSummaries.set(p.id,{confirmed,inferred,unverified,observed:outcomes.length,active,failed,appearance});
    item.dataset.statusPackage=p.id;item.dataset.packageStatus=result;item.dataset.confirmedSteps=confirmed;item.dataset.inferredSteps=inferred;item.dataset.resultInferred=String(!!appearance.inferred);
    item.setAttribute('aria-current',active?'step':'false');item.setAttribute('aria-label',p.name+' · '+appearance.label+' · '+(confirmed+inferred)+' steps completed');
    if(result==='unknown')caption.append(node('span',appearance.label,'package-result-label'));if(confirmed+inferred)caption.append(node('span',(confirmed+inferred)+' '+(confirmed+inferred===1?'step':'steps')+' completed','pipeline-confirmed-count'));label.append(node('strong',p.name));if(caption.childElementCount)label.append(caption);
    item.append(stepIcon(result),label);item.title=appearance.evidence+'. '+confirmed+' reported/verified step results · '+inferred+' inferred step results'+(unverified?' · '+unverified+' unverified step results':'');
    item.classList.toggle('is-selected',pipelineSelection===p.id);item.setAttribute('aria-pressed',String(pipelineSelection===p.id));
    item.onclick=()=>{pipelineSelection=p.id;manualPackages.add(state.id+'/package/'+p.id);setDisclosure(state.id+'/package/'+p.id,true);canvas.dataset.stockKey='';render();canvas.querySelector('[data-package="'+CSS.escape(p.id)+'"]').scrollIntoView({block:'nearest'});};
    if(connected&&track.childElementCount){const connector=node('span',undefined,'pipeline-connector');connector.setAttribute('aria-hidden','true');connector.title='Bundle package order, not completion evidence';connector.append(node('span','›','pipeline-chevron'));track.append(connector);}track.append(item);
  }
  const overview=$('overview-metrics');overview.replaceChildren();overview.dataset.reportedSteps=confirmedTotal;overview.dataset.inferredSteps=inferredTotal;
  for(const [value,label,kind] of [[state.packages.length,'Packages','packages'],[confirmedTotal+inferredTotal,'Steps completed','confirmed'],[activePackages.size,'Packages active','active'],[unknownTotal,'Steps unknown','unknown']]){const metric=node('div',undefined,'overview-metric '+kind);metric.dataset.metric=kind;metric.append(node('strong',String(value)),node('span',label));overview.append(metric);}
  overview.title=confirmedTotal+' reported/verified step results · '+inferredTotal+' inferred from sequential CLI advancement. Unknown outcomes and process exits are not success evidence.';
  pipelineTitle.append(node('p',state.packages.length+' '+(state.packages.length===1?'package':'packages')+' · '+(confirmedTotal+inferredTotal)+' '+(confirmedTotal+inferredTotal===1?'step':'steps')+' completed','deployment-confirmed-total'));
  track.dataset.layout=packageLayout;track.setAttribute('role','group');
  const layouts=node('div',undefined,'pipeline-layout-toggle');layouts.setAttribute('role','group');layouts.setAttribute('aria-label','Package layout');
  for(const mode of ['pipeline','list']){const button=node('button',title(mode));button.type='button';button.dataset.focusKey='package-layout:'+mode;button.setAttribute('aria-pressed',String(packageLayout===mode));button.onclick=()=>{packageLayout=mode;canvas.dataset.stockKey='';render();};layouts.append(button);}titleLine.append(layouts);
  banner.append(track);
  const actions=node('div',undefined,'session-view-actions');
  const output=node('button',limited?'View available output':'View CLI output','session-output-button');output.dataset.focusKey='session-output';output.onclick=()=>openOutput('session-output','Session');actions.append(output);statusHeading.append(actions);
  const activity=currentCliActivity(state);
  if(activity){const pane=node('section',undefined,'current-cli-activity '+activity.state);pane.setAttribute('aria-label','Current CLI activity');const heading=node('div',undefined,'current-cli-heading');heading.append(node('span','Current CLI activity','current-cli-label'));if(activity.state==='running')heading.append(stepIcon('running'));heading.append(node('strong',activity.label));const r=activity.report;if(r){const owner=r.definition_owner||{},context=[...new Set([owner.package,owner.component].filter(Boolean))].join(' / ');if(context)heading.append(node('span',context,'current-cli-context'));const canLocate=Object.values(NAVIGATION_MESSAGES).includes(r.kind)&&r.resource,link=node('button',canLocate?'Go to logs':'View output','current-cli-log-link');link.onclick=()=>openOutput('current-cli-report','Current activity',canLocate?{items:[{...r,first_log_id:r.log_id||r.first_log_id}],label:activity.label}:null);heading.append(link);}pane.append(heading,node('p',activity.detail+(r?.resource?' · '+r.resource:''),'current-cli-report'));pane.title='Latest captured SDK activity, not an independently verified resource-health result.';canvas.append(pane);}
  canvas.append(banner);
  if(errors.length){
    const lastError=errors.reduce((a,b)=>b.timestamp>a.timestamp?b:a),warning=node('div',undefined,'cli-error-summary');warning.setAttribute('role','status');
    warning.append(node('strong','CLI reported an error'),node('p',lastError.error||'An action failure was reported. Open CLI output for the original error.'));canvas.append(warning);
  }
  if(limited&&!blind)canvas.append(node('p','Partial CLI output: some console activity is unavailable.','source-output-warning'));
  const packageToolbar=node('div',undefined,'packages-toolbar'),disclosures=node('div',undefined,'package-disclosure-controls');packageToolbar.append(node('h2','Execution timeline','packages-heading'));
  const quietLabel=node('label',undefined,'quiet-finished-toggle'),quiet=node('input');quiet.type='checkbox';quiet.checked=quietFinished;quiet.dataset.focusKey='quiet-finished';quiet.setAttribute('aria-label','Quiet finished view');quietLabel.title='Automatically collapse completed packages after the CLI ends. Manually opened packages stay open; failed and unknown results stay visible.';quiet.onchange=()=>{quietFinished=quiet.checked;try{localStorage.setItem('uds-deploy-quiet-finished',String(quietFinished));}catch{}finishedViews.delete(state.id);canvas.dataset.stockKey='';render();};quietLabel.append(quiet,document.createTextNode('Quiet finished view'));packageToolbar.append(quietLabel);
  for(const [label,open] of [['Expand all',true],['Collapse all',false]]){const button=node('button',label);button.type='button';button.setAttribute('aria-label',label+' packages');button.onclick=()=>{for(const detail of canvas.querySelectorAll('details.package-execution')){detail.open=open;disclosure.set(detail.dataset.disclosure,open);manualPackages.add(detail.dataset.disclosure);}};disclosures.append(button);}packageToolbar.append(disclosures);canvas.append(packageToolbar);
  for(const p of state.packages){
    const section=node('details',undefined,'package-execution');section.dataset.package=p.id;
    const disclosureKey=state.id+'/package/'+p.id;section.open=disclosure.get(disclosureKey)||false;
    section.ontoggle=()=>{if(section.isConnected){disclosure.set(disclosureKey,section.open);if(section.open)requestAnimationFrame(()=>restoreComponentScroll(section.querySelector('.component-progress-list')));}};
    const own=reports.filter(r=>r.definition_owner?.package===p.id),active=activePackages.has(p.id);
    section.classList.toggle('has-reported-error',p.status==='failed'||own.some(r=>r.message==='action failed'||r.kind==='deployment.error'));
    section.classList.toggle('is-active',active);section.classList.toggle('has-command-result',packageSummaries.get(p.id).appearance.state==='succeeded');
    const components=p.attempts.slice(-1)[0]?.execution?.components||[];
    if(!disclosure.has(disclosureKey)&&active)section.open=true;
    if(!running&&quietFinished&&!finishedViews.has(state.id)&&!manualPackages.has(disclosureKey)){const summary=packageSummaries.get(p.id);section.open=!quietPackageEligible(summary);disclosure.set(disclosureKey,section.open);}
    const choiceKey=state.id+'/'+p.id,lastComponent=own.reduce((a,b)=>b.definition_owner.component&&(!a||b.timestamp>a.timestamp)?b:a,null)?.definition_owner.component;
    const activeComponent=active?(latest?.definition_owner?.package===p.id?latest.definition_owner.component:components.find(c=>c.observed&&c.status==='running')?.id):null;
    const preferred=componentChoices.get(choiceKey)||activeComponent||lastComponent;
    const chosen=components.some(c=>c.id===preferred)?preferred:components.length===1?components[0].id:null;
    const heading=node('summary',undefined,'package-execution-heading');heading.dataset.focusKey='package-disclosure:'+p.id;
    heading.addEventListener('click',()=>manualPackages.add(disclosureKey));heading.append(node('span','Package','hierarchy-pill'),node('strong',p.name,'package-title'));
    if(components.length!==1)heading.append(node('span',components.length?components.length+' components':'Definitions unavailable','package-component-count'));
    if(own.some(r=>r.message==='action failed'||r.kind==='deployment.error'))heading.append(node('span','Error reported','package-observation failed'));
    else if(p.status==='failed')heading.append(node('span','Command failed','package-observation failed'));
    else if(p.status==='completed')heading.append(node('span','Command succeeded','package-observation succeeded'));
    else if(active)heading.append(node('span',activeComponent?'Running · '+activeComponent:'Running','package-observation active'));
    else if(packageSummaries.get(p.id).appearance.inferred){const done=node('span','Done','package-observation succeeded');done.title=packageSummaries.get(p.id).appearance.evidence;heading.append(done);}
    else heading.append(node('span',own.length?'Result not reported':'Not reported','package-observation'));
    const summary=packageSummaries.get(p.id);if(summary.observed){const counts=node('span',(summary.confirmed+summary.inferred)+' '+(summary.confirmed+summary.inferred===1?'step':'steps')+' completed'+(summary.unverified?' · '+summary.unverified+' unknown':''),'package-step-summary');counts.title=summary.confirmed+' reported/verified · '+summary.inferred+' inferred from sequential CLI advancement. Not a completion percentage.';heading.append(counts);}
    section.append(heading);
    const info=p.artifact_info||{},artifact=node('div',undefined,'package-artifact'),version=node('span',info.version||p.version.split('@')[0],'package-version');version.title=info.reference||'Package version';artifact.append(version);
    if(info.has_yaml){const configLabel=info.kind==='ZarfInitConfig'?'Zarf init config':'Zarf package config',yaml=node('button',configLabel,'package-yaml');yaml.setAttribute('aria-label','View '+configLabel);yaml.dataset.focusKey='package-yaml:'+p.id;yaml.onclick=event=>{event.preventDefault();event.stopPropagation();showDefinition(p.id);};artifact.append(yaml);}
    if(components.length){
      const board=node('div',undefined,'component-progress-board'),boardHeading=node('div',undefined,'component-progress-heading');board.hidden=components.length===1;const boardLabel=node('h3');boardLabel.append(node('span','Components','hierarchy-pill'));boardHeading.append(boardLabel,artifact);
      if(active&&componentChoices.has(choiceKey)){const follow=node('button','Follow current component','follow-component');follow.dataset.focusKey='component-follow:'+p.id;follow.onclick=()=>{componentChoices.delete(choiceKey);canvas.dataset.stockKey='';render();};boardHeading.append(follow);}
      board.append(boardHeading);const list=node('div',undefined,'component-progress-list'),scrollKey=state.id+'/component-progress/'+p.id;list.dataset.scrollKey=scrollKey;list.dataset.choiceKey=choiceKey;list.setAttribute('aria-label',p.name+' component activity');
      for(const component of components){
        const componentReports=own.filter(r=>r.definition_owner.component===component.id),current=activeComponent===component.id,row=node('button',undefined,'component-progress-row'+(current?' is-current':'')),jobs=node('span',undefined,'component-progress-jobs');
        row.dataset.componentProgress=component.id;row.dataset.componentChoice=component.id;row.dataset.focusKey='component-inspect:'+p.id+':'+component.id;row.setAttribute('aria-label','Inspect '+p.name+' / '+component.id);row.setAttribute('aria-pressed',String(component.id===chosen));row.setAttribute('aria-controls',state.id+'/component-detail/'+p.id+'/'+component.id);row.title='Inspect component activity and packaged resources';row.append(node('strong',component.id,'component-progress-name'));
        const componentKey=state.id+'/component-detail/'+p.id+'/'+component.id,expanded=component.id===chosen&&(disclosure.get(componentKey)??true),groups=[...groupedSteps(componentReports).values()];row.dataset.compact=String(expanded);
        if(expanded&&groups.length){
          const outcomes=groups.map(items=>reportedStepState(items,component,state.checks,state.status==='deploying'&&state.source.output_complete!==false,items.includes(latest))),counts={succeeded:0,running:0,failed:0,unknown:0};for(const outcome of outcomes)counts[outcome.state]++;
          jobs.classList.add('component-counts');jobs.append(node('span',groups.length+' observed '+(groups.length===1?'step':'steps')));
          for(const [kind,label] of [['succeeded','completed'],['running','running'],['failed','failed'],['unknown','unknown']])if(counts[kind])jobs.append(node('span',counts[kind]+' '+label,'component-step-count '+kind));
          jobs.title=outcomes.filter(o=>o.state==='succeeded'&&!o.inferred).length+' reported/verified · '+outcomes.filter(o=>o.inferred).length+' inferred completed steps. Observed activity only, not a whole-component result.';
        }else for(const items of groups){
          const appearance=reportedStepState(items,component,state.checks,state.status==='deploying'&&state.source.output_complete!==false,items.includes(latest)),text=describe(items,component),job=node('span',undefined,'component-progress-step '+appearance.state);
          job.title=text.action+(text.target?' · '+text.target:'')+' — '+appearance.evidence;if(jobs.childElementCount){const arrow=node('span','→','component-step-connector');arrow.setAttribute('aria-hidden','true');job.append(arrow);}job.append(stepIcon(appearance.state),node('span',text.action));jobs.append(job);
        }
        if(!jobs.childElementCount){if(current&&!expanded)jobs.append(stepIcon('running'));jobs.append(node('span',componentReports.length?'Start reported; no step result yet':'Not reported','component-progress-empty'));}
        row.append(jobs);if(current){row.append(node('span','Current','component-progress-current'));}
        row.onclick=()=>{manualPackages.add(disclosureKey);componentChoices.set(choiceKey,component.id);setDisclosure(componentKey,true);canvas.dataset.stockKey='';render();canvas.querySelector('[data-package="'+CSS.escape(p.id)+'"] [data-component="'+CSS.escape(component.id)+'"]').scrollIntoView({block:'nearest'});};list.append(row);
      }
      list.onscroll=()=>{if(list.isConnected&&list.clientHeight)flowScroll.set(scrollKey,list.scrollTop);};board.append(list);section.append(board);
      requestAnimationFrame(()=>restoreComponentScroll(list));if(components.length===1)heading.insertBefore(artifact,heading.querySelector('.package-observation'));
    }
    else{const meta=node('div',undefined,'package-info');meta.append(artifact);section.append(meta);}
    if(components.length&&!chosen)section.append(node('p','Select a component above to inspect its activity and packaged resources.','component-selection-hint'));
    for(const component of components){
      const componentKey=state.id+'/component-detail/'+p.id+'/'+component.id,row=node('details',undefined,'component-execution');row.dataset.component=component.id;row.hidden=component.id!==chosen;row.dataset.disclosure=componentKey;row.open=components.length===1?true:disclosure.has(componentKey)?disclosure.get(componentKey):true;row.dataset.inline=String(components.length===1);
      const expandedAtRender=row.open;row.ontoggle=()=>{if(row.isConnected){disclosure.set(componentKey,row.open);if(component.id===chosen&&row.open!==expandedAtRender){manualPackages.add(disclosureKey);canvas.dataset.stockKey='';render();}}};
      row.id=componentKey;row.setAttribute('aria-label',p.name+' / '+component.id+' activity');const componentHeading=node('summary',undefined,'component-detail-heading');componentHeading.append(node('span','Component','hierarchy-pill'),node('span',component.id,'component-name'));componentHeading.hidden=components.length===1;row.append(componentHeading);
      if(components.length===1){const identity=node('div',undefined,'component-identity');identity.append(node('span','Component','hierarchy-pill'),node('span',component.id,'component-name'));row.append(identity);}
      const content=node('div',undefined,'component-activity');
      const resourceKey=state.id+'/resources/'+p.id+'/'+component.id,declared=component.artifact_info||{},resourcesInfo=node('details',undefined,'component-resources');
      resourcesInfo.dataset.disclosure=resourceKey;resourcesInfo.open=disclosure.get(resourceKey)||false;const resourcesInitiallyOpen=resourcesInfo.open;resourcesInfo.ontoggle=()=>{if(resourcesInfo.isConnected){disclosure.set(resourceKey,resourcesInfo.open);if(resourcesInfo.open&&!resourcesInitiallyOpen)manualPackages.add(disclosureKey);}};
      const charts=declared.charts||[...new Map(component.phases.filter(p=>p.kind.startsWith('helm.')&&p.resource?.chart).map(p=>[p.resource.chart,{name:p.resource.chart,release:p.resource.release||p.resource.chart,namespace:p.resource.namespace}])).values()];
      const namespaces=[...new Set(charts.map(c=>c.namespace).filter(Boolean))],commonNamespace=namespaces.length===1&&charts.every(c=>c.namespace===namespaces[0]),images=declared.images||[],hasResources=charts.length||images.length;
      if(hasResources){const header=node('summary','Resources');if(commonNamespace){const pill=node('span',namespaces[0],'resource-namespace-pill');pill.title='Packaged namespace: '+namespaces[0];pill.setAttribute('aria-label','Packaged namespace '+namespaces[0]);header.append(pill);}resourcesInfo.append(header);content.classList.add('has-resources');}
      if(charts.length){
        const scroll=node('div',undefined,'resource-table-scroll'),table=node('table',undefined,'resource-table'),head=node('thead'),headRow=node('tr'),body=node('tbody'),showNamespace=!commonNamespace&&namespaces.length>0,showManifest=charts.some(c=>c.manifest);
        table.setAttribute('aria-label','Packaged Helm resources');table.title='Resources from the packaged definition; runtime namespace overrides are not applied to this view.';
        const columns=[...(showNamespace?[['Namespace','namespace']]:[]),...(showManifest?[['Manifest','manifest']]:[]),['Helm release','release'],['Chart','name'],['Version','version']];
        for(const [label] of columns){const cell=node('th',label);cell.scope='col';headRow.append(cell);}head.append(headRow);table.append(head,body);
        for(const chart of charts){const row=node('tr');for(const [,key] of columns){const value=chart[key]||'—',cell=node('td',value);cell.title=String(value);row.append(cell);}body.append(row);}scroll.append(table);resourcesInfo.append(scroll);
      }
      if(images.length){
        const key=state.id+'/images/'+p.id+'/'+component.id,inventory=node('details',undefined,'resource-images');inventory.dataset.disclosure=key;inventory.open=disclosure.get(key)||false;
        inventory.append(node('summary','Images · '+images.length));inventory.title='Image references declared in the packaged component';
        const list=node('ul');for(const image of images){const item=node('li');item.append(node('code',image));list.append(item);}inventory.append(list);resourcesInfo.append(inventory);
      }
      steps(own.filter(r=>r.definition_owner.component===component.id),component,content,p.name+' / '+component.id);
      const resources=component.phases.filter(p=>p.kind.startsWith('helm.')).map(p=>p.resource);
      const checks=(state.checks||[]).filter(c=>c.current_deployment&&resources.some(r=>r.namespace===c.namespace&&(r.release||r.chart)===(c.release||c.name)));
      if(checks.length){
        const verification=node('div',undefined,'component-verification');verification.append(node('h3','Kubernetes status'));
        verification.title='State observed separately from CLI reports; a snapshot after the session ends.';
        for(const check of checks){
          const good=['deployed','ready'].includes(check.status),row=node('div',undefined,'cluster-result'+(good?' cluster-check':''));
          row.append(node('span',check.kind==='helm-release'?'Helm release':'Deployment','kubernetes-kind'),node('span',check.name,'kubernetes-name'));
          const status=node('span',title(check.status),'kubernetes-state '+(good?'succeeded':check.status==='failed'?'failed':check.status==='waiting'?'running':'unknown'));
          row.append(status,node('span',check.kind==='helm-release'?'Revision '+check.revision:check.ready+'/'+check.desired+' replicas','kubernetes-detail'));
          row.title=check.evidence+' · '+check.namespace+' · independently observed Kubernetes state, not a pipeline step';verification.append(row);
        }
        if(hasResources)resourcesInfo.append(verification);else content.append(verification);
      }
      if(hasResources)content.append(resourcesInfo);
      row.append(content);section.append(row);
    }
    if(!components.length)section.append(node('p','Component definitions are not available from this output source.','unobserved-component'));
    canvas.append(section);
  }
  if(!running)finishedViews.add(state.id);
  const info=node('details',undefined,'session-details');info.dataset.disclosure='session-details';info.open=opened.has('session-details');info.append(node('summary','Session details'));
  const meta=node('dl',undefined,'session-metadata');
  const fields=[['Process',state.source.pid?'PID '+state.source.pid:'Task-owned capture'],['Output',state.source.note]];
  if(state.source.kind==='stock-process'&&state.completed_at)fields.push(['Result','Process ended. Its exit code is unavailable to this watcher; check the deployment terminal.']);
  if(!running&&latest)fields.push(['Last reported activity',latest.message+(latest.resource?' · '+latest.resource:'')]);
  for(const [name,value]of fields)meta.append(node('dt',name),node('dd',value));info.append(meta);
  info.append(node('p','Done can be inferred when the same sequential CLI advances without a reported error. Hover a step for its evidence. Process disappearance is not success; Kubernetes checks remain separate observations.','session-notes'));
  canvas.append(info);
}
function renderPipeline(){
  $('jobs-total').textContent=state.packages.length;
  $('group-toolbar').hidden=graphView!=='pipeline'||liveOnly;
  for(const [id,active]of [['stage-grouping',grouping==='stages'],['dependency-grouping',grouping==='dependencies']]){$(id).classList.toggle('active',active);$(id).setAttribute('aria-pressed',String(active));}
  $('graph-caption').hidden=graphView!=='pipeline';
  if(!['stock-process','task-capture'].includes(state.source?.kind))$('graph-caption').textContent=grouping==='stages'||liveOnly?'Package names and order come from the built bundle. No deployment stages are inferred.':'Task scheduling only — these dependencies are repository policy, not declared bundle metadata.';
  for(const [id,active]of [['pipeline-tab',graphView==='pipeline'],['jobs-tab',graphView==='jobs']]){$(id).classList.toggle('active',active);$(id).setAttribute('aria-selected',String(active));$(id).tabIndex=active?0:-1;}
  $('packages').hidden=graphView!=='pipeline';$('jobs').hidden=graphView!=='jobs';
  if(['stock-process','task-capture'].includes(state.source?.kind)&&graphView==='pipeline'){renderStockPipeline();return;}
  $('packages').classList.remove('stock-pipeline');
  const key=JSON.stringify([state.id,selected,inspectorOpen,grouping,state.mode,state.packages.map(p=>[p.id,p.name,p.version,p.layer,p.dependencies,p.status,p.current_activity,p.retry_supported,p.retry_reason,(p.execution?.components||[]).flatMap(c=>c.phases).filter(q=>q.status==='unknown').length])]);
  if(key===graphKey){scheduleWires();return;}graphKey=key;
  const canvas=$('packages'),left=canvas.scrollLeft,top=canvas.scrollTop;
  const surface=node('div',undefined,'graph-surface'+(grouping==='stages'?' stage-surface':'')),wires=svgNode('svg');wires.classList.add('pipeline-wires');wires.setAttribute('aria-hidden','true');surface.append(wires);
  const columns=node('div',undefined,'graph-columns'),groups=displayedGroups(),names=stageNames(groups);
  const jobsList=node('div',undefined,'jobs-table');
  for(const [index,group]of groups.entries()){
    const column=node('section',undefined,'pipeline-stage'),head=node('div',undefined,'stage-heading');head.append(node('strong',names[index]),node('span',String(group.packages.length),'stage-count'));column.append(head);
    const jobs=node('div',undefined,'stage-jobs');
    for(const id of group.packages){
      const p=state.packages.find(p=>p.id===id),shell=node('div',undefined,'job-pill'+(inspectorOpen&&selected===id?' selected':''));shell.dataset.job=id;
      const button=node('button',undefined,'package pipeline-job');button.setAttribute('aria-label',`${p.name} ${title(p.status)}`);button.setAttribute('aria-pressed',String(inspectorOpen&&selected===id));button.dataset.focusKey='package:'+id;
      button.title=`${p.name} · ${p.version}\n${title(p.status)} · ${p.current_activity}\n${p.dependencies.length?'Prerequisites: '+p.dependencies.join(', '):'No selected prerequisites'}`;
      button.append(statusIcon(p.status),node('span',p.name,'package-name'),node('span',title(p.status),`badge ${p.status} sr-only`));
      const unknown=(p.execution?.components||[]).flatMap(c=>c.phases).filter(q=>q.status==='unknown').length;
      if(unknown){const flag=node('span',`${unknown} unverified`,'unknown-flag');flag.title='Package result is recorded; these operation outcomes are unknown.';button.append(flag);}
      button.onclick=()=>selectPackage(id);shell.append(button);
      if(p.status==='failed'&&!liveOnly){
        const retry=node('button','↻','job-retry');retry.setAttribute('aria-label','Retry '+p.name);retry.dataset.focusKey='retry:'+id;retry.disabled=!p.retry_supported;retry.title=p.retry_reason||'Retry '+p.name;retry.onclick=()=>retryPackage(id);shell.append(retry);
      }
      jobs.append(shell);
      const row=node('div',undefined,'job-list-row'),link=node('button',p.name,'job-list-button');link.dataset.focusKey='job-list:'+id;link.onclick=()=>selectPackage(id);row.append(statusIcon(p.status),link,node('span',title(p.status),'list-status'),node('span',p.current_activity,'list-activity'));jobsList.append(row);
    }column.append(jobs);columns.append(column);
  }
  surface.append(columns);canvas.replaceChildren(surface);canvas.scrollLeft=left;canvas.scrollTop=top;$('jobs').replaceChildren(jobsList);scheduleWires();
}
function scheduleWires(){if(!wireFrame)wireFrame=requestAnimationFrame(()=>{wireFrame=null;drawWires();});}
function drawWires(){
  const surface=$('packages').querySelector('.graph-surface');if(!surface||$('packages').hidden||state?.source?.kind==='stock-process')return;
  if(grouping==='stages'){surface.querySelector('svg').replaceChildren();surface.style.paddingBottom='20px';return;}
  const svg=surface.querySelector('svg'),root=surface.getBoundingClientRect(),boxes=new Map();
  for(const el of surface.querySelectorAll('[data-job]')){const b=el.getBoundingClientRect();boxes.set(el.dataset.job,{left:b.left-root.left,right:b.right-root.left,y:(b.top+b.bottom)/2-root.top,bottom:b.bottom-root.top});}
  const edges=directDependencies(state.packages),parents=new Map();for(const e of edges){if(!parents.has(e.to))parents.set(e.to,[]);parents.get(e.to).push(e.from);}
  const channels=new Map(),bottom=Math.max(0,...[...boxes.values()].map(b=>b.bottom));
  for(const e of edges){const a=boxes.get(e.from),b=boxes.get(e.to);if(b.left-a.right>100){const key=parents.get(e.to).slice().sort().join('\0');if(!channels.has(key))channels.set(key,bottom+24+channels.size*12);}}
  surface.style.paddingBottom=channels.size?`${40+channels.size*12}px`:'20px';
  svg.setAttribute('width',surface.offsetWidth);svg.setAttribute('height',surface.offsetHeight);svg.replaceChildren();
  const bundles=new Map();
  for(const e of edges){
    const a=boxes.get(e.from),b=boxes.get(e.to),bus=b.left-32;let d;
    if(b.left-a.right>100){
      const low=channels.get(parents.get(e.to).slice().sort().join('\0')),out=a.right+24;
      d=`M${a.right},${a.y} H${out-10} Q${out},${a.y} ${out},${a.y+10} V${low-10} Q${out},${low} ${out+10},${low} H${bus-10} Q${bus},${low} ${bus},${low-10} V${b.y+10} Q${bus},${b.y} ${bus+10},${b.y} H${b.left}`;
    }else{
      const r=Math.min(12,Math.abs(b.y-a.y)/2),sign=Math.sign(b.y-a.y);
      d=r?`M${a.right},${a.y} H${bus-r} Q${bus},${a.y} ${bus},${a.y+sign*r} V${b.y-sign*r} Q${bus},${b.y} ${bus+r},${b.y} H${b.left}`:`M${a.right},${a.y} H${b.left}`;
    }
    // Shared parent sets are genuine all-of joins. Separate sets get a small
    // background gap at crossings, so an intersection cannot look like a join.
    const signature=parents.get(e.to).slice().sort().join('\0');
    if(!bundles.has(signature)){const group=svgNode('g'),halos=svgNode('g'),links=svgNode('g');group.append(halos,links);svg.append(group);bundles.set(signature,{halos,links});}
    const bundle=bundles.get(signature),halo=svgNode('path');halo.setAttribute('d',d);halo.classList.add('dependency-halo');bundle.halos.append(halo);
    const path=svgNode('path');path.setAttribute('d',d);path.dataset.source=e.from;path.dataset.target=e.to;path.classList.add('dependency-line');if(inspectorOpen&&(e.from===selected||e.to===selected))path.classList.add('related');bundle.links.append(path);
  }
}
function render(){
  if(!state)return;
  $('job-inspector').hidden=!inspectorOpen;
  const focus=document.activeElement?.dataset.focusKey;
  for(const el of document.querySelectorAll('details[data-disclosure]'))disclosure.set(el.dataset.disclosure,el.open);
  for(const el of document.querySelectorAll('.operation-flow'))if(el.clientWidth)flowScroll.set(el.dataset.flowKey,el.scrollLeft);
  for(const el of document.querySelectorAll('.component-progress-list[data-scroll-key]'))if(el.clientHeight)flowScroll.set(el.dataset.scrollKey,el.scrollTop);
  const known=discoveredRuns.find(r=>r.id===state.id);if(known)known.status=state.status;updateActiveLink();
  $('bundle').textContent=`${state.bundle_name} ${state.version}`;
  const artifactKind=state.artifact_info?.kind;
  $('artifact-kind').textContent=['ZarfPackageConfig','ZarfInitConfig'].includes(artifactKind)?'Package':artifactKind==='UDSBundle'||state.artifact_info?.has_yaml?'Bundle':'Deployment';
  $('artifact-kind').dataset.kind=$('artifact-kind').textContent.toLowerCase();
  const target=state.target.includes(':cluster/')?state.target.split(':cluster/').pop():state.target;
  const packageNames=state.packages.map(p=>p.name);
  $('target').replaceChildren();
  if(liveOnly&&state.source?.kind==='stock-process'){
    for(const name of packageNames.length<=2?packageNames:[packageNames.length+' packages'])$('target').append(node('span',name,'header-package-pill'));
    if(state.artifact_info?.architecture){const arch=node('span',state.artifact_info.architecture,'header-arch-pill');arch.setAttribute('aria-label','Artifact architecture '+state.artifact_info.architecture);$('target').append(arch);}
  }else $('target').textContent=`${state.status==='completed'?'Deployed to':'Target'} ${target}`;
  if(liveOnly&&['stock-process','task-capture'].includes(state.source?.kind)&&(state.artifact_info?.kind==='UDSBundle'||!state.artifact_info?.kind&&state.artifact_info?.has_yaml)){const yaml=node('button','Bundle YAML','session-yaml');yaml.dataset.focusKey='bundle-yaml';yaml.title='View the packaged bundle definition';yaml.onclick=()=>showDefinition();$('target').append(yaml);}
  const connection=liveOnly?clusterConnectionState(state):null;
  if(connection){const indicator=node('span',undefined,'cluster-connection '+connection.state);indicator.dataset.connectionState=connection.state;indicator.title=connection.evidence;if(connection.state==='running')indicator.append(stepIcon('running'));indicator.append(node('span',connection.label));$('target').append(indicator);}
  $('target').title=liveOnly?packageNames.join(', '):state.target+' · '+packageNames.join(', ');$('full-target').textContent=state.target;
  $('started').textContent=`${state.started_at?'Started':state.source?.kind==='stock-process'?'Attached':'Created'} ${new Date((state.started_at||state.created_at)*1000).toLocaleString()}`;
  $('run-reference').textContent=`Run ${state.id.slice(0,8)}`;$('run-reference').title=state.id;$('run-id').textContent=state.id;
  const reportedErrors=state.source?.kind==='stock-process'&&(state.reports||[]).some(r=>r.message==='action failed'||r.kind==='deployment.error');
  const blindProcess=state.source?.kind==='stock-process'&&state.status==='deploying'&&state.source.output_complete===false&&(!(state.reports||[]).length||state.source.activity_available===false);
  $('run-status').textContent=reportedErrors?'Errors reported':blindProcess?'Process running':state.source?.kind==='stock-process'&&state.completed_at?'Process ended':title(state.status);$('run-status').className=`run-status ${reportedErrors?'failed':state.status}`;
  $('run-status').title=state.source?.kind==='stock-process'&&state.completed_at?'Exit code unavailable to this watcher; check the deployment terminal.':blindProcess?'Process is alive; the attached log does not expose current step activity.':'';
  document.body.classList.toggle('stock-observation',['stock-process','task-capture'].includes(state.source?.kind));
  $('count').textContent=`${state.packages.filter(p=>p.status==='completed').length} of ${state.packages.length}`;
  $('elapsed').textContent=elapsed(state.started_at,state.completed_at);$('mode').textContent=title(state.mode);
  $('status-counts').replaceChildren();for(const status of ['deploying','waiting','failed','unknown']){const n=state.packages.filter(p=>p.status===status).length;if(n)$('status-counts').append(node('span',`${n} ${status==='deploying'?'running':status}`,status));}
  if(state.source?.kind==='stock-process'&&state.completed_at&&state.status==='unknown')notice('');
  else if(state.error||state.orchestration_error)notice(state.error||state.orchestration_error);
  else if(state.status==='deploying'&&state.heartbeat&&Date.now()/1000-state.heartbeat>20)notice('Engine heartbeat is stale. Unknown outcomes are not treated as success.');
  const preparing=(state.invocations||[]).filter(i=>i.status==='running'&&i.observer==='awaiting');
  $('invocation-notice').hidden=!preparing.length;
  $('invocation-notice').textContent=`${preparing.length} UDS invocation(s) loading or awaiting the optional execution observer. No component steps are assumed; stock CLI results have limited detail.`;
  renderPipeline();
  const p=packageState();if(!p)return;if(autoAttempt)attempt=p.attempts.length?p.attempts[p.attempts.length-1].id:null;
  const a=selectedAttempt(),x=selectedExecution();
  $('detail-name').textContent=p.name;$('detail-version').textContent=`${p.version.split('@')[0]} · ${a?'Attempt '+a.number+' · '+title(a.status):'Not started'}`;$('detail-version').title=p.version;
  $('operation').textContent=a&&a.id!==p.attempts[p.attempts.length-1].id?`Attempt ${a.number}: ${title(a.status)} · historical execution`:p.current_activity||title(p.status);
  $('package-meta').replaceChildren();for(const text of [`Started ${clock(a?.started_at)}`,`Elapsed ${elapsed(a?.started_at,a?.completed_at)}`,`Finished ${clock(a?.completed_at)}`])$('package-meta').append(node('span',text));
  $('error').hidden=!(a?.error||p.error);$('error').textContent=a?.error||p.error||'';
  $('retry').hidden=liveOnly||p.status!=='failed';$('retry').disabled=!p.retry_supported;$('retry').textContent=p.operation==='Retry queued'?'Retry queued':'Retry package';$('retry-reason').textContent=['failed','cancelled','unknown'].includes(p.status)?p.retry_reason||'':'';
  const key=p.attempts.map(a=>`${a.id}:${a.status}`).join('|');if($('attempt').dataset.optionsKey!==key){$('attempt').replaceChildren();if(!p.attempts.length)$('attempt').append(node('option','No attempt yet'));for(const item of p.attempts){const o=node('option',`Attempt ${item.number} · ${item.status}`);o.value=item.id;$('attempt').append(o);}$('attempt').dataset.optionsKey=key;}if(attempt)$('attempt').value=attempt;
  let tracking=p.tracking_notice||'';
  if(x.observation==='definition-only')tracking='These components and applicable operations come from the package definition. Selection and execution outcomes were not exposed by the CLI; definitions never prove completion.';
  else if(x.observation==='legacy')tracking='This attempt predates structured execution tracking. Package results and original logs are retained; no component or phase progress is reconstructed.';
  else if(!x.components.length&&['awaiting','structured'].includes(x.observation))tracking='Waiting for the CLI-selected package definition. No generic image, Helm, or readiness steps are assumed.';
  else if(x.observation==='partial')tracking='Some execution events are missing. Unverified outcomes are explicitly unknown.';
  else if(x.observation==='unavailable')tracking='Stock CLI: command results and original output only. Component/image/Helm outcomes are unknown unless the CLI exposes execution events. No custom CLI build is required or selected.';
  $('tracking-notice').hidden=!tracking;$('tracking-notice').textContent=tracking;
  renderComponents(x);
  $('package-view').classList.toggle('active',!full);$('full-view').classList.toggle('active',full);
  $('activity-view').classList.toggle('active',!rawMode);$('raw-view').classList.toggle('active',rawMode);$('logs').hidden=!rawMode;$('activity-feed').hidden=rawMode;
  $('log-title').textContent=liveOnly?'Deployment output':rawMode?'Original execution output':'Execution events';
  $('log-subtitle').textContent=liveOnly?((full?'Full deployment output':componentFilter?`${p.name} / ${componentFilter} output`:`${p.name} output`)+(state.source?.output_complete===false?' · partial capture':'')+($('log-search').value||$('log-level').value?' · filtered view':logAnchorLabel?' · '+logAnchorLabel:'')):full?'All packages · all attempts · all captured streams':`${p.name} · ${a?'attempt '+a.number:'not started'}`;
  const feedState=outputFeedState(state,liveOnly);
  $('follow-control').hidden=!!feedState;$('follow').disabled=!!feedState;
  $('output-state').hidden=!feedState;$('output-state').textContent=feedState||'';
  $('log-count').title=`Browser display limit: ${MAX_ROWS.toLocaleString()} records. Jump to start reads the beginning of this capture; history pages contain ${LOG_PAGE} records.`;
  $('copy').title='Copy the currently loaded output records';
  $('clear-scope').hidden=!componentFilter;
  $('log-scope').textContent=full?(state.source?.kind==='stock-process'?'Original CLI output · process-owned file':'Full output includes unscoped batch preparation.'):componentFilter?`${componentFilter}${phaseFilter?' / '+phaseFilter:''} · only reliably attributed output`:'Package output; shared/unattributed batch lines remain in Full deployment.';
  const phase=x.components.find(c=>c.id===componentFilter)?.phases.find(q=>q.id===phaseFilter);
  const runs=phase?.executions||[];$('operation-run').hidden=!phaseFilter||runs.length<2;
  const executionKey=runs.map(r=>r.id+':'+r.status).join('|');if($('operation-run').dataset.optionsKey!==executionKey){$('operation-run').replaceChildren(node('option','All internal executions'));$('operation-run').firstChild.value='';for(const [i,item]of runs.entries()){const o=node('option',`${state.pipeline.operation_labels[item.kind]||item.kind} · execution ${i+1} · ${item.status}`);o.value=item.id;$('operation-run').append(o);}$('operation-run').dataset.optionsKey=executionKey;}$('operation-run').value=operationFilter||'';
  renderActivity();updateLogNavigation();
  updateLogCount();
  if(focus){const el=[...document.querySelectorAll('[data-focus-key]')].find(e=>e.dataset.focusKey===focus);if(el&&document.activeElement===document.body)el.focus({preventScroll:true});}
}
function renderComponents(x){
  const list=$('components');list.replaceChildren();
  for(const c of x.components){
    const key=`${selected}/${attempt}/${c.id}`,details=node('details',undefined,'component-job');details.dataset.disclosure=key;details.open=disclosure.has(key)?disclosure.get(key):['running','failed'].includes(c.status)||x.components.length===1;
    const head=node('summary',undefined,'component-heading');head.append(statusIcon(c.status),node('strong',c.id),node('span',`${c.phases.length} operations`,'component-count'),node('span',!c.observed&&c.status==='pending'?'Expected':title(c.status),`component-status ${c.status}`));
    const unknown=c.phases.filter(q=>q.status==='unknown').length;if(unknown)head.append(node('span',`${unknown} unverified`,'unknown-flag'));
    details.append(head);
    if(c.reason||c.error)details.append(node('p',c.reason||c.error,'component-note'));
    // Runtime-only operations (for example, cluster connection or generated
    // charts) belong at their observed start, not after all YAML definitions.
    const phases=[...c.phases].sort((a,b)=>Number(b.observed)-Number(a.observed)||((a.started_at||a.completed_at||Infinity)-(b.started_at||b.completed_at||Infinity)));
    const flow=node('div',undefined,'operation-flow');flow.dataset.flowKey=key;
    for(const phase of phases){
      const item=node('div',undefined,'phase-item operation-stage');
      const headings={'cluster.connect':'Connect','actions.before':'Before deploy','files.copy':'Files','images.push':'Images','repositories.push':'Repositories','data.inject':'Data','helm.apply':'Helm','helm.install':'Install','helm.upgrade':'Upgrade','helm.rollback':'Rollback','health.wait':'Readiness','health.component':'Health checks','manifests.apply':'Manifests','actions.after':'After deploy','actions.success':'Success actions','actions.failure':'Failure actions'};
      item.append(node('div',headings[phase.kind]||phase.kind,'operation-stage-name'));const button=node('button',undefined,`phase-job ${componentFilter===c.id&&phaseFilter===phase.id?'selected':''}`);button.dataset.focusKey=`phase:${c.id}/${phase.id}`;button.dataset.component=c.id;button.dataset.phase=phase.id;button.setAttribute('aria-label',`${phase.label} ${title(phase.status)}`);
      const text=node('span',undefined,'phase-label');text.append(node('strong',phase.label),node('span',phase.status==='skipped'?'Explicit skip from the execution layer':phase.observed?'Observed function boundary':phase.conditional?'Expected · conditional · not observed':'Expected from selected definition · not observed','phase-evidence'));
      button.title=`${phase.label}\n${title(phase.status)} · ${phase.observed?'Observed execution boundary':'Expected from definition; not observed'}${phase.error?'\n'+phase.error:''}`;
      button.append(statusIcon(phase.status),text,node('span',!phase.observed&&phase.status==='pending'?'Expected':title(phase.status),`phase-status ${phase.status}`));
      button.onclick=()=>{if(liveOnly&&!phase.observed)clearScope();else{componentFilter=c.id;phaseFilter=phase.id;operationFilter=null;}full=false;rawMode=true;render();loadLogs().catch(e=>notice(e.message));};item.append(button);
      if(phase.reason||phase.error)item.append(node('p',phase.reason||phase.error,'phase-note'));
      if(phase.executions.length>1)item.append(node('p',`${phase.executions.length} internal executions retained · ${phase.executions.map(e=>e.status).join(' → ')}`,'phase-note'));
      flow.append(item);
    }
    details.append(flow);
    if(!c.phases.length)details.append(node('p',c.status==='skipped'?'Explicitly excluded by the CLI selection; no operations were scheduled.':'No phase definition was reported for this component.','component-note'));
    list.append(details);flow.scrollLeft=flowScroll.get(key)||0;
  }
}
function renderActivity(){
  if(!state)return;const items=[];
  for(const p of full?state.packages:[packageState()])for(const a of p.attempts){
    if(!full&&a.id!==attempt)continue;
    if(a.started_at)items.push({time:a.started_at,title:a.execution?'Attempt started':'Recorded attempt start (legacy)',detail:`${p.name} · attempt ${a.number}`,status:'running'});
    for(const c of a.execution?.components||[]){if(componentFilter&&c.id!==componentFilter)continue;
      if(c.observed&&!phaseFilter){
        if(c.started_at)items.push({time:c.started_at,title:'Component started',detail:`${p.name} / ${c.id}`,status:'running'});
        if(c.completed_at)items.push({time:c.completed_at,title:'Component '+c.status,detail:c.error||c.reason||`${p.name} / ${c.id}`,status:c.status});
      }
      for(const phase of c.phases){if(phaseFilter&&phase.id!==phaseFilter)continue;
        for(const e of phase.executions){if(operationFilter&&e.id!==operationFilter)continue;const label=state.pipeline.operation_labels[e.kind]||phase.label;
          if(e.started_at)items.push({time:e.started_at,title:label+' started',detail:`${p.name} / ${c.id}`,status:'running'});
          if(e.completed_at)items.push({time:e.completed_at,title:label+' '+e.status,detail:e.error||`${p.name} / ${c.id}`,status:e.status});
        }
        if(phase.status==='skipped'&&phase.observed&&phase.completed_at)items.push({time:phase.completed_at,title:phase.label+' skipped',detail:phase.reason||c.id,status:'skipped'});
      }
    }
    if(a.completed_at&&!componentFilter)items.push({time:a.completed_at,title:(a.execution?'Package ':'Recorded package result (legacy): ')+title(a.status).toLowerCase(),detail:p.name+' · attempt '+a.number,status:a.status});
  }
  items.sort((a,b)=>a.time-b.time);const visible=items.slice(-MAX_TIMELINE),feed=$('activity-feed'),top=feed.scrollTop;
  const fragment=document.createDocumentFragment();for(const item of visible){const row=node('div',undefined,`activity-entry ${item.status}`);row.append(statusIcon(item.status));const text=node('div',undefined,'activity-text');text.append(node('strong',item.title),node('span',item.detail,'activity-resource'));row.append(text,node('time',clock(item.time)));fragment.append(row);}
  if(!visible.length){const empty=node('div',undefined,'feed-empty');empty.append(node('strong','No verified operation events recorded'),document.createTextNode('Definitions and raw output do not prove that a phase ran or succeeded. Use Raw logs for troubleshooting.'));fragment.append(empty);}
  feed.replaceChildren(fragment);feed.scrollTop=$('follow').checked?feed.scrollHeight:top;
  if(!rawMode)$('log-count').textContent=`${visible.length} of ${items.length} recorded timeline events`;
}
function appendLogText(parent,text,query,budget){
  if(!query){parent.append(document.createTextNode(text));return;}
  // Literal matching only. Build DOM text nodes, never interpret log text as HTML.
  const pattern=new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi');let offset=0,match;
  while(budget.remaining>0&&(match=pattern.exec(text))!==null){
    parent.append(document.createTextNode(text.slice(offset,match.index)),node('mark',match[0],'log-search-match'));
    offset=match.index+match[0].length;budget.remaining--;budget.count++;
  }
  if(!budget.remaining&&pattern.test(text))budget.limited=true;
  parent.append(document.createTextNode(text.slice(offset)));
}
function updateLogCount(){if(rawMode)$('log-count').textContent=`${logs.length.toLocaleString()} records loaded`+($('log-search').value?` · ${logHighlightCount.toLocaleString()} matches highlighted${logHighlightsLimited?' (display limit)':''}`:'');}
function logLine(item,budget){
  const row=node('div',undefined,`log-line ${item.data.level}-line`);row.dataset.logId=item.id;row.classList.toggle('log-anchor',item.id===logAnchorId);
  if(!liveOnly){row.append(node('span',clock(item.data.source_timestamp||item.timestamp)+'  ','log-time'));if(full)row.append(node('span',`[${item.package||'batch:'+String(item.process||item.data.process_id||'unknown').slice(0,8)} / ${item.attempt||'unscoped'}] `,'log-package'));}
  appendLogText(row,item.data.text.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,''),$('log-search').value,budget);return row;
}
// SDK parsing here is for log navigation only, never lifecycle inference.
const NAVIGATION_MESSAGES={'processing Helm chart':'helm.prepare','performing Helm install':'helm.install','performing Helm upgrade':'helm.upgrade','running health checks':'health.wait','pushing image':'images.push','image push in progress':'images.push','done pushing images':'images.push','pulling images':'images.pull','saving image':'images.pull','done pulling images':'images.pull','running command':'actions.command','action succeeded':'actions.command','action failed':'actions.command'};
function navigationReport(raw){
  const text=raw.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/[\r\n]+$/,'').split('\r').pop().trim();let fields,message;
  try{fields=JSON.parse(text);if(!fields||Array.isArray(fields)||typeof fields!=='object')return null;message=fields.msg;}catch{
    const line=text.match(/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d (?:INF|ERR|WRN|DBG) (.*)$/);if(!line)return null;
    message=Object.keys(NAVIGATION_MESSAGES).find(m=>line[1]===m||line[1].startsWith(m+' '));if(!message)return null;
    const suffix=line[1].slice(message.length).trim();fields={};
    for(const m of suffix.matchAll(/\b(name|chart|package)=("(?:\\.|[^"\\])*"|[^\s]+)/g)){try{fields[m[1]]=m[2].startsWith('"')?JSON.parse(m[2]):m[2];}catch{return null;}}
    if(suffix.startsWith('cmd=')){fields.cmd=suffix.slice(4);if(message==='action failed'){const parts=fields.cmd.split(' err=');if(parts.length!==2)return null;fields.cmd=parts[0];}}
  }
  const kind=NAVIGATION_MESSAGES[message];if(!kind)return null;
  return {kind,resource:fields.chart||fields.name||fields.package||null,command:typeof fields.cmd==='string'?fields.cmd:null};
}
async function locateActivityLog(items,mine,id){
  const key=id+'/'+items.map(r=>r.id).join('|');if(activityLogPositions.has(key))return activityLogPositions.get(key);
  const direct=items.map(r=>r.first_log_id).filter(n=>Number.isSafeInteger(n)&&n>0);let position=direct.length?Math.min(...direct):null;
  if(!position){
    // Older held captures lack source-record IDs. Locate an exact SDK identity,
    // not an arbitrary substring/user echo; then open unfiltered context.
    const first=items.find(r=>r.resource)||items[0],query=first.kind==='actions.command'?null:first.resource||first.message;let after=0;
    for(let page=0;page<64&&!position;page++){
      if(mine!==logGeneration||id!==run)return null;
      const url=new URL(logURL(`latest=0&limit=500&after=${after}`),location.href);if(query)url.searchParams.set('search',query);else url.searchParams.delete('search');
      const rows=await request(url);if(mine!==logGeneration||id!==run)return null;
      for(const row of rows){const found=navigationReport(row.data.text);if(!found)continue;
        let hash=null;if(found.command){const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(found.command));hash=[...new Uint8Array(bytes)].map(n=>n.toString(16).padStart(2,'0')).join('').slice(0,12);}
        if(items.some(r=>r.kind===found.kind&&(r.kind==='actions.command'?(r.action_id===hash||r.declaration_id&&r.resource===found.command):r.resource&&r.resource===found.resource))){position=row.id;break;}
      }
      if(rows.length<500)break;after=rows[rows.length-1].id;
    }
  }
  if(position){if(activityLogPositions.size>=2000)activityLogPositions.delete(activityLogPositions.keys().next().value);activityLogPositions.set(key,position);}return position;
}
async function loadActivityLogs(items,label){
  logHistory=true;$('follow').checked=false;logAnchorId=null;logAnchorLabel='Locating '+label;
  const mine=beginLogRequest(),id=run;pausedNew=0;render();
  try{
    const anchor=await locateActivityLog(items,mine,id);if(mine!==logGeneration||id!==run)return;
    if(!anchor)throw Error('No exact captured SDK record could be located for this activity. Use Search original output or Latest output.');
    const preceding=await request(logURL(`latest=1&limit=41&before=${anchor}`));if(mine!==logGeneration||id!==run)return;
    const before=preceding.slice(-40),slots=LOG_PAGE-before.length,following=await request(logURL(`latest=0&limit=${slots+1}&after=${anchor-1}`));if(mine!==logGeneration||id!==run)return;
    if(following[0]?.id!==anchor)throw Error('The exact captured record is unavailable; no guessed log position was used.');
    logs=[...before,...following.slice(0,slots)];logIds=new Set(logs.map(r=>r.id));logEarlier=preceding.length>40;logLater=following.length>slots||pausedNew>0;logAnchorId=anchor;logAnchorLabel='Jumped to '+label;notice('');drawLogs();render();
    const row=$('logs').querySelector('.log-anchor');if(row){const box=$('logs');box.scrollTop+=row.getBoundingClientRect().top-box.getBoundingClientRect().top;}
  }catch(error){if(mine===logGeneration){logAnchorLabel='Exact activity position unavailable';render();}throw error;}
  finally{if(mine===logGeneration){logLoading=false;updateLogNavigation();}}
}
function logPage(rows,fromEnd){return {rows:fromEnd?rows.slice(-LOG_PAGE):rows.slice(0,LOG_PAGE),more:rows.length>LOG_PAGE};}
function updateLogNavigation(){
  $('log-start').hidden=!liveOnly||!rawMode;$('log-start').disabled=logLoading||!logs.length;
  $('older').disabled=logLoading||!logEarlier;
  $('newer').hidden=!liveOnly||!rawMode||!logHistory;$('newer').disabled=logLoading||!logLater;
  $('log-latest').hidden=!liveOnly||!rawMode||!(logHistory||!$('follow').checked);$('log-latest').disabled=logLoading;
  $('new-lines').hidden=!pausedNew;$('new-lines').textContent=`${pausedNew} new records`;
  const boundary=$('log-boundary');if(boundary){const filtered=$('log-search').value||$('log-level').value;boundary.textContent=logLoading?'Loading output…':!logs.length?'No output in this view':logEarlier?'Earlier output available':filtered?'Start of matching output':full?'Start of captured output':'Start of scoped output';boundary.dataset.atStart=String(!logLoading&&!!logs.length&&!logEarlier);boundary.title=state?.source?.output_complete===false?'Only available captured output is shown; earlier terminal-only output cannot be recovered.':'This marks the beginning of the captured output, not terminal scrollback.';}
}
function drawLogs(prepend=false){
  const box=$('logs'),top=box.scrollTop,height=box.scrollHeight,fragment=document.createDocumentFragment(),budget={remaining:MAX_HIGHLIGHTS,count:0,limited:false};
  if(liveOnly)fragment.append(node('div',undefined,'log-boundary'));for(const row of logs)fragment.append(logLine(row,budget));
  logHighlightCount=budget.count;logHighlightsLimited=budget.limited;box.replaceChildren(fragment);if(liveOnly)box.firstElementChild.id='log-boundary';updateLogNavigation();
  box.scrollTop=$('follow').checked?box.scrollHeight:top+(prepend?Math.max(0,box.scrollHeight-height):0);updateLogCount();
}
function addLogs(rows,prepend=false){
  const fresh=rows.filter(row=>!logIds.has(row.id));if(!fresh.length)return;
  logs.push(...fresh);logs.sort((a,b)=>a.id-b.id);if(logs.length>MAX_ROWS){logs=prepend?logs.slice(0,MAX_ROWS):logs.slice(-MAX_ROWS);if(prepend)logLater=true;else logEarlier=true;}logIds=new Set(logs.map(r=>r.id));drawLogs(prepend);
}
function queueLog(item){
  if(logIds.has(item.id)||item.id<=(logs[logs.length-1]?.id||0))return;
  if(logHistory||!$('follow').checked){pausedNew++;logLater=true;updateLogNavigation();return;}
  pendingRows.push(item);if(pendingRows.length>=MAX_ROWS*2)pendingRows.splice(0,MAX_ROWS);
  if(!logTimer)logTimer=setTimeout(()=>{logTimer=null;const rows=pendingRows;pendingRows=[];if(logHistory||!$('follow').checked){pausedNew+=rows.length;logLater=true;updateLogNavigation();}else addLogs(rows);},70);
}
function beginLogRequest(){const mine=++logGeneration;if(logTimer){clearTimeout(logTimer);logTimer=null;}pendingRows=[];logLoading=true;updateLogNavigation();return mine;}
async function loadLogs(edge='latest'){
  logAnchorId=null;logAnchorLabel='';
  logHistory=edge==='start';if(logHistory)$('follow').checked=false;
  const mine=beginLogRequest(),id=run;pausedNew=0;logEarlier=false;logLater=false;logs=[];logIds=new Set();drawLogs();renderActivity();
  try{const page=logPage(await request(logURL(`latest=${edge==='start'?0:1}&limit=${LOG_PAGE+1}`)),edge!=='start');if(mine!==logGeneration||id!==run)return;
    logEarlier=edge!=='start'&&page.more;logLater=edge==='start'&&page.more||pausedNew>0;addLogs(page.rows);$('logs').scrollTop=edge==='start'?0:$('logs').scrollHeight;
    if(!page.rows.length&&componentFilter)$('log-count').textContent='No output with reliable attribution for this scope; clear the filter for package output.';
  }finally{if(mine===logGeneration){logLoading=false;updateLogNavigation();}}
}
async function pageLogs(direction){
  if(logLoading||!logs.length)return;
  logAnchorId=null;logAnchorLabel='';logHistory=true;$('follow').checked=false;const mine=beginLogRequest(),id=run,back=direction==='older';
  try{const page=logPage(await request(logURL(`latest=${back?1:0}&limit=${LOG_PAGE+1}&${back?'before='+logs[0].id:'after='+logs[logs.length-1].id}`)),back);if(mine!==logGeneration||id!==run)return;
    if(!page.rows.length){if(back)logEarlier=false;else logLater=false;return;}
    if(back){logEarlier=page.more;logLater=liveOnly||logLater;}else{logLater=page.more;logEarlier=true;}
    if(liveOnly){logs=page.rows;logIds=new Set(logs.map(r=>r.id));drawLogs();$('logs').scrollTop=0;}else addLogs(page.rows,back);
  }finally{if(mine===logGeneration){logLoading=false;updateLogNavigation();}}
}
function latestLogs(){$('follow').checked=true;return loadLogs();}
if(liveOnly){
  $('nav-deployments').textContent='Current tasks';$('breadcrumb-home').textContent='Current tasks';$('history-title').textContent='Current tasks';
  $('history-description').textContent='Deploy in another terminal; active deployments appear here automatically.';
  $('history-empty').querySelector('h2').textContent='Ready to watch a deployment';
  $('history-empty').querySelector('p').textContent='With capture setup enabled, open a new terminal and run your usual uds deploy command. This viewer does not start deployments.';
  $('log-status').textContent='Original output retained.';
  document.title='UDS · Local watcher';
}
$('nav-deployments').onclick=$('breadcrumb-home').onclick=()=>showPage('history',true);
$('nav-pipeline').onclick=()=>{if(state)showPage('pipeline',true);};
$('deployment-search').oninput=renderHistory;$('deployment-status').onchange=renderHistory;
for(const [id,mode]of [['stage-grouping','stages'],['dependency-grouping','dependencies']])$(id).onclick=()=>{grouping=mode;renderPipeline();};
window.addEventListener('popstate',()=>{const id=new URL(location.href).searchParams.get('deployment');if(id){if(id===run&&state)showPage('pipeline');else chooseRun(id,false);}else showPage('history');});
$('history').onchange=()=>chooseRun($('history').value);$('active-run').onclick=()=>{if(activeRunId)chooseRun(activeRunId);};
$('activity-view').onclick=()=>{rawMode=false;render();};$('raw-view').onclick=()=>{rawMode=true;render();};
$('attempt').onchange=()=>{attempt=$('attempt').value;autoAttempt=false;clearScope();render();loadLogs().catch(e=>notice(e.message));};
$('full-view').onclick=()=>{full=true;clearScope();render();loadLogs().catch(e=>notice(e.message));};$('package-view').onclick=()=>{full=false;clearScope();render();loadLogs().catch(e=>notice(e.message));};
$('clear-scope').onclick=()=>{clearScope();render();loadLogs().catch(e=>notice(e.message));};
$('operation-run').onchange=()=>{operationFilter=$('operation-run').value||null;loadLogs().catch(e=>notice(e.message));};
$('log-search').oninput=()=>{logGeneration++;logLoading=false;logAnchorId=null;logAnchorLabel='';rawMode=true;render();drawLogs();clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadLogs().catch(e=>notice(e.message)),250);};$('log-level').onchange=()=>{rawMode=true;render();loadLogs().catch(e=>notice(e.message));};
$('log-start').onclick=()=>loadLogs('start').catch(e=>notice(e.message));
$('older').onclick=()=>pageLogs('older').catch(e=>notice(e.message));$('newer').onclick=()=>pageLogs('newer').catch(e=>notice(e.message));
$('log-latest').onclick=$('new-lines').onclick=()=>latestLogs().catch(e=>notice(e.message));
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(logs.map(r=>r.data.raw).join(''));$('copy').textContent='Copied';setTimeout(()=>$('copy').textContent='Copy',1000);}catch(e){notice(e.message);}};
$('download').onclick=()=>{const link=node('a');link.href=logURL('download=1');link.download=`${run}-original.log`;link.click();};
async function retryPackage(id){if(liveOnly){notice('Read-only watcher. Retry from your deployment terminal.');return;}const p=state.packages.find(p=>p.id===id);if(!confirm(`Retry ${p.name} with this deployment's saved bundle, configuration, and context? Successful packages will not be restarted.`))return;$('retry').disabled=true;try{await request(`${api}/${run}/packages/${encodeURIComponent(p.id)}/retry`,{method:'POST',headers:{'Content-Type':'application/json','X-Deploy-Action':'retry-or-start'},body:'{}'});if(selected===id)autoAttempt=true;await refreshState();}catch(e){notice(e.message);$('retry').disabled=false;}}
$('retry').onclick=()=>retryPackage(selected);
$('close-output').onclick=()=>{inspectorOpen=false;render();const el=[...document.querySelectorAll('[data-focus-key]')].find(e=>e.dataset.focusKey===document.body.dataset.outputFocus);if(el)el.focus({preventScroll:true});};
$('close-output').hidden=!liveOnly;
$('close-inspector').onclick=()=>{inspectorOpen=false;render();const key=(graphView==='pipeline'?'package:':'job-list:')+selected;const job=[...document.querySelectorAll('[data-focus-key]')].find(e=>e.dataset.focusKey===key);if(job)job.focus({preventScroll:true});$('pipeline-tab').scrollIntoView({block:'nearest'});};
for(const [id,view]of [['pipeline-tab','pipeline'],['jobs-tab','jobs']])$(id).onclick=()=>{graphView=view;renderPipeline();};
for(const id of ['pipeline-tab','jobs-tab'])$(id).onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const target=e.key==='Home'?'pipeline-tab':e.key==='End'?'jobs-tab':id==='pipeline-tab'?'jobs-tab':'pipeline-tab';$(target).click();$(target).focus();}};
new ResizeObserver(scheduleWires).observe($('packages'));
for(const id of ['logs','activity-feed'])$(id).addEventListener('wheel',()=>{const box=$(id);if(box.scrollTop+box.clientHeight<box.scrollHeight-40)$('follow').checked=false;},{passive:true});
$('follow').onchange=()=>{if($('follow').checked){if(logHistory||pausedNew)loadLogs().catch(e=>notice(e.message));else{const box=$(rawMode?'logs':'activity-feed');box.scrollTop=box.scrollHeight;}}};
window.addEventListener('online',()=>{if(state){refreshState();if($('follow').checked)loadLogs().catch(e=>notice(e.message));}});
setInterval(()=>{if(pageView==='history')renderHistory();else if(state)render();},1000);setInterval(discover,5000);discover();
