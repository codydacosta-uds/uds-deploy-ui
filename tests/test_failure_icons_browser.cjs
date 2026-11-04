// Offline CSS fixture only: no deployment, capture, server, or lifecycle changes.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const web=path.join(__dirname,'../src/uds_deploy/web');
const css=['style.css','theme.css'].map(name=>fs.readFileSync(path.join(web,name),'utf8')).join('\n');
const evidence=fs.mkdtempSync(path.join(os.tmpdir(),'uds-failure-icons-'));
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:720}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.setContent('<style>'+css+'</style><body data-mode="live"><main><h1>Failure icon style fixture</h1><div id="fixture" style="display:flex;align-items:center;gap:32px;padding:24px">'+
   '<div><span data-icon="activity" class="step-status-icon failed" aria-hidden="true">×</span> Activity</div>'+
   '<div class="component-progress-step"><span data-icon="component" class="step-status-icon failed" aria-hidden="true">×</span> Component</div>'+
   '<div class="history-status failed"><span data-icon="table" class="status-icon failed" aria-hidden="true">×</span> Failed</div>'+
   '<div><span data-icon="cancelled" class="status-icon cancelled" aria-hidden="true">×</span> Cancelled</div>'+
   '</div></main></body>');
  for(const theme of ['light','dark']){
   await page.locator('html').evaluate((element,value)=>element.dataset.theme=value,theme);
   const icons=await page.locator('[data-icon]').evaluateAll(elements=>elements.map(element=>{
    const box=element.getBoundingClientRect(),style=getComputedStyle(element);
    const bars=['::before','::after'].map(pseudo=>{
     const bar=getComputedStyle(element,pseudo),matrix=new DOMMatrix(bar.transform);
     return {x:box.left+parseFloat(style.borderLeftWidth)+parseFloat(bar.left)+parseFloat(bar.width)/2+matrix.e,
      y:box.top+parseFloat(style.borderTopWidth)+parseFloat(bar.top)+parseFloat(bar.height)/2+matrix.f,
      thickness:parseFloat(bar.height),color:bar.backgroundColor,rotation:matrix.b};
    });
    return {name:element.dataset.icon,x:box.left+box.width/2,y:box.top+box.height/2,textFill:style.webkitTextFillColor,color:style.color,bars};
   }));
   assert.equal(icons.length,4);
   for(const icon of icons){
    assert.equal(icon.textFill,'rgba(0, 0, 0, 0)','Hide the old glyph without changing text metrics');
    for(const bar of icon.bars){
     assert.ok(Math.abs(bar.x-icon.x)<.1&&Math.abs(bar.y-icon.y)<.1,theme+' '+icon.name+' cross is centered');
     assert.equal(bar.thickness,2);assert.equal(bar.color,icon.color);
    }
    assert.ok(icon.bars[0].rotation>0&&icon.bars[1].rotation<0,'Both diagonal strokes form the X');
   }
   await page.locator('#fixture').screenshot({path:path.join(evidence,theme+'.png')});
  }
  assert.deepEqual(errors,[]);
  console.log('Failure icons passed: centered crosses at activity, component and table sizes in both themes. Evidence: '+evidence);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
