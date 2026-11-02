// Read-only Playwright checks on REAL captures. No simulated lifecycle events.
// UDS_WATCHER_SOURCE_URL and UDS_WATCHER_CAPTURE_ID are explicit private local inputs.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const source=process.env.UDS_WATCHER_SOURCE_URL,id=process.env.UDS_WATCHER_CAPTURE_ID;
if(!source||!id)throw Error('Explicit real local capture source and ID required');
const evidence=fs.mkdtempSync(path.join(os.tmpdir(),'uds-standalone-browser-'));
function contrast(a,b){const lum=s=>s.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);const x=lum(a),y=lum(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'serve_real_capture.py')],{env:process.env,stdio:['ignore','pipe','pipe']});let browser;
 try{
  const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(Error('Temporary server startup timed out')),20000);server.stdout.on('data',data=>{text+=data;if(text.includes('\n')){clearTimeout(timer);resolve(text.split('\n')[0]);}});server.on('exit',()=>{clearTimeout(timer);reject(Error('Temporary server exited'));});});
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[],writes=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',request=>{if(!['GET','HEAD'].includes(request.method()))writes.push(request.method());if(new URL(request.url()).origin!==new URL(url).origin)external.push('external request');});
  await page.goto(url+'?deployment='+encodeURIComponent(id));await page.waitForSelector('.package-execution');await page.evaluate(()=>document.fonts.ready);
  assert.equal(await page.locator('.watch-brand').innerText(),'UDS Watch');assert.equal(await page.locator('.uds-brand img').count(),0,'No unlicensed official logos');
  assert.equal(await page.locator('#artifact-kind').innerText(),'Bundle');assert.equal(await page.locator('#artifact-kind').getAttribute('data-kind'),'bundle');
  const capture=await page.evaluate(()=>({packages:state.packages.map(p=>({id:p.id,components:p.attempts.at(-1)?.execution?.components.map(c=>c.id)||[]}))}));
  await page.getByRole('button',{name:'Expand all packages',exact:true}).click();const cards=page.locator('.package-execution');assert.equal(await cards.count(),capture.packages.length);
  for(let i=0;i<capture.packages.length;i++){
   const card=cards.nth(i),pkg=capture.packages[i];assert.equal(await card.locator(':scope>summary>.hierarchy-pill').innerText(),'Package');
   if(pkg.components.length===1){assert.equal(await card.locator('.component-progress-board').isVisible(),false);assert.equal(await card.locator('.component-identity .component-name').innerText(),pkg.components[0]);}
   else if(pkg.components.length){const rows=card.locator('.component-progress-row');assert.equal(await rows.count(),pkg.components.length);for(let j=0;j<pkg.components.length;j++){await rows.nth(j).click();assert.equal(await card.locator('.component-execution:visible > summary .component-name').innerText(),pkg.components[j]);}}
  }
  const first=cards.first(),toggle=page.getByRole('button',{name:'Dark mode',exact:true});
  for(const theme of ['light','dark']){
   if((await toggle.getAttribute('aria-pressed')==='true')!==(theme==='dark'))await toggle.click();
   const bundleStyle=await page.locator('#artifact-kind').evaluate(e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,radius:getComputedStyle(e).borderRadius}));assert.equal(bundleStyle.radius,'999px');assert.ok(contrast(bundleStyle.bg,bundleStyle.color)>=4.5);
   const resources=first.locator('.component-execution:visible .component-resources');if(await resources.count()&&!await resources.evaluate(e=>e.open))await resources.locator(':scope>summary').click();
   for(const width of [390,1280,1600]){await page.setViewportSize({width,height:1100});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'No horizontal page overflow');await page.screenshot({path:path.join(evidence,theme+'-'+width+'.png'),fullPage:true});}
   await page.setViewportSize({width:1600,height:1100});
   const config=first.getByRole('button',{name:'View Zarf package config',exact:true});await config.click();await page.waitForSelector('#definition-content .yaml-key');
   const definition=await page.evaluate(async()=>{const response=await fetch(api+'/'+run+'/packages/'+encodeURIComponent(state.packages[0].id)+'/definition');return response.json();});
   assert.equal(definition.values_hidden,false);assert.ok(!definition.yaml.includes('[value hidden]'));assert.ok((await page.locator('#definition-content').textContent())===definition.yaml,'Highlighting preserves the entire real config');
   assert.equal(await page.locator('#definition-content img, #definition-content script, #definition-content iframe').count(),0);
   for(const kind of ['key','string','number','literal']){const token=page.locator('#definition-content .yaml-'+kind).first();if(await token.count()){const colors=await token.evaluate(e=>({color:getComputedStyle(e).color,bg:getComputedStyle(e.closest('pre')).backgroundColor}));assert.ok(contrast(colors.bg,colors.color)>=4.5);}}
   await page.getByRole('button',{name:'Close YAML',exact:true}).click();
   const step=first.locator('.component-execution:visible .stock-job').first();if(await step.count()){await step.click();await page.waitForFunction(()=>!logLoading&&document.querySelector('#logs .log-anchor'));assert.match(await page.locator('#log-subtitle').innerText(),/Jumped to/);await page.getByRole('button',{name:'Close logs',exact:true}).click();}
  }
  const download=await page.request.get(url+'api/deployments/'+encodeURIComponent(id)+'/logs?download=1'),original=await page.request.get(new URL('api/deployments/'+encodeURIComponent(id)+'/logs?download=1',source).href);assert.ok((await download.body()).equals(await original.body()),'Standalone download preserves all original capture bytes');
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(external,[]);
  console.log('Standalone Playwright passed on real captures: hierarchy, every component, full YAML/highlighting, exact log anchors/download, both themes, 390/1280/1600 widths, no writes/external requests. Evidence: '+evidence);
 }finally{
  if(browser)await browser.close();server.kill('SIGINT');await new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('exit',resolve);});
 }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
