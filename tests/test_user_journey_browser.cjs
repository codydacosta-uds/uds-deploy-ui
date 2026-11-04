// True deploy-first NativeReader journey, using normal Playwright browser launch.
// CLI browser handoff is recorded separately. No OS browser or deployment proxy.
// A separate, explicitly synthetic UI-discovery fixture follows the real journey.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const manifest=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(test,message,timeout=25000){const deadline=Date.now()+timeout;while(Date.now()<deadline){if(await test())return;await sleep(50);}throw Error(message);}
(async()=>{let browser;
 try{
  await until(()=>fs.existsSync(manifest.browser_event),'CLI did not hand the viewer URL to the configured browser');
  const event=JSON.parse(fs.readFileSync(manifest.browser_event,'utf8'));
  // Keep Playwright's default launch flags, including its mock Keychain flags.
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1600,height:1100}});
  const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',request=>{if(!['GET','HEAD'].includes(request.method()))writes.push(request.method());});
  await page.goto(event.url);await page.waitForSelector('#deployments-page:visible');
  await page.waitForFunction(pid=>discoveredRuns.some(r=>r.source?.pid===pid),manifest.deploy_pid);
  const chosenRun=await page.evaluate(pid=>discoveredRuns.find(r=>r.source?.pid===pid).id,manifest.deploy_pid);
  await page.screenshot({path:path.join(manifest.evidence,manifest.shell+'-00-current-tasks.png'),fullPage:true});
  await page.locator('[data-run="'+chosenRun+'"] .deployment-link').click();
  await page.waitForSelector('.package-execution');await page.waitForFunction(pid=>state?.source?.pid===pid,manifest.deploy_pid);
  assert.ok(manifest.deploy_started_before_viewer,'Deployment must precede viewer startup');
  const logo=page.locator('.uds-brand img:visible');assert.equal(await logo.count(),1);assert.equal(await logo.evaluate(e=>e.complete&&e.naturalWidth>0),true);assert.equal(await logo.getAttribute('src'),'uds-logo.png');
  const source=await page.evaluate(()=>({complete:state.source.output_complete,note:state.source.note,run:state.id}));assert.equal(source.complete,true);assert.match(source.note,/full CLI session/);
  assert.ok(await page.locator('.current-cli-activity.running').count()>0,'Late attachment shows the real ongoing CLI action');
  await page.locator('.current-cli-log-link').first().click();await page.waitForFunction(()=>!logLoading&&document.querySelector('#logs .log-anchor'));assert.match(await page.locator('#log-subtitle').innerText(),/Jumped to/,'Current actions jump by their exact captured line ID');await page.getByRole('button',{name:'Close logs',exact:true}).click();
  const card=page.locator('.package-execution').first();assert.equal(await card.locator('.component-execution:visible').getAttribute('data-component'),'prepare');assert.ok(await card.locator('.stock-job.running').count()>0);
  assert.ok(await card.locator('.component-progress-row[aria-pressed="true"] .component-progress-step.running').count()>0,'The selected active row keeps its running icon and step label');
  assert.equal(await card.locator('.component-counts').count(),0);
  const pending=card.locator('[data-component-progress="verify"]');assert.equal(await pending.locator('.component-overview-state').innerText(),'Pending');assert.equal(await pending.locator('.component-current-operation').innerText(),'—');assert.equal(await pending.locator('.activity-duration').innerText(),'—');assert.equal(await pending.locator('.step-status-icon.running').count(),0,'Pending is neutral, not spinning');
  const skipped=card.locator('[data-component-progress="optional-not-selected"]');
  assert.equal(await skipped.getAttribute('data-component-selection'),'not-selected');assert.match(await skipped.innerText(),/Not selected/);
  assert.equal(await skipped.locator('.component-progress-step').count(),0,'Unselected inventory is neutral, not pending work');
  assert.equal(await skipped.locator('.step-status-icon.not-selected').innerText(),'!');
  assert.equal(await skipped.locator('.step-status-icon.succeeded').count(),0,'Not selected is not successful execution');
  await page.screenshot({path:path.join(manifest.evidence,manifest.shell+'-01-late-attach-light.png'),fullPage:true});
  await card.locator('.component-execution:visible .stock-job').first().click();await page.waitForFunction(()=>!logLoading&&document.querySelector('#logs .log-anchor'));assert.match(await page.locator('#log-subtitle').innerText(),/Jumped to/);await page.getByRole('button',{name:'Close logs',exact:true}).click();
  fs.writeFileSync(manifest.release_prepare,'release');
  await page.waitForFunction(()=>state.reports.some(r=>r.definition_owner?.component==='verify'&&r.message==='running command'));
  await card.getByRole('button',{name:'Inspect '+manifest.package_alias+' / verify',exact:true}).click();assert.ok(await card.locator('.component-execution:visible .stock-job.running').count()>0);
  await page.getByRole('button',{name:'Dark mode',exact:true}).click();await page.screenshot({path:path.join(manifest.evidence,manifest.shell+'-02-live-transition-dark.png'),fullPage:true});
  fs.writeFileSync(manifest.release_verify,'release');await until(()=>fs.existsSync(manifest.task_exit),'Native deployment did not finish');
  assert.equal(JSON.parse(fs.readFileSync(manifest.task_exit,'utf8')).code,0,'Real native CLI must complete successfully');
  await page.waitForFunction(()=>!!state.completed_at);await page.waitForFunction(()=>document.querySelector('#run-status').textContent==='Done');
  assert.equal(await page.locator('.current-cli-activity').count(),0,'Ended CLI is no longer presented as running');
  assert.equal(await page.locator('[data-status-package]').first().getAttribute('data-package-status'),'succeeded','Positive final action and CLI advancement permit the documented green inferred result');
  await card.getByRole('button',{name:'Inspect '+manifest.package_alias+' / prepare',exact:true}).click();assert.equal(await card.locator('.component-execution:visible .stock-job').first().getAttribute('data-step-status'),'succeeded');
  const response=await page.request.get(new URL('api/deployments/'+encodeURIComponent(source.run)+'/logs?download=1',event.url).href);assert.equal(response.status(),200);
  assert.ok((await response.body()).equals(fs.readFileSync(manifest.terminal)),'End-to-end download must exactly match the original native CLI output');
  assert.ok((await response.body()).includes(Buffer.from('JOURNEY stdout')));assert.ok((await response.body()).includes(Buffer.from('JOURNEY stderr')));
  assert.ok(!(await response.body()).includes(Buffer.from('JOURNEY OPTIONAL MUST NOT RUN')),'The real SDK must not execute the unselected action');
  assert.equal(await page.evaluate(()=>state.reports.some(r=>r.kind==='component.start'&&r.definition_owner?.component==='optional-not-selected')),false);
  await skipped.locator('.step-status-icon.not-selected').click();
  assert.equal(await page.locator('#not-selected-dialog').isVisible(),true);assert.equal(await page.locator('#not-selected-meaning').innerText(),"Optional component not enabled for this deployment. Not a failure and doesn't block completion.");assert.equal(await page.locator('#not-selected-title .step-status-icon.not-selected').innerText(),'!');
  await page.getByRole('button',{name:'Close explanation',exact:true}).click();assert.match(await card.locator('.component-execution:visible').innerText(),/Not selected by the packaged bundle/);
  assert.equal(await card.locator('.component-execution:visible .step-status-icon.not-selected').count(),1);
  assert.equal(await card.locator('.component-execution:visible .stock-job').count(),0);assert.equal(await page.locator('#run-status').innerText(),'Done');
  await page.screenshot({path:path.join(manifest.evidence,manifest.shell+'-03-finished-dark.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(manifest.evidence,manifest.shell+'-04-finished-dark-390.png'),fullPage:true});
  await page.locator('#theme-toggle').click();await page.screenshot({path:path.join(manifest.evidence,manifest.shell+'-05-finished-light-390.png'),fullPage:true});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile viewport must not overflow horizontally');
  // Isolated UI fixtures, NOT another SDK invocation or real lifecycle evidence.
  // Route only this separate test page; the real viewer and its capture stay intact.
  const finished=await page.evaluate(()=>JSON.parse(JSON.stringify(state)));
  finished.bundle_name='Discovery fixture';
  const next={...finished,id:'fixture-next-run',created_at:finished.created_at+1,status:'deploying',completed_at:null,error:null,reports:[],checks:[]};
  const third={...next,id:'fixture-third-run',created_at:next.created_at+1};let inventory=[finished];
  const discovery=await browser.newPage({viewport:{width:1600,height:1100}});
  discovery.on('pageerror',e=>errors.push(e.message));discovery.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))writes.push(r.method());});
  await discovery.route('**/api/**',route=>{
   const target=new URL(route.request().url()),pathname=target.pathname;
   // Keep a real, quiet SSE connection to this test's held SDK capture.
   if(pathname.endsWith('/events')){target.pathname=pathname.replace(/\/[^/]+\/events$/,'/'+finished.id+'/events');return route.continue({url:target.href});}
   const data=pathname.endsWith('/processes')?[]:pathname.endsWith('/deployments')?inventory:pathname.endsWith('/logs')?[]:inventory.find(r=>pathname.endsWith('/'+r.id));
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data??{})});
  });
  const fixtureURL=new URL(event.url);fixtureURL.searchParams.set('deployment',finished.id);
  await discovery.goto(fixtureURL.href);await discovery.waitForFunction(id=>state?.id===id,finished.id);
  const published=Date.now();inventory=[next,finished];
  await discovery.waitForFunction(id=>state?.id===id,next.id,{timeout:4000});
  assert.ok(Date.now()-published<4000,'The next deployment is selected without a five-second wait or reload');
  assert.equal(new URL(discovery.url()).searchParams.get('deployment'),next.id);
  await discovery.evaluate(id=>chooseRun(id),finished.id);await discovery.evaluate(()=>discover());await sleep(1200);
  assert.equal(await discovery.evaluate(()=>state.id),finished.id,'Manual historical selection remains pinned');
  await discovery.evaluate(id=>chooseRun(id),next.id);inventory=[third,next,finished];await discovery.evaluate(()=>discover());await sleep(1200);
  assert.equal(await discovery.evaluate(()=>state.id),next.id,'Concurrent active runs do not steal focus');
  next.status='unknown';next.completed_at=finished.completed_at;
  await discovery.waitForFunction(id=>state?.id===id,third.id,{timeout:4000});
  await discovery.waitForFunction(()=>document.querySelector('#connection').classList.contains('live'));
  for(const theme of ['light','dark']){
   if(await discovery.locator('html').getAttribute('data-theme')!==theme)await discovery.locator('#theme-toggle').click();
   for(const width of [390,1600]){
    await discovery.setViewportSize({width,height:1100});await discovery.evaluate(()=>document.fonts.ready);
    assert.equal(await discovery.evaluate(()=>state.id),third.id);
    await discovery.screenshot({path:path.join(manifest.evidence,manifest.shell+'-discovery-fixture-'+theme+'-'+width+'.png'),fullPage:true});
    assert.ok(await discovery.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   }
  }
  await discovery.getByRole('button',{name:'← Current tasks',exact:true}).click();await discovery.waitForSelector('#deployments-page:visible');
  const row=await discovery.locator('[data-run="'+third.id+'"] .deployment-link').elementHandle();await row.focus();third.cursor=(third.cursor||0)+1;
  await discovery.evaluate(()=>discover());assert.equal(await row.evaluate(e=>e.isConnected&&document.activeElement===e),true,'Unrelated log-cursor updates keep overview rows/focus intact');
  inventory=[{...third,id:'fixture-fourth-run',created_at:third.created_at+1},...inventory];await discovery.evaluate(()=>discover());await sleep(1200);
  assert.equal(await discovery.locator('#deployments-page').isVisible(),true,'New deployments update the overview without navigating away');assert.equal(new URL(discovery.url()).searchParams.has('deployment'),false);
  await discovery.close();assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  console.log('Isolated discovery UI fixtures passed: next-run auto-follow, manual pinning, concurrency safety, light/dark desktop/mobile.');
  fs.writeFileSync(path.join(manifest.evidence,manifest.shell+'-result.json'),JSON.stringify({capture_mode:manifest.capture_mode||'hook',cli_browser_handoff_verified:true,browser_launched_by_playwright:true,os_default_browser_tested:false,deploy_started_before_viewer:true,late_attach_full_output:true,live_transition:true,native_exit:0,download_byte_exact:true,read_only:true,synthetic_discovery_fixtures_verified:true},null,2));
  console.log('Deploy-first user journey passed ('+manifest.shell+', '+(manifest.capture_mode||'hook')+'): CLI browser handoff recorded, normal Playwright launch, actual NativeReader late-attached, live steps advanced, completed state and original bytes matched. Evidence: '+manifest.evidence);
 }finally{if(browser)await browser.close();}
})().catch(error=>{console.error(error.message.replace(/http:\/\/127\.0\.0\.1:\d+\/[^\s'\"]+/g,'[private local URL]'));process.exitCode=1;});
