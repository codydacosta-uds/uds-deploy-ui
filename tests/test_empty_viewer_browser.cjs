// Observe an actually empty NativeReader viewer; no injected deployment state.
// Uses normal Playwright launch only. No OS browser or Keychain testing.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),home=fs.mkdtempSync(path.join(os.tmpdir(),'uds-empty-home-')),evidence=fs.mkdtempSync(path.join(os.tmpdir(),'uds-empty-browser-'));
function contrast(a,b){const lum=s=>s.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);const x=lum(a),y=lum(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
(async()=>{let browser;const env={PATH:process.env.PATH,HOME:home,UDS_DEPLOY_RUNTIME_DIR:path.join(home,'runtime'),KUBECONFIG:''};
 const server=spawn(path.join(root,'uds-watch'),['--no-browser','--no-setup','--port','0'],{cwd:root,env,stdio:['ignore','pipe','pipe']});
 try{
  const url=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(Error('Viewer startup timed out')),15000);server.stdout.on('data',data=>{output+=data;const match=output.match(/UDS Watch: (http:\/\/[^\s]+)/);if(match){clearTimeout(timer);resolve(match[1]);}});server.once('exit',()=>{clearTimeout(timer);reject(Error('Viewer exited before readiness'));});});
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[],writes=[],external=[];
  page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(!['GET','HEAD'].includes(request.method()))writes.push(request.method());if(new URL(request.url()).origin!==new URL(url).origin)external.push('external');});
  await page.goto(url);await page.waitForSelector('#history-empty:visible');await page.evaluate(()=>document.fonts.ready);
  const actual=await page.request.get(new URL('api/deployments',url).href);assert.equal((await actual.json()).length,0,'This check requires a truly empty current viewer; no captures are hidden or fabricated');
  assert.equal(await page.locator('#history-empty h2').innerText(),'Ready to watch a deployment');assert.match(await page.locator('#history-empty p').innerText(),/capture setup enabled/);assert.doesNotMatch(await page.locator('#history-empty p').innerText(),/uds run|cannot be recovered/);
  assert.equal(await page.locator('#deployment-table-scroll').isVisible(),false,'No ghost table headings without deployments');
  const toggle=page.getByRole('button',{name:'Dark mode',exact:true});
  for(const theme of ['light','dark']){
   if((await toggle.getAttribute('aria-pressed')==='true')!==(theme==='dark'))await toggle.click();
   const logo=page.locator('.uds-brand img:visible');assert.equal(await logo.count(),1);assert.equal(await logo.evaluate(e=>e.complete&&e.naturalWidth>0),true);assert.equal(await logo.getAttribute('src'),theme==='dark'?'uds-logo-on-dark.png':'uds-logo.png');
   const colors=await page.evaluate(()=>{const background=getComputedStyle(document.querySelector('main')).backgroundColor;return ['#history-description','#history-empty h2','#history-empty p','.deployment-table th'].map(selector=>({selector,color:getComputedStyle(document.querySelector(selector)).color,background}));});for(const item of colors)assert.ok(contrast(item.background,item.color)>=4.5,'Readable '+theme+' empty state: '+item.selector);
   for(const width of [390,1280,1600]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(evidence,theme+'-'+width+'.png'),fullPage:true});}
  }
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(external,[]);console.log('Real empty viewer passed: approved light/dark UDS logos, no ghost table headings, readable contrast, generic deployment instructions, responsive widths. Evidence: '+evidence);
 }finally{
  if(browser)await browser.close();server.kill('SIGINT');await new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('exit',resolve);});fs.rmSync(home,{recursive:true,force:true});
 }
})().catch(error=>{console.error(error.message.replace(/http:\/\/127\.0\.0\.1:\d+\/[^\s'\"]+/g,'[private local URL]'));process.exitCode=1;});
