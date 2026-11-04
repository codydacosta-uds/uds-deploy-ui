// Isolated discovery-policy fixtures. No fake data enters a live viewer.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/uds_deploy/web/app.js'),'utf8');
const begin=source.indexOf('function isActiveRun('),end=source.indexOf('async function chooseRun(',begin);
assert.ok(begin>=0&&end>begin);
const old={id:'old',status:'unknown',created_at:1},active={id:'new',status:'deploying',created_at:2};
function fixture(runs=[active,old]){
 const elements=new Map(),chosen=[],notices=[];
 const element=id=>{if(!elements.has(id))elements.set(id,{value:'',dataset:{},replaceChildren(){},append(){}});return elements.get(id);};
 const context=vm.createContext({URL,location:{href:'http://127.0.0.1/fixture/'},api:'/fixture/api/deployments',
  discovering:false,autoFollowRuns:true,matrixParent:null,liveOnly:true,pageView:'pipeline',initialRoute:false,run:'old',state:old,discoveredRuns:[old],
  $:element,node:()=>({}),renderHistory(){},updateActiveLink(){},notice:message=>notices.push(message),
  request:async url=>url.endsWith('/processes')?[]:runs,
  chooseRun:async(id,navigate)=>{chosen.push({id,navigate});context.run=id;context.state=runs.find(r=>r.id===id);},
  refreshState:async()=>{},showPage(view){context.pageView=view;}});
 vm.runInContext("'use strict';\n"+source.slice(begin,end),context);
 return {context,chosen,notices};
}
(async()=>{
 const {context:c,chosen}=fixture();
 assert.equal(c.nextActiveRun([active,old],'old'),'new','A retained completed run must not block the next deployment');
 assert.equal(c.nextActiveRun([active,old],'new'),null,'Keep following the current active run');
 assert.equal(c.nextActiveRun([active,{...old,status:'deploying'}],'old'),null,'Do not choose between concurrent deployments');
 assert.equal(c.nextActiveRun([old],'old'),null);
 assert.equal(c.nextActiveRun([{...active,created_at:0},old],'old'),null,'Do not jump back to an older still-running deployment');
 assert.equal(c.nextActiveRun([{...active,created_at:old.created_at},old],'old'),null,'Ambiguous start ordering must not steal focus');
 assert.equal(c.nextActiveRun([active],'gone'),'new','Keep the previous missing-run fallback');
 await c.discover();assert.deepEqual(chosen,[{id:'new',navigate:false}]);assert.equal(c.discovering,false);
 for(const settings of [{autoFollowRuns:false},{pageView:'history'},{liveOnly:false}]){
  const test=fixture();Object.assign(test.context,settings);await test.context.discover();assert.deepEqual(test.chosen,[],'Preserve manual/history/non-live selection');
 }
 const concurrent=fixture([active,{...old,status:'deploying'}]);await concurrent.context.discover();assert.deepEqual(concurrent.chosen,[]);
 const grouped=fixture([{...active,id:'matrix-parent',matrix:{jobs:[]}}]);grouped.context.matrixParent={id:'matrix-parent'};grouped.context.run='native-child';await grouped.context.discover();assert.deepEqual(grouped.chosen,[],'A parent matrix must not steal focus from its selected child');assert.equal(grouped.context.matrixParent.status,'deploying','Keep the parent matrix fresh while watching child logs');
 // Exercise the actual manual-selection policy before chooseRun's DOM work.
 const manualStart=source.indexOf('async function chooseRun('),manualEnd=source.indexOf('  generation++;',manualStart);
 assert.ok(manualEnd>manualStart);vm.runInContext(source.slice(manualStart,manualEnd)+'}',c);
 await c.chooseRun('old');assert.equal(c.autoFollowRuns,false,'Manually selecting a finished run pins it');
 await c.chooseRun('new');assert.equal(c.autoFollowRuns,true,'Selecting the active run resumes following');
 await c.chooseRun('old',false);assert.equal(c.autoFollowRuns,true,'Automatic navigation does not disable following');
 const busy=fixture();let release,calls=0;
 busy.context.request=url=>{if(url.endsWith('/processes'))return Promise.resolve([]);calls++;return new Promise(resolve=>{release=resolve;});};
 const pending=busy.context.discover();await busy.context.discover();assert.equal(calls,1,'Slow metadata requests must not pile up at the faster cadence');
 release([active,old]);await pending;assert.equal(busy.context.discovering,false);
 busy.context.request=async()=>{throw Error('isolated fixture error');};await busy.context.discover();
 assert.equal(busy.context.discovering,false,'Failure releases the polling guard');assert.deepEqual(busy.notices,['isolated fixture error']);
 const empty=fixture([]);empty.context.initialRoute=true;empty.context.state=null;empty.context.run=null;await empty.context.discover();
 assert.equal(empty.context.initialRoute,true,'An empty watcher remains ready for its first deployment');
 empty.context.request=async url=>url.endsWith('/processes')?[]:[active];await empty.context.discover();
 assert.deepEqual(empty.chosen,[],'A newly discovered deployment appears in Current tasks without opening it');assert.equal(empty.context.initialRoute,false);assert.equal(empty.context.pageView,'history');
 const landing=fixture();Object.assign(landing.context,{initialRoute:true,pageView:'history',run:null,state:null});await landing.context.discover();await landing.context.discover();assert.deepEqual(landing.chosen,[],'The populated landing page stays put across discovery polls');assert.equal(landing.context.pageView,'history');
 const linked=fixture();Object.assign(linked.context,{initialRoute:true,pageView:'history',run:null,state:null});linked.context.location.href+='?deployment=new';await linked.context.discover();assert.deepEqual(linked.chosen,[{id:'new',navigate:false}],'An explicit deployment URL still opens its detail view');
 assert.match(source,/setInterval\(discover,liveOnly\?1000:5000\)/,'Live discovery polls each second without changing legacy viewers');
 assert.doesNotMatch(source,/api\/processes/,'Current tasks must not fetch or display raw PID diagnostics');
 console.log('Discovery policy passed: one-second polling, next-run following, manual pinning, concurrency safety, bounded requests, stable Current tasks landing and explicit deep links.');
})().catch(error=>{console.error(error);process.exitCode=1;});
