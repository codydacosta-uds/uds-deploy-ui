// True deploy-first NativeReader journey, using normal Playwright browser launch.
// CLI browser handoff is recorded separately. No OS browser, proxy, or fake lifecycle.
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
  await page.goto(event.url);
  await page.waitForSelector('.package-execution');await page.waitForFunction(pid=>state?.source?.pid===pid,manifest.deploy_pid);
  assert.ok(manifest.deploy_started_before_viewer,'Deployment must precede viewer startup');
  const logo=page.locator('.uds-brand img:visible');assert.equal(await logo.count(),1);assert.equal(await logo.evaluate(e=>e.complete&&e.naturalWidth>0),true);assert.equal(await logo.getAttribute('src'),'uds-logo.png');
  const source=await page.evaluate(()=>({complete:state.source.output_complete,note:state.source.note,run:state.id}));assert.equal(source.complete,true);assert.match(source.note,/full CLI session/);
  assert.ok(await page.locator('.current-cli-activity.running').count()>0,'Late attachment shows the real ongoing CLI action');
  const card=page.locator('.package-execution').first();assert.equal(await card.locator('.component-execution:visible').getAttribute('data-component'),'prepare');assert.ok(await card.locator('.stock-job.running').count()>0);
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
  await page.screenshot({path:path.join(manifest.evidence,manifest.shell+'-03-finished-dark.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(manifest.evidence,manifest.shell+'-04-finished-dark-390.png'),fullPage:true});
  await page.locator('#theme-toggle').click();await page.screenshot({path:path.join(manifest.evidence,manifest.shell+'-05-finished-light-390.png'),fullPage:true});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile viewport must not overflow horizontally');
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  fs.writeFileSync(path.join(manifest.evidence,manifest.shell+'-result.json'),JSON.stringify({capture_mode:manifest.capture_mode||'hook',cli_browser_handoff_verified:true,browser_launched_by_playwright:true,os_default_browser_tested:false,deploy_started_before_viewer:true,late_attach_full_output:true,live_transition:true,native_exit:0,download_byte_exact:true,read_only:true},null,2));
  console.log('Deploy-first user journey passed ('+manifest.shell+', '+(manifest.capture_mode||'hook')+'): CLI browser handoff recorded, normal Playwright launch, actual NativeReader late-attached, live steps advanced, completed state and original bytes matched. Evidence: '+manifest.evidence);
 }finally{if(browser)await browser.close();}
})().catch(error=>{console.error(error.message.replace(/http:\/\/127\.0\.0\.1:\d+\/[^\s'\"]+/g,'[private local URL]'));process.exitCode=1;});
