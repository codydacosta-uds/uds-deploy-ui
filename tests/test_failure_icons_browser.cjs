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
   '<span class="history-status unknown"><span class="status-icon unknown" aria-hidden="true">?</span>Unconfirmed</span>'+
   '<strong class="run-status failed">Errors reported</strong>'+
   '<span class="history-status completed"><span class="status-icon completed" aria-hidden="true">✓</span>Done</span>'+
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
   const palette=await page.evaluate(()=>{
    const colors=selector=>{const style=getComputedStyle(document.querySelector(selector));return {text:style.color,background:style.backgroundColor,border:style.borderColor};};
    return {failed:colors('.history-status.failed'),icon:colors('.status-icon.failed'),run:colors('.run-status.failed'),unknown:colors('.history-status.unknown'),question:colors('.status-icon.unknown'),step:colors('.step-status-icon.failed'),done:colors('.history-status.completed'),doneIcon:colors('.history-status.completed .status-icon')};
   });
   const luminance=color=>color.match(/[\d.]+/g).slice(0,3).map(Number).map(value=>{value/=255;return value<=.04045?value/12.92:((value+.055)/1.055)**2.4;}).reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
   const contrast=(a,b)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
   assert.ok(contrast(palette.failed.text,palette.failed.background)>=4.5,'Readable '+theme+' failure badge');
   assert.ok(contrast(palette.unknown.text,palette.unknown.background)>=4.5,'Readable '+theme+' unconfirmed badge');
   assert.ok(contrast(palette.done.text,palette.done.background)>=4.5,'Readable '+theme+' completed badge');
   if(theme==='light'){
    assert.equal(palette.failed.text,'rgb(198, 40, 40)');assert.equal(palette.failed.background,'rgb(255, 235, 238)');
    assert.equal(palette.icon.background,palette.failed.text);assert.equal(palette.step.background,palette.failed.text);assert.equal(palette.run.background,palette.failed.text,'Failure circles, headers and badges share the red token');
    assert.equal(palette.unknown.background,'rgb(237, 237, 237)');assert.equal(palette.unknown.text,'rgb(85, 85, 85)');assert.equal(palette.question.text,palette.unknown.text);assert.equal(palette.question.border,'rgb(115, 115, 115)','No amber or purple leaks into Unconfirmed');
   }else{
    assert.equal(palette.failed.background,'rgb(252, 121, 136)');assert.equal(palette.failed.text,'rgb(100, 26, 37)');assert.equal(palette.icon.background,palette.failed.text);assert.equal(palette.icon.text,palette.failed.background);
    assert.equal(palette.run.background,palette.failed.background);assert.equal(palette.run.text,palette.failed.text,'Errors reported uses the same failure palette');assert.equal(palette.step.text,palette.failed.text);
    assert.equal(palette.done.background,'rgb(53, 181, 151)');assert.equal(palette.done.text,'rgb(0, 61, 54)');assert.equal(palette.doneIcon.background,palette.done.text);assert.equal(palette.doneIcon.text,palette.done.background);
    assert.equal(palette.unknown.background,'rgb(65, 65, 65)');assert.equal(palette.question.text,palette.unknown.text,'Dark Unconfirmed is neutral gray, not amber');
   }
   await page.locator('#fixture').screenshot({path:path.join(evidence,theme+'.png')});
  }
  assert.deepEqual(errors,[]);
  console.log('Failure icons/palette passed: centered crosses, shared light-mode red, neutral Unconfirmed gray and readable badge contrast in both themes. Evidence: '+evidence);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
