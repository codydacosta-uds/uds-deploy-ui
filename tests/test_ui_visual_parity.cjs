// Real-capture visual parity: integrated viewer vs standalone, same selected capture.
// No lifecycle injection. Normal Playwright launch; no OS browser or Keychain test.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const source=process.env.UDS_WATCHER_SOURCE_URL,id=process.env.UDS_WATCHER_CAPTURE_ID;
if(!source||!id)throw Error('Explicit local integrated-viewer URL and real capture ID required');
const evidence=fs.mkdtempSync(path.join(os.tmpdir(),'uds-ui-parity-'));
(async()=>{let browser;const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'serve_real_capture.py')],{env:process.env,stdio:['ignore','pipe','pipe']});
 try{
  const standalone=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(Error('Temporary standalone server did not start')),15000);server.stdout.on('data',data=>{text+=data;if(text.includes('\n')){clearTimeout(timer);resolve(text.split('\n')[0]);}});server.once('exit',()=>{clearTimeout(timer);reject(Error('Temporary server exited'));});});
  browser=await chromium.launch({headless:true});const pages=[await browser.newPage({viewport:{width:1600,height:1100}}),await browser.newPage({viewport:{width:1600,height:1100}})],errors=[],writes=[];
  for(const page of pages){page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(!['GET','HEAD'].includes(request.method()))writes.push(request.method());});}
  const integrated=new URL(source);integrated.searchParams.set('deployment',id);const portable=new URL(standalone);portable.searchParams.set('deployment',id);
  await Promise.all([pages[0].goto(integrated.href),pages[1].goto(portable.href)]);
  for(const page of pages){await page.waitForSelector('.package-execution');await page.evaluate(()=>document.fonts.ready);await page.getByRole('button',{name:'Expand all packages',exact:true}).click();await page.mouse.move(0,0);}
  for(const theme of ['light','dark']){
   for(const page of pages){const toggle=page.getByRole('button',{name:'Dark mode',exact:true});if((await toggle.getAttribute('aria-pressed')==='true')!==(theme==='dark'))await toggle.click();await page.mouse.move(0,0);}
   for(const width of [390,1280,1600]){
    for(const page of pages){await page.setViewportSize({width,height:1100});await page.evaluate(async()=>{await document.fonts.ready;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});}
    const first=await pages[0].screenshot({path:path.join(evidence,theme+'-'+width+'-integrated.png'),fullPage:true,animations:'disabled'});
    const second=await pages[1].screenshot({path:path.join(evidence,theme+'-'+width+'-standalone.png'),fullPage:true,animations:'disabled'});
    assert.ok(first.equals(second),'Rendered UI drift at '+theme+' '+width+'px; inspect local comparison screenshots');
   }
  }
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);console.log('Pixel-identical real-capture UI verified between integrated and standalone viewers in light/dark at 390/1280/1600px. Evidence: '+evidence);
 }finally{if(browser)await browser.close();server.kill('SIGINT');await new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('exit',resolve);});}
})().catch(error=>{console.error(error.message.replace(/http:\/\/127\.0\.0\.1:\d+\/[^\s'\"]+/g,'[private local URL]'));process.exitCode=1;});
