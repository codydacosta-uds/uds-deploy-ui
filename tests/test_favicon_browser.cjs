// Isolated artwork rendering, not an OS browser-tab integration test.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const browser=await chromium.launch({headless:true});try{
 const image='data:image/png;base64,'+fs.readFileSync(path.join(__dirname,'../src/uds_deploy/web/doug.png')).toString('base64');
 const page=await browser.newPage({viewport:{width:560,height:180},deviceScaleFactor:2});
 await page.setContent('<style>body{margin:0;font:16px system-ui}.preview{display:flex;align-items:center;gap:16px;padding:16px;background:#f5f6f7;color:#333}.dark{background:#343c3e;color:#eee}img{width:16px;height:16px}.large{width:32px;height:32px}</style>'+['light','dark'].map(theme=>'<div class="preview '+theme+'"><img src="'+image+'" alt="Doug">UDS Deploy Portal<img class="large" src="'+image+'" alt="Doug at 32 pixels"></div>').join(''));
 const bounds=await page.locator('img').first().evaluate(async image=>{
  await image.decode();const canvas=document.createElement('canvas');canvas.width=canvas.height=64;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,64,64);
  const data=ctx.getImageData(0,0,64,64).data;let left=64,right=-1,top=64,bottom=-1;
  for(let y=0;y<64;y++)for(let x=0;x<64;x++)if(data[(y*64+x)*4+3]>32){left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);}
  return {width:image.naturalWidth,height:image.naturalHeight,left,right,top,bottom,corner:data[3]};
 });
 assert.equal(bounds.width,64);assert.equal(bounds.height,64);assert.equal(bounds.corner,0,'Square padding must remain transparent');
 const ratio=(bounds.right-bounds.left+1)/(bounds.bottom-bounds.top+1);assert.ok(ratio>.55&&ratio<.66,'Doug keeps the portrait proportions rather than filling a square');assert.ok(Math.abs((bounds.left+bounds.right)/2-31.5)<=1,'Center the artwork');
 const evidence=fs.mkdtempSync(path.join(os.tmpdir(),'uds-favicon-review-'));await page.screenshot({path:path.join(evidence,'light-dark.png')});
 console.log('Favicon artwork passed: transparent square canvas, centered portrait proportions, 16/32-pixel previews. Evidence: '+evidence);
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
