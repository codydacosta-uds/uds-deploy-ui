// Read-only Playwright checks on REAL captures. No simulated lifecycle events.
// UDS_WATCHER_SOURCE_URL and UDS_WATCHER_CAPTURE_ID are explicit private local inputs.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const source=process.env.UDS_WATCHER_SOURCE_URL,id=process.env.UDS_WATCHER_CAPTURE_ID,expectDone=process.env.UDS_WATCHER_EXPECT_DONE==='1';
if(!source||!id)throw Error('Explicit real local capture source and ID required');
const widths=(process.env.UDS_WATCHER_TEST_WIDTHS||'390,1280,1600').split(',').map(Number),expectTiming=process.env.UDS_WATCHER_EXPECT_TIMING==='1';
const evidence=fs.mkdtempSync(path.join(os.tmpdir(),'uds-standalone-browser-'));
function selectionOutline(e){const style=getComputedStyle(e),hex=style.getPropertyValue('--theme-border').trim()||'#8b96a4';return {shadow:style.boxShadow,color:'rgb('+hex.slice(1).match(/../g).map(value=>parseInt(value,16)).join(', ')+')'};}
function contrast(a,b){const lum=s=>s.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);const x=lum(a),y=lum(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'serve_real_capture.py')],{env:process.env,stdio:['ignore','pipe','pipe']});let browser;
 try{
  const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(Error('Temporary server startup timed out')),20000);server.stdout.on('data',data=>{text+=data;if(text.includes('\n')){clearTimeout(timer);resolve(text.split('\n')[0]);}});server.on('exit',()=>{clearTimeout(timer);reject(Error('Temporary server exited'));});});
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[],writes=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',request=>{if(!['GET','HEAD'].includes(request.method()))writes.push(request.method());if(new URL(request.url()).origin!==new URL(url).origin)external.push('external request');});
  await page.goto(url);await page.waitForSelector('#deployment-rows .deployment-link');await page.waitForTimeout(1200);
  assert.equal(await page.locator('#deployments-page').isVisible(),true,'Current tasks remains the landing page');assert.equal(await page.locator('#workspace').isVisible(),false);assert.equal(new URL(page.url()).searchParams.has('deployment'),false);
  const overviewRow=page.locator('[data-run="'+id+'"]');if(expectDone)assert.match(await overviewRow.locator('.history-status').innerText(),/Done/,'Overview uses the same approved completion evidence as details');
  assert.ok(await overviewRow.locator('td').evaluateAll(cells=>cells.every(cell=>getComputedStyle(cell).verticalAlign==='baseline')),'Row text aligns to the deployment name first-line baseline');
  assert.equal(await page.locator('.task-target:visible').count(),0);assert.doesNotMatch(await overviewRow.innerText(),/#native-|Local CLI process|See pipeline/);assert.match(await overviewRow.locator('.package-total').innerText(),/\d+ packages?/);
  for(const theme of ['dark','light']){if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#theme-toggle').click();await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(evidence,theme+'-current-tasks-desktop.png'),fullPage:true});}
  assert.equal(await overviewRow.locator('.history-status').getAttribute('href'),await overviewRow.locator('.deployment-link').getAttribute('href'),'Status and name link to the same deployment');
  await overviewRow.locator('.history-status').focus();await page.keyboard.press('Enter');await page.waitForSelector('#workspace:visible');
  await page.getByRole('button',{name:'← Current tasks',exact:true}).click();await page.waitForTimeout(1200);assert.equal(await page.locator('#deployments-page').isVisible(),true,'Returning to Current tasks stays there across polls');assert.equal(new URL(page.url()).searchParams.has('deployment'),false);
  await page.goBack();await page.waitForSelector('#workspace:visible');await page.waitForSelector('.package-execution');await page.evaluate(()=>document.fonts.ready);
  assert.equal(await page.locator('.uds-brand img:visible').count(),1,'Use the approved UDS branding');assert.equal(await page.locator('.watch-brand').count(),0);
  assert.equal(await page.locator('.uds-brand-title').innerText(),'Deploy');assert.equal(await page.title(),'UDS Deploy Portal');assert.equal(await page.locator('link[rel="icon"]').getAttribute('href'),'doug.png');
  assert.equal(await page.locator('#artifact-kind').innerText(),'Bundle');assert.equal(await page.locator('#artifact-kind').getAttribute('data-kind'),'bundle');
  assert.equal(await page.locator('.session-details').count(),0,'Redundant session metadata is not rendered');
  assert.equal(await page.locator('.timing-note').count(),0);assert.ok(await page.locator('.activity-duration').evaluateAll(times=>times.length>0&&times.every(e=>!!e.title)),'Timing explanations remain on duration tooltips');
  const activityLink=page.locator('.current-cli-log-link').first();assert.equal(await activityLink.innerText(),'Jump to activity');
  const activityLine=await page.evaluate(()=>(state.reports||[]).reduce((a,b)=>!a||b.timestamp>a.timestamp?b:a,null).log_id);
  await activityLink.click();await page.waitForFunction(()=>!logLoading&&document.querySelector('#logs .log-anchor'));assert.equal(Number(await page.locator('#logs .log-anchor').getAttribute('data-log-id')),activityLine);await page.getByRole('button',{name:'Close logs',exact:true}).click();
  const allLogs=page.locator('.session-output-button');assert.equal(await allLogs.innerText(),'View all logs');await allLogs.click();await page.waitForFunction(()=>!logLoading);assert.equal(await page.locator('#logs .log-anchor').count(),0,'General logs clear the activity jump');await page.getByRole('button',{name:'Close logs',exact:true}).click();
  const capture=await page.evaluate(()=>({nativeStatus:state.status,packages:state.packages.map(p=>({id:p.id,components:p.attempts.at(-1)?.execution?.components.map(c=>c.id)||[],omitted:(p.attempts.at(-1)?.execution?.components||[]).filter(c=>c.selection==='not-selected').map(c=>c.id),pushed:[...new Set(state.reports.filter(r=>r.kind==='images.push'&&r.resource&&r.definition_owner?.package===p.id).map(r=>r.definition_owner.component))]}))}));
  if(expectDone){await page.waitForFunction(()=>document.querySelector('#run-status').textContent==='Done');assert.equal(await page.locator('[data-status-package][data-package-status="succeeded"]').count(),capture.packages.length);assert.equal(await page.locator('[data-metric="unknown"] strong').innerText(),'0');}
  await page.getByRole('button',{name:'Expand all packages',exact:true}).click();const cards=page.locator('.package-execution');assert.equal(await cards.count(),capture.packages.length);
  for(let i=0;i<capture.packages.length;i++){
   const card=cards.nth(i),pkg=capture.packages[i];assert.equal(await card.locator(':scope>summary>.hierarchy-pill').innerText(),'Package');
   if(pkg.components.length===1){assert.equal(await card.locator('.component-progress-board').isVisible(),false);assert.equal(await card.locator('.component-identity .component-name').innerText(),pkg.components[0]);}
   else if(pkg.components.length){
    const rows=card.locator('.component-progress-row');assert.equal(await rows.count(),pkg.components.length);
    for(let j=0;j<pkg.components.length;j++){
     const before=await rows.nth(j).locator('.component-progress-step').allTextContents();
     assert.ok(before.length<=1,'The overview is compact; individual operations belong in the detail view');
     assert.equal(await rows.nth(j).locator('.component-step-connector').count(),0);
     if(expectTiming&&!pkg.omitted.includes(pkg.components[j]))assert.notEqual(await rows.nth(j).locator('.activity-duration').innerText(),'—','SDK-clock component timing survives late replay');
     await rows.nth(j).click();assert.equal(await rows.nth(j).locator('.component-counts').count(),0,'Selection must not replace icons with summary counts');
     if(expectDone)assert.deepEqual(await rows.nth(j).locator('.component-progress-step').allTextContents(),before,'Selection keeps the compact overview; individual steps appear below');
     const detail=card.locator('.component-execution:visible');assert.equal(await detail.locator(':scope > summary .component-name').innerText(),pkg.components[j]);
     for(const gap of await detail.locator('.execution-rail').evaluateAll(rails=>rails.map(e=>parseFloat(getComputedStyle(e).paddingBottom))))assert.ok(gap>=10,'Cards keep breathing room above their horizontal scrollbar');
     if(pkg.omitted.includes(pkg.components[j])){assert.equal(await page.locator('#not-selected-dialog').isVisible(),true);assert.equal(await page.locator('#not-selected-meaning').innerText(),"Optional component not enabled for this deployment. Not a failure and doesn't block completion.");assert.equal(await page.locator('#not-selected-title .step-status-icon.not-selected').innerText(),'!');await page.getByRole('button',{name:'Close explanation',exact:true}).click();assert.equal(await rows.nth(j).locator('.step-status-icon.not-selected').innerText(),'!');assert.match(await rows.nth(j).innerText(),/Not selected/);assert.equal(await detail.locator('.step-status-icon.not-selected').count(),1);assert.equal(await detail.locator('.stock-job').count(),0);}
     if(expectDone&&pkg.pushed.includes(pkg.components[j])){assert.equal(await detail.locator('.stock-job[data-report="images.push"]').getAttribute('data-step-status'),'succeeded');assert.equal(await detail.locator('.image-transfer:not(.succeeded)').count(),0,'Every image in the reported completed batch has its checkmark');}
    }
   }
  }
  await page.locator('[data-status-package]').last().click();
  const first=cards.first(),toggle=page.getByRole('button',{name:'Dark mode',exact:true});
  for(const theme of ['light','dark']){
   if((await toggle.getAttribute('aria-pressed')==='true')!==(theme==='dark'))await toggle.click();
   const logo=page.locator('.uds-brand img:visible');assert.equal(await logo.count(),1);assert.equal(await logo.evaluate(e=>e.complete&&e.naturalWidth>0),true);assert.equal(await logo.getAttribute('src'),theme==='dark'?'uds-logo-on-dark.png':'uds-logo.png');
   const brand=await page.locator('.uds-brand').evaluate(e=>{const img=e.querySelector('img:not([hidden])'),title=e.querySelector('.uds-brand-title'),style=getComputedStyle(title);return {width:img.getAttribute('width'),height:img.getAttribute('height'),divider:style.borderLeftWidth,color:style.color,bg:getComputedStyle(e.closest('header')).backgroundColor};});assert.equal(brand.width,'96');assert.equal(brand.height,'60');assert.equal(brand.divider,'1px');assert.ok(contrast(brand.color,brand.bg)>=4.5);
   const spacing=await page.locator('.run-meta').evaluate(e=>{const s=getComputedStyle(e);return {top:parseFloat(s.paddingTop),bottom:parseFloat(s.paddingBottom),gap:parseFloat(s.columnGap)};});assert.ok(spacing.top>=8&&spacing.bottom>=10&&spacing.gap>=24,'Timestamp metadata has breathing room');
   const bundleStyle=await page.locator('#artifact-kind').evaluate(e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,radius:getComputedStyle(e).borderRadius}));assert.equal(bundleStyle.radius,'999px');assert.ok(contrast(bundleStyle.bg,bundleStyle.color)>=4.5);
   const selection=await page.locator('.deployment-package.is-selected').evaluate(selectionOutline);assert.ok(selection.shadow.includes(selection.color),'Package selection uses the current theme border');
   if(expectDone){const green=await page.locator('.deployment-package.succeeded .step-status-icon').first().evaluate(e=>getComputedStyle(e).backgroundColor);for(const border of await cards.evaluateAll(items=>items.map(e=>getComputedStyle(e).borderLeftColor)))assert.equal(border,green,'Completed package borders stay green in both themes');}
   const resources=first.locator('.component-execution:visible .component-resources');if(await resources.count()&&!await resources.evaluate(e=>e.open))await resources.locator(':scope>summary').click();
   for(const width of widths){
    await page.setViewportSize({width,height:1100});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'No horizontal page overflow');
    const board=cards.filter({has:page.locator('.component-progress-board:not([hidden])')}).first();
    if(await board.count()){
     const rows=board.locator('.component-progress-row'),row=rows.nth(Math.min(3,await rows.count()-1));await row.click();await page.keyboard.press('Tab');await row.focus();
     const bounds=await row.evaluate(e=>{const r=e.getBoundingClientRect(),l=e.closest('.component-progress-list').getBoundingClientRect();return {left:r.left-l.left,right:l.right-r.right,offset:parseFloat(getComputedStyle(e).outlineOffset),visible:e.matches(':focus-visible')};});
     assert.ok(bounds.left>=3&&bounds.right>=3&&bounds.offset<=0&&bounds.visible,'Selection/focus ring stays inside the scroll container, clear of the package border');
     const outline=await row.evaluate(selectionOutline);assert.ok(outline.shadow.includes(outline.color),'Component selection uses the current theme border');
    }
    await page.screenshot({path:path.join(evidence,theme+'-'+width+'.png'),fullPage:true});
    const omitted=page.locator('[data-component-selection="not-selected"]').first();
    if(await omitted.count()){
     await omitted.locator('.step-status-icon.not-selected').click();const explanation=page.locator('#not-selected-dialog');assert.equal(await explanation.isVisible(),true);
     const textColors=await explanation.evaluate(e=>({bg:getComputedStyle(e).backgroundColor,fg:getComputedStyle(e.querySelector('#not-selected-meaning')).color}));assert.ok(contrast(textColors.bg,textColors.fg)>=4.5);
     assert.ok(await explanation.evaluate(e=>e.getBoundingClientRect().width<=innerWidth-39));
     await page.screenshot({path:path.join(evidence,theme+'-'+width+'-not-selected-explanation.png'),fullPage:true});
     await page.keyboard.press('Escape');assert.equal(await explanation.isVisible(),false);
     assert.equal(await page.evaluate(()=>document.activeElement?.dataset.componentSelection),'not-selected','Escape restores the component button focus');
     await omitted.focus();await page.keyboard.press('Enter');assert.equal(await explanation.isVisible(),true);await page.getByRole('button',{name:'Close explanation',exact:true}).click();
     await page.locator('.component-execution:visible .selection-explanation').click();assert.equal(await explanation.isVisible(),true);await page.keyboard.press('Escape');
     const icon=omitted.locator('.step-status-icon.not-selected'),colors=await icon.evaluate(e=>({bg:getComputedStyle(e).backgroundColor,fg:getComputedStyle(e).color}));assert.ok(contrast(colors.bg,colors.fg)>=4.5);
     assert.equal(await icon.innerText(),'!');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
     await page.screenshot({path:path.join(evidence,theme+'-'+width+'-not-selected.png'),fullPage:true});
    }
   }
   await page.setViewportSize({width:1600,height:1100});
   const config=first.getByRole('button',{name:'View Zarf package config',exact:true});await config.click();await page.waitForSelector('#definition-content .yaml-key');
   const definition=await page.evaluate(async()=>{const response=await fetch(api+'/'+run+'/packages/'+encodeURIComponent(state.packages[0].id)+'/definition');return response.json();});
   assert.equal(definition.values_hidden,false);assert.ok(!definition.yaml.includes('[value hidden]'));assert.ok((await page.locator('#definition-content').textContent())===definition.yaml,'Highlighting preserves the entire real config');
   assert.equal(await page.locator('#definition-content img, #definition-content script, #definition-content iframe').count(),0);
   for(const kind of ['key','string','number','literal']){const token=page.locator('#definition-content .yaml-'+kind).first();if(await token.count()){const colors=await token.evaluate(e=>({color:getComputedStyle(e).color,bg:getComputedStyle(e.closest('pre')).backgroundColor}));assert.ok(contrast(colors.bg,colors.color)>=4.5);}}
   await page.getByRole('button',{name:'Close YAML',exact:true}).click();
   const step=first.locator('.component-execution:visible .stock-job').first();if(await step.count()){await step.click();await page.waitForFunction(()=>!logLoading&&document.querySelector('#logs .log-anchor'));assert.match(await page.locator('#log-subtitle').innerText(),/Jumped to/);await page.getByRole('button',{name:'Close logs',exact:true}).click();}
  }
  const download=await page.request.get(url+'api/deployments/'+encodeURIComponent(id)+'/logs?download=1'),original=await page.request.get(new URL('api/deployments/'+encodeURIComponent(id)+'/logs?download=1',process.env.UDS_WATCHER_ORIGINAL_SOURCE_URL||source).href);assert.ok((await download.body()).equals(await original.body()),'Standalone download preserves all original capture bytes');
  assert.equal(await page.locator('button button').count(),0,'Explanation controls must not create nested buttons');
  assert.equal(await page.evaluate(()=>state.status),capture.nativeStatus,'Presentation must not rewrite native outcome');
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(external,[]);
  console.log('Standalone Playwright passed on real captures: hierarchy, every component, full YAML/highlighting, exact log anchors/download, both themes, '+widths.join('/')+' widths, no writes/external requests. Evidence: '+evidence);
 }finally{
  if(browser)await browser.close();server.kill('SIGINT');await new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('exit',resolve);});
 }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
