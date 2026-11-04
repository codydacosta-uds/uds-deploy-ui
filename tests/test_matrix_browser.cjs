// Action-only SDK fixture, driven by test_matrix_journey.py. No cluster deployment.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const manifest=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[],writes=[],external=[];
 page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(!['GET','HEAD'].includes(request.method()))writes.push(request.method());if(new URL(request.url()).origin!==new URL(manifest.url).origin)external.push(request.url());});
 await page.goto(manifest.url);
 const link=page.locator('.deployment-link').filter({hasText:'Concurrent SDK fixture'});await link.waitFor();await link.click();
 await page.locator('#matrix-view').waitFor({state:'visible'});assert.equal(await page.locator('#deployment-detail').isVisible(),false);
 const parentId=await page.evaluate(()=>state.id);assert.ok(parentId.startsWith('matrix-'));
 const job=name=>page.locator('[data-matrix-job="'+name+'"]');
 await job('prepare').waitFor();await page.waitForFunction(()=>!document.querySelector('[data-matrix-job="prepare"]').disabled);
 assert.equal(await page.locator('.matrix-layer').count(),3);assert.equal(await page.locator('.matrix-job').count(),4);
 assert.equal(await job('verify').getAttribute('data-job-status'),'waiting');assert.match(await job('verify').innerText(),/Not started/);
 await job('prepare').click();await page.locator('#deployment-detail').waitFor({state:'visible'});
 assert.equal(await page.locator('#matrix-view').isVisible(),true);assert.equal(new URL(page.url()).searchParams.get('deployment'),parentId);
 await page.waitForFunction(()=>document.querySelector('#packages').textContent.includes('Matrix fixture prepare'));
 await page.getByRole('button',{name:'View all logs',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#logs').textContent.includes('MATRIX prepare stdout'));
 fs.writeFileSync(path.join(manifest.directory,'prepare.release'),'release');
 await page.waitForFunction(()=>['work-a','work-b'].every(name=>document.querySelector('[data-matrix-job="'+name+'"]').dataset.jobStatus==='deploying'&&!document.querySelector('[data-matrix-job="'+name+'"]').disabled),null,{timeout:15000});
 assert.equal(await job('verify').getAttribute('data-job-status'),'waiting','The join must wait for both concurrent children');
 assert.equal(await page.evaluate(()=>state.source.kind),'stock-process','Child inspection reuses the native view');
 await job('work-a').click();await page.waitForFunction(()=>state?.packages?.[0]?.id==='work-a');
 await page.waitForFunction(()=>document.querySelector('#packages').textContent.includes('Matrix fixture work-a'));await page.getByRole('button',{name:'View all logs',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#logs').textContent.includes('MATRIX work-a stdout'));
 assert.equal(await page.locator('#matrix-view .dependency-line').count(),4,'Draw only the declared fan-out and join');
 for(const theme of ['light','dark']){
  const toggle=page.locator('#theme-toggle');if((await toggle.getAttribute('aria-pressed')==='true')!==(theme==='dark'))await toggle.click();
  for(const width of [1280,1600]){await page.setViewportSize({width,height:1100});await page.evaluate(()=>document.fonts.ready);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(manifest.evidence,manifest.mode+'-'+theme+'-'+width+'.png'),fullPage:true});}
 }
 const summary=page.locator('[data-matrix-layer="1"] > summary');await summary.click();assert.equal(await page.locator('[data-matrix-layer="1"]').getAttribute('open'),null);await summary.click();
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
 await page.getByRole('button',{name:'Close child details',exact:true}).click();await page.waitForFunction(()=>!!state?.matrix);assert.equal(await page.locator('#deployment-detail').isVisible(),false);
 await page.getByRole('button',{name:'← Current tasks',exact:true}).click();await page.waitForSelector('#deployments-page:visible');await page.evaluate(()=>discover());
 assert.equal(await page.locator('[data-run="'+parentId+'"]').count(),1);
 for(const child of finalGroup.matrix.jobs.filter(job=>job.child_run_id))assert.equal(await page.locator('[data-run="'+child.child_run_id+'"]').count(),0,'Validated children belong to one parent row');
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(external,[]);
 fs.writeFileSync(path.join(manifest.directory,'browser.done'),JSON.stringify({parent:parentId,jobs:finalGroup.matrix.jobs.map(job=>({id:job.id,status:job.status,child:job.child_run_id}))}));
 console.log('Matrix SDK '+manifest.mode+' passed: real parallel children, declared joins, same-page components/logs, separate original streams, one parent task, light/dark 1280/1600.');
}finally{await browser.close();}})().catch(error=>{console.error(error.stack);process.exitCode=1;});
