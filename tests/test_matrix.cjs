// Isolated matrix presentation; no logs create jobs, dependencies or success.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/uds_deploy/web/app.js'),'utf8');
function fn(name){const start=source.indexOf('function '+name+'(');assert.ok(start>=0);return source.slice(start,source.indexOf('\n}',start)+2);}
const context=vm.createContext({});vm.runInContext(fn('matrixAppearance')+'\n'+fn('matrixLayerStatus')+'\n'+source.slice(source.indexOf('function directDependencies('),source.indexOf('function displayedGroups(')),context);
for(const [status,appearance,label] of [['completed','succeeded','Done'],['failed','failed','Failed'],['deploying','running','Running'],['waiting','pending','Pending'],['not-started','unknown','Not started'],['unknown','unknown','Unconfirmed']]){
 assert.equal(context.matrixAppearance(status).state,appearance);assert.equal(context.matrixAppearance(status).label,label);
}
const status=values=>context.matrixLayerStatus(values.map(value=>({status:value})));
assert.equal(status(['completed','completed']),'completed');assert.equal(status(['completed','deploying']),'deploying');assert.equal(status(['waiting','waiting']),'waiting');assert.equal(status(['completed','failed']),'failed');assert.equal(status(['completed','unknown']),'unknown');assert.equal(status(['completed','not-started']),'unknown');assert.equal(status(['not-started','not-started']),'not-started');
const jobs=[{id:'prepare',dependencies:[]},{id:'a',dependencies:['prepare']},{id:'b',dependencies:['prepare']},{id:'final',dependencies:['prepare','a','b']}];
const edges=JSON.parse(JSON.stringify(context.directDependencies(jobs)));
assert.deepEqual(edges,[{from:'prepare',to:'a'},{from:'prepare',to:'b'},{from:'a',to:'final'},{from:'b',to:'final'}]);
assert.deepEqual(JSON.parse(JSON.stringify(context.directDependencies([{id:'a',dependencies:[]},{id:'b',dependencies:[]}]))),[],'Sharing a layer never invents an edge');
console.log('Matrix policy passed: explicit runner results, pending/failed/unconfirmed states, and declared dependency fan-out/join only.');
