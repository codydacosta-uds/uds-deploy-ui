// Isolated renderer unit tests. Browser evidence uses real SDK output separately.
// Standalone adaptation of Apache-2.0 regression tests; see NOTICE.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/uds_deploy/web/app.js'),'utf8');
const start=source.indexOf('function appendLogText('),end=source.indexOf('\n}',start)+2;
const render=vm.runInNewContext('('+source.slice(start,end)+')',{
 document:{createTextNode:text=>({tag:'text',textContent:text})},
 node:(tag,text,cls)=>({tag,textContent:text,className:cls})
});
function check(text,query,expected,limit=3000){
 const children=[],parent={append(...nodes){children.push(...nodes);}},budget={remaining:limit,count:0,limited:false};
 render(parent,text,query,budget);
 assert.equal(children.map(n=>n.textContent).join(''),text,'Highlighting must preserve the original displayed text');
 assert.deepEqual(children.filter(n=>n.tag==='mark').map(n=>n.textContent),expected);
 assert.equal(budget.count,expected.length);return {children,budget};
}
check('Error: ERROR and error','error',['Error','ERROR','error']);
check('prefix [literal]+<tag>& suffix','[literal]+<tag>&',['[literal]+<tag>&']);
check('a.* aZZ a.*','a.*',['a.*','a.*']);
check('literal \\ path','\\',['\\']);
check('deployment started','not found',[]);
check('unchanged text','',[]);
check('🚀 Ready — ready','ready',['Ready','ready']);
const limited=check('x'.repeat(10000),'x',['x','x','x'],3);assert.equal(limited.budget.limited,true,'Bound DOM expansion for broad queries');
const exact=check('xx','x',['x','x'],2);assert.equal(exact.budget.limited,false,'Do not report a limit when every match was highlighted');
const navigationStart=source.indexOf('const NAVIGATION_MESSAGES='),navigationEnd=source.indexOf('async function locateActivityLog('),parse=vm.runInNewContext(source.slice(navigationStart,navigationEnd)+';navigationReport');
assert.equal(parse('application echo processing Helm chart chart=example'),null,'User text is not an SDK navigation anchor');
assert.equal(parse('2026-11-02 11:00:00 INF processing Helm chart name=raw-package-component-manifest').resource,'raw-package-component-manifest');
assert.equal(parse('2026-11-02 11:00:00 INF performing Helm upgrade chart="raw-package-component-manifest"').kind,'helm.upgrade');
assert.equal(parse(JSON.stringify({msg:'pushing image',name:'registry.example/image:1'})).resource,'registry.example/image:1');
assert.equal(parse('2026-11-02 11:00:00 INF running command cmd=Validate application').command,'Validate application');
console.log('Log renderer/navigation passed: literal safe highlights, exact SDK identities, preserved originals, bounded rendering.');
