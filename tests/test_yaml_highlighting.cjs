// Isolated lexical/DOM unit tests; browser verification uses real packaged configs.
// Standalone adaptation of Apache-2.0 regression tests; see NOTICE.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/uds_deploy/web/app.js'),'utf8');
const start=source.indexOf('function yamlTokens('),end=source.indexOf('async function showDefinition(',start);
const {yamlTokens,renderYaml}=vm.runInNewContext(source.slice(start,end)+';({yamlTokens,renderYaml})',{
 document:{createDocumentFragment:()=>({children:[],append(child){this.children.push(child);}}),createTextNode:text=>({tag:'text',textContent:text})},
 node:(tag,text,className)=>({tag,textContent:text,className})
});
function check(text,limit){
 const tokens=yamlTokens(text,limit);assert.equal(Array.from(tokens,t=>t.text).join(''),text,'Every character must survive highlighting');
 return Array.from(tokens).filter(t=>t.kind);
}
const sample='kind: "ZarfPackageConfig"\nmetadata:\n  name: "gitlab"\n  "annotation: key": "https://example.test/#fragment"\ncomponents:\n  - name: "deploy"\n    required: true\n    optional: false # preserved comment\n    retries: 3\n    wait: -1.25e+2\n    empty: null\n    images: []\n    values: {}\n    cmd: "echo \\"safe\\"; literal \\n <img src=x onerror=alert(1)> & 🚀"\n# comment\n';
const tokens=check(sample);
assert.deepEqual(tokens.filter(t=>t.kind==='key').map(t=>t.text),['kind','metadata','name','"annotation: key"','components','name','required','optional','retries','wait','empty','images','values','cmd']);
assert.deepEqual(tokens.filter(t=>t.kind==='literal').map(t=>t.text),['true','false','null']);
assert.deepEqual(tokens.filter(t=>t.kind==='number').map(t=>t.text),['3','-1.25e+2']);
assert.deepEqual(tokens.filter(t=>t.kind==='comment').map(t=>t.text),['# preserved comment','# comment']);
assert.ok(tokens.some(t=>t.kind==='string'&&t.text.includes('<img src=x onerror=alert(1)>')));
assert.equal(tokens.filter(t=>t.kind==='punctuation').length,2);
for(const text of ['', '\r\n', 'name: "a"\r\nvalue: 0\r\n', 'title: "false"\nversion: "19.5.1-uds.0"\n', "'quoted key': 'it''s a value'\n", 'partial: "unterminated\n  # comment\n', 'script: |\n  echo unknown syntax\n', 'url: https://example.test/#not-a-comment\n'])check(text);
assert.equal(check('flag: "true"\n')[1].kind,'string','Quoted booleans stay strings');
assert.equal(check('value: -42\n')[1].text,'-42','A negative number is not a list marker');
const huge='icon: "data:image/svg+xml;base64,'+'x'.repeat(500000)+'"\n';assert.equal(check(huge).length,2,'A long scalar stays a single token');
const limited=check(sample,3);assert.equal(limited.length,3,'Bound syntax spans without truncating any source');assert.equal(check(sample,0).length,0);
let rendered=[];const parent={replaceChildren(fragment){rendered=fragment.children;}};
renderYaml(parent,sample);assert.equal(rendered.map(n=>n.textContent).join(''),sample);assert.ok(rendered.every(n=>n.tag==='span'||n.tag==='text'),'Only inert text and span nodes are created');
renderYaml(parent,'kind: "replacement"\n');assert.equal(rendered.map(n=>n.textContent).join(''),'kind: "replacement"\n','Reopening replaces the previous document');
console.log('YAML highlighting passed: keys/scalars/comments, escaped quotes, CRLF/Unicode, inert DOM, exact source text, bounded spans and long values.');
