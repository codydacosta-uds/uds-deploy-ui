// Real held capture only: final Helm health checks, no fabricated lifecycle data.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{let browser;try{
 const url=process.env.UDS_WATCHER_TEST_URL;assert.ok(url,'Set UDS_WATCHER_TEST_URL to an existing private viewer run');
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[],writes=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))writes.push(r.method());});
 await page.goto(url);await page.waitForFunction(()=>state?.completed_at&&state?.source?.output_complete===true);
 const evidence=fs.mkdtempSync(path.join(os.tmpdir(),'uds-terminal-health-'));
 const raw=await page.evaluate(()=>({status:state.status,reports:state.reports,checks:state.checks}));
 assert.ok(raw.reports.some(r=>r.kind==='health.wait'));assert.ok(!raw.reports.some(r=>r.kind==='deployment.error'||r.message==='action failed'));
 await page.waitForFunction(()=>document.querySelector('#run-status').textContent==='Done');
 await page.getByRole('button',{name:'Expand all packages',exact:true}).click();
 const api=await page.evaluate(()=>new URL('api/deployments/'+encodeURIComponent(state.id)+'/logs?download=1',location.href).href);
 const original=await(await page.request.get(api)).body();assert.ok(original.length>0);
 for(const theme of ['light','dark']){
  if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#theme-toggle').click();
  for(const width of [390,1280,1600]){
   await page.setViewportSize({width,height:1100});await page.evaluate(async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));});
   assert.equal(await page.locator('#run-status').innerText(),'Done');assert.match(await page.locator('#run-status').getAttribute('title'),/Assumed complete/);
   const pkg=page.locator('[data-status-package]').first();assert.equal(await pkg.getAttribute('data-package-status'),'succeeded');assert.equal(await pkg.getAttribute('data-result-inferred'),'true');
   assert.equal(await page.locator('.stock-job').first().getAttribute('data-step-status'),'succeeded');assert.equal(await page.locator('.stock-job.running').count(),0);
   const details=page.locator('summary').filter({hasText:'Step details'}).first();if(await details.count()&&!await details.evaluate(e=>e.parentElement.open))await details.click();
   assert.match(await page.locator('body').innerText(),/Assumed complete:.*health checks/);
   await page.screenshot({path:path.join(evidence,theme+'-'+width+'.png'),fullPage:true});
  }
 }
 const after=await page.evaluate(()=>({status:state.status,reports:state.reports,checks:state.checks}));assert.deepEqual(after,raw,'Inferred Done must not mutate observed reports or native status');
 assert.ok(original.equals(await(await page.request.get(api)).body()),'Completion styling must not change original log bytes');
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
 console.log('Real final-health capture verified: green Done header/package/step, explicit inference details, unchanged reports/log bytes, light/dark at 390/1280/1600px. Evidence: '+evidence);
}finally{if(browser)await browser.close();}})().catch(e=>{console.error(e.message.replace(/http:\/\/127\.0\.0\.1:\d+\/[^\s'\"]+/g,'[private viewer URL]'));process.exitCode=1;});
