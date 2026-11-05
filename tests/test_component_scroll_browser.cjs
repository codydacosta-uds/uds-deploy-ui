// Isolated presentation fixture: normalized mock CLI reports, never a deployment.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{execFileSync}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.join(__dirname,'..'),web=path.join(root,'src/uds_deploy/web');
const fixture=JSON.parse(execFileSync(process.env.PYTHON||'python3',['-c',`
import copy,json,sys
sys.path.insert(0,'tests')
from test_native_watcher import NativeTests
case=NativeTests();case.setUp()
try:
 original=case.package['components'][0]
 case.package['components']=[]
 for i in range(33):
  component=copy.deepcopy(original);component['name']='component-%02d'%i
  component['actions']={'onDeploy':{'before':[{'cmd':'fixture-action-%02d'%i}]}}
  case.package['components'].append(component)
 case.output.write_text('2026-11-05 11:00:00 INF starting deploy package=actual-alias\\n2026-11-05 11:00:01 INF deploying component name=component-28\\n2026-11-05 11:00:02 INF running command cmd=fixture-action-28\\n2026-11-05 11:00:03 INF deploying component name=component-02\\n2026-11-05 11:00:04 INF running command cmd=fixture-action-02\\n')
 case.refresh();print(json.dumps(case.reader.list()[0]))
finally:case.doCleanups()
`],{cwd:root,encoding:'utf8'}));
const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png','.woff2':'font/woff2'};
const group={...fixture,id:'matrix-scroll-fixture',bundle_name:'Grouped scroll fixture',reports:[],source:{kind:'runner-record'},matrix:{layers:[{id:'work',label:'Work'}],jobs:[{id:'child',label:'Captured child',layer:'work',packages:fixture.packages.map(pkg=>pkg.id),dependencies:[],status:'deploying',started_at:fixture.started_at,completed_at:null,exit_code:null,child_run_id:fixture.id}]}};
let inventory=[fixture];const evidence=fs.mkdtempSync(path.join(os.tmpdir(),'uds-component-scroll-'));
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage({viewport:{width:1600,height:650}}),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('http://component-scroll.test/**',route=>{
  const pathname=new URL(route.request().url()).pathname;
  if(pathname.endsWith('/events'))return route.fulfill({contentType:'text/event-stream',body:''});
  if(pathname.startsWith('/api/'))return route.fulfill({json:pathname==='/api/deployments'?inventory:pathname.endsWith('/logs')?[]:pathname.endsWith('/'+group.id)?group:fixture});
  const filename=pathname==='/'?'index.html':pathname.slice(1);return route.fulfill({contentType:mime[path.extname(filename)]||'text/plain',body:fs.readFileSync(path.join(web,filename))});
 });
 await page.goto('http://component-scroll.test/?deployment='+fixture.id);await page.waitForSelector('.component-progress-row');await page.evaluate(()=>document.fonts.ready);
 const row=name=>page.locator('[data-component-progress="'+name+'"]');
 const visible=page.locator('.component-execution:visible');
 await visible.locator('.stock-job').click();
 assert.equal(await page.evaluate(()=>componentChoices.get(state.id+'/'+state.packages[0].id)),'component-02','Selecting a step pins its component, not just the step');
 await page.getByRole('button',{name:'Close logs',exact:true}).click();
 for(const grouped of [false,true]){
  if(grouped){inventory=[group];await page.emulateMedia({reducedMotion:'reduce'});await page.goto('http://component-scroll.test/?deployment='+group.id);await page.locator('[data-matrix-job="child"]').click();await visible.waitFor();}
 for(const width of [1280,1600])for(const theme of ['light','dark']){
  await page.setViewportSize({width,height:650});
  if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#theme-toggle').click();
  await row('component-28').click();await page.waitForTimeout(100);
  if(!await visible.locator('.selected-step-details').evaluate(el=>el.open))await visible.locator('.selected-step-details > summary').click();
  await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));await page.waitForTimeout(100);
  const before=await page.evaluate(()=>({window:scrollY,list:document.querySelector('.component-progress-list').scrollTop,component:document.querySelector('.component-execution:not([hidden])').dataset.component,anchor:document.querySelector('.component-execution:not([hidden]) .selected-step-details > summary').getBoundingClientRect().top}));
  for(const percent of [20,40,60,80,95]){
   fixture.reports.at(-1).image_percent=percent;
   await page.evaluate(async()=>{await refreshState();render();});await page.waitForTimeout(80);
  }
  const after=await page.evaluate(()=>({window:scrollY,list:document.querySelector('.component-progress-list').scrollTop,component:document.querySelector('.component-execution:not([hidden])').dataset.component,anchor:document.querySelector('.component-execution:not([hidden]) .selected-step-details > summary').getBoundingClientRect().top}));
  console.log((grouped?'Grouped':'Ordinary')+' '+theme+' '+width+': inspected component/list/viewport retained through changing progress above');
  assert.equal(after.component,before.component,'Background progress must not replace the manually inspected component');
  assert.ok(Math.abs(after.list-before.list)<=1,'Keep the manually inspected component-list position');
  assert.ok(Math.abs(after.anchor-before.anchor)<=1,'Background progress must not jump the page back up');
  assert.ok(Math.abs(after.window-before.window)<=1,'Matrix refresh must not clamp the page scroll while rebuilding');
  await page.screenshot({path:path.join(evidence,(grouped?'grouped':'ordinary')+'-'+theme+'-'+width+'.png')});
 }
 }
 await page.getByRole('button',{name:'Follow current component',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.component-execution:not([hidden])').dataset.component==='component-02');
 const next=structuredClone(fixture.reports.at(-1));next.definition_owner.component='component-03';next.timestamp+=1;next.resource='fixture-action-03';fixture.reports.push(next);await page.evaluate(()=>refreshState());await page.waitForFunction(()=>document.querySelector('.component-execution:not([hidden])').dataset.component==='component-03');
 assert.deepEqual(errors,[]);console.log('Component scroll fixture passed. Evidence: '+evidence);
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
