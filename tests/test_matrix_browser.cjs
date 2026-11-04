// Action-only SDK fixture, driven by test_matrix_journey.py. No cluster deployment.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const manifest=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[],writes=[],external=[];
 page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(!['GET','HEAD'].includes(request.method()))writes.push(request.method());if(new URL(request.url()).origin!==new URL(manifest.url).origin)external.push(request.url());});
 await page.goto(manifest.url);
 const link=page.locator('.deployment-link').filter({hasText:'Concurrent SDK fixture'});await link.waitFor();await link.click();
 await page.locator('#packages #matrix-navigation #matrix-view').waitFor({state:'visible'});assert.equal(await page.locator('.package-execution').count(),0);
 assert.equal(await page.getByRole('heading',{name:'Package navigation',exact:true}).count(),1);assert.equal(await page.locator('#workspace > #matrix-view').count(),0);
 assert.equal(await page.locator('#group-toolbar').isVisible(),false,'Legacy grouping controls must not appear before inspecting a child');assert.equal(await page.locator('#graph-caption').isVisible(),false);
 await page.evaluate(()=>{document.getElementById('stage-grouping').click();document.getElementById('dependency-grouping').click();});assert.equal(await page.locator('#matrix-view').isVisible(),true,'Legacy handlers must not replace the matrix');
 const parentId=await page.evaluate(()=>state.id);assert.ok(parentId.startsWith('matrix-'));
 const parentTitle=await page.locator('#bundle').innerText();
 assert.equal(await page.locator('#overview-metrics [data-metric="packages"] strong').innerText(),'4');assert.equal(await page.locator('#connection').innerText(),'● Live','Parent polling must not leave a Loading deployment message');
 const job=name=>page.locator('[data-matrix-job="'+name+'"]');
 await job('prepare').waitFor();await page.waitForFunction(()=>!document.querySelector('[data-matrix-job="prepare"]').disabled);
 assert.equal(await page.locator('.matrix-layer').count(),3);assert.equal(await page.locator('.matrix-job').count(),4);
 assert.equal(await page.locator('.matrix-summary').count(),1,'Single jobs must not get invented stage headers or dropdown wrappers');assert.equal(await page.locator('.matrix-summary strong').innerText(),'2 jobs');
 assert.equal(await page.locator('[data-matrix-layer="0"]').evaluate(el=>el.tagName),'DIV');assert.equal(await page.locator('[data-matrix-layer="2"]').evaluate(el=>el.tagName),'DIV');
 assert.doesNotMatch(await page.locator('#matrix-view').innerText(),/Layer [0-9]|Parallel jobs|Bootstrap|Applications/,'Console category labels are not UI headings');
 assert.equal(await page.locator('[data-matrix-layer="1"]').getAttribute('open'),null,'Future parallel work starts collapsed');assert.equal(await page.locator('[data-matrix-layer="2"]').getAttribute('open'),null,'Future layers must not fill the screen');
 assert.equal(await job('verify').getAttribute('data-job-status'),'waiting');assert.match(await job('verify').textContent(),/Not started/);
 await job('prepare').click();await page.locator('.package-execution').first().waitFor({state:'visible'});
 assert.equal(await page.locator('#packages #matrix-navigation #matrix-view').isVisible(),true,'The matrix belongs inside the existing Package navigation panel');
 assert.equal(await page.locator('#matrix-view').isVisible(),true);assert.equal(new URL(page.url()).searchParams.get('deployment'),parentId);
 await page.waitForFunction(()=>document.querySelector('#packages').textContent.includes('Matrix fixture prepare'));
 assert.equal(await page.locator('#bundle').innerText(),parentTitle);assert.equal(await page.locator('#overview-metrics [data-metric="packages"] strong').innerText(),'4','Selected child must not replace parent totals with one-package totals');
 assert.equal(await page.locator('[data-selected-matrix-job="prepare"]').count(),1);
 await job('prepare').click();await page.waitForFunction(()=>!!state?.matrix);assert.equal(await page.locator('.package-execution').count(),0,'Clicking the selected job closes its details');assert.equal(await page.locator('#bundle').innerText(),parentTitle);
 await job('prepare').click();await page.waitForFunction(()=>state?.packages?.[0]?.id==='prepare');
 await page.getByRole('button',{name:'View all logs',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#logs').textContent.includes('MATRIX prepare stdout'));
 fs.writeFileSync(path.join(manifest.directory,'prepare.release'),'release');
 await page.waitForFunction(()=>['work-a','work-b'].every(name=>document.querySelector('[data-matrix-job="'+name+'"]').dataset.jobStatus==='deploying'&&!document.querySelector('[data-matrix-job="'+name+'"]').disabled),null,{timeout:15000});
 assert.equal(await job('verify').getAttribute('data-job-status'),'waiting','The join must wait for both concurrent children');
 assert.equal(await page.evaluate(()=>state.source.kind),'stock-process','Child inspection reuses the native view');
 const childId=await page.evaluate(()=>(state.matrix?state:matrixParent).matrix.jobs.find(job=>job.id==='work-a').child_run_id),slowChild='**/api/deployments/'+childId;
 let delayedRequests=0;await page.route(slowChild,async route=>{if(++delayedRequests<=2)await new Promise(resolve=>setTimeout(resolve,1000));await route.continue();});
 await job('work-a').click();assert.equal(await job('work-a').getAttribute('aria-pressed'),'true','Selection feedback must not wait for the child request');assert.equal(await page.locator('#matrix-child-loading').isVisible(),true);assert.equal(await page.locator('.package-execution').count(),0,'Do not show the previous child while loading');assert.equal(await page.locator('#job-inspector').isVisible(),false);
 await job('work-a').click();assert.equal(await page.evaluate(()=>!!state?.matrix),true,'Closing uses the already-loaded parent immediately');await page.waitForTimeout(1200);assert.equal(await page.evaluate(()=>!!state?.matrix),true,'A late response must not reopen closed details');
 await job('work-a').click();assert.equal(await page.locator('#matrix-child-loading').isVisible(),true);await page.waitForFunction(()=>state?.packages?.[0]?.id==='work-a');assert.equal(await page.locator('#matrix-child-loading').count(),0);
 await page.waitForFunction(()=>document.querySelector('#packages').textContent.includes('Matrix fixture work-a'));
 assert.equal(await page.locator('#bundle').innerText(),parentTitle);assert.equal(await page.locator('#overview-metrics [data-metric="packages"] strong').innerText(),'4');assert.equal(await page.locator('[data-matrix-layer="0"]').getAttribute('open'),null,'An inactive unpinned layer collapses after changing selection');
 assert.equal(await page.locator('#matrix-navigation').evaluate(el=>!!(el.compareDocumentPosition(document.querySelector('.matrix-child-context'))&Node.DOCUMENT_POSITION_FOLLOWING)),true,'Selected-job context stays below navigation');
 assert.equal(await page.locator('#matrix-navigation').evaluate(el=>!!(el.compareDocumentPosition(document.querySelector('.cli-activity-lanes'))&Node.DOCUMENT_POSITION_FOLLOWING)),true,'Child activity stays below navigation');
 await page.getByRole('button',{name:'View all logs',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#logs').textContent.includes('MATRIX work-a stdout'));
 assert.equal(await page.locator('#matrix-view .dependency-line').count(),4,'Draw only the declared fan-out and join');
 await page.locator('#matrix-navigation').getByRole('button',{name:'List',exact:true}).click();await page.locator('.matrix-surface.matrix-list').waitFor();assert.equal(await page.locator('.matrix-wires').isVisible(),false);
 await page.locator('#matrix-navigation').getByRole('button',{name:'Pipeline',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('.matrix-surface').classList.contains('matrix-list'));
 for(const theme of ['light','dark']){
  const toggle=page.locator('#theme-toggle');if((await toggle.getAttribute('aria-pressed')==='true')!==(theme==='dark'))await toggle.click();
  await job('work-a').hover();const hover=await job('work-a').evaluate(el=>getComputedStyle(el).backgroundColor.match(/\d+/g).slice(0,3).map(Number));assert.ok(theme==='light'?hover.every(channel=>channel>200):hover.every(channel=>channel<100),'Matrix hover honors '+theme+' mode instead of inheriting the legacy black background');
  for(const width of [1280,1600]){await page.setViewportSize({width,height:1100});await page.evaluate(()=>document.fonts.ready);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(manifest.evidence,manifest.mode+'-'+theme+'-'+width+'.png'),fullPage:true});}
 }
 const summary=page.locator('[data-matrix-layer="1"] > summary');await summary.click();assert.equal(await page.locator('[data-matrix-layer="1"]').getAttribute('open'),null);await page.evaluate(()=>refreshState());assert.equal(await page.locator('[data-matrix-layer="1"]').getAttribute('open'),null,'Polling must not undo a manual collapse');await summary.click();
 fs.writeFileSync(path.join(manifest.directory,'work-a.release'),'release');await page.waitForFunction(()=>document.querySelector('[data-matrix-job="work-a"]').dataset.jobStatus==='completed');
 assert.equal(await job('work-b').getAttribute('data-job-status'),'deploying');assert.equal(await job('verify').getAttribute('data-job-status'),'waiting');
 fs.writeFileSync(path.join(manifest.directory,'work-b.release'),'release');
 if(manifest.mode==='success'){
  await page.waitForFunction(()=>document.querySelector('[data-matrix-job="verify"]').dataset.jobStatus==='deploying'&&!document.querySelector('[data-matrix-job="verify"]').disabled,null,{timeout:15000});
  await job('verify').click();await page.waitForFunction(()=>state?.packages?.[0]?.id==='verify');fs.writeFileSync(path.join(manifest.directory,'verify.release'),'release');
 }else await page.waitForFunction(()=>document.querySelector('[data-matrix-job="work-b"]').dataset.jobStatus==='failed');
 await page.waitForFunction(expected=>(state?.matrix?state:matrixParent)?.status===expected,manifest.mode==='success'?'completed':'failed',{timeout:15000});
 if(manifest.mode==='failure'){assert.equal(await job('verify').getAttribute('data-job-status'),'not-started');assert.equal(fs.existsSync(path.join(manifest.directory,'verify.started')),false);}
 // The API keeps original child status/evidence; the parent only adds runner results.
 const finalGroup=await page.evaluate(()=>JSON.parse(JSON.stringify(state.matrix?state:matrixParent)));
 for(const child of finalGroup.matrix.jobs.filter(job=>job.child_run_id)){
  const detail=await page.request.get(new URL('api/deployments/'+child.child_run_id,manifest.url).href),snapshot=await detail.json();assert.equal(snapshot.source.output_complete,true);
  const logs=await page.request.get(new URL('api/deployments/'+child.child_run_id+'/logs?download=1',manifest.url).href);assert.ok((await logs.body()).includes(Buffer.from('MATRIX '+child.id+' stdout')));
 }
 await page.getByRole('button',{name:'Close child details',exact:true}).click();await page.waitForFunction(()=>!!state?.matrix);assert.equal(await page.locator('.package-execution').count(),0);assert.equal(await page.locator('#group-toolbar').isVisible(),false);assert.equal(await page.locator('#graph-caption').isVisible(),false);
 await page.getByRole('button',{name:'← Current tasks',exact:true}).click();await page.waitForSelector('#deployments-page:visible');await page.evaluate(()=>discover());
 assert.equal(await page.locator('[data-run="'+parentId+'"]').count(),1);
 for(const child of finalGroup.matrix.jobs.filter(job=>job.child_run_id))assert.equal(await page.locator('[data-run="'+child.child_run_id+'"]').count(),0,'Validated children belong to one parent row');
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(external,[]);
 fs.writeFileSync(path.join(manifest.directory,'browser.done'),JSON.stringify({parent:parentId,jobs:finalGroup.matrix.jobs.map(job=>({id:job.id,status:job.status,child:job.child_run_id}))}));
 console.log('Matrix SDK '+manifest.mode+' passed: real parallel children, declared joins, same-page components/logs, separate original streams, one parent task, light/dark 1280/1600.');
}finally{await browser.close();}})().catch(error=>{console.error(error.stack);process.exitCode=1;});
