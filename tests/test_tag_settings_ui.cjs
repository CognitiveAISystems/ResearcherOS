const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  constructor(){ this.dataset={};this.style={};this.children=[];this.textContent='';this.value=''; }
  set innerHTML(html){this.children=[...html.matchAll(/<button[^>]*data-(index|color)="([^"]+)"[^>]*>/g)].map(m=>{const e=new Element();e.dataset[m[1]]=m[2];return e;});}
  get childElementCount(){return this.children.length;}
  querySelectorAll(){return this.children;}
  querySelector(selector){this.parts ||= {}; return this.parts[selector] ||= new Element();}
  setAttribute(k,v){this[k]=v;}
  showModal(){this.open=true;}
  focus(){}
  close(){this.open=false;}
}
const settle=async()=>{for(let i=0;i<15;i++)await new Promise(r=>setImmediate(r));};
async function setup(){
 const elements=new Map(); const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const calls=[]; const deletions=[]; const project={id:'demo',card_tags:['alpha','beta','gamma'],boards:{b:{id:'b',cards:[{tags:['alpha','ALPHA']},{tags:['alpha','beta']}]}}};
 const ctx={document:{getElementById:get},state:{project},setTimeout,clearTimeout,CARD_TAG_NAME_RE:/^[a-zA-Z0-9_-]+$/,cardTagHue:()=>40,
 boardWriteProjectId:()=> 'demo',isHubMode:()=>false,saveKanbanDisabledTagFilters(){},syncLabProject(){},rerenderKanbanAfterFilters(){},reloadProjectView:async()=>project,
 KoiApi:{deleteCardTag:async(pid,tag)=>{deletions.push(tag);},getProject:async()=>project,updateCardTag:async(pid,old,body)=>{calls.push({old,...body});if(body.name==='taken')throw Error('Already exists');}}};
 vm.createContext(ctx);const source=fs.readFileSync(require('node:path').join(__dirname,'../web/app.js'),'utf8');
 vm.runInContext(source.slice(source.indexOf('const TAG_COLOR_PALETTE =')),ctx);
 await ctx.openTagSettings(project.boards.b);return {get,calls,deletions};
}
test('all tags can change colors without replacing controls',async()=>{
 const {get,calls}=await setup();const list=get('tag-settings-list');const palette=get('tag-settings-palette');const original=list.children.slice();const swatches=palette.children.slice();
 for(let i=0;i<3;i++){list.children[i].onclick();palette.children[i].onclick();await settle();}
 assert.deepEqual(calls.map(c=>c.old),['alpha','beta','gamma']);
 assert.ok(original.every((e,i)=>list.children[i]===e));assert.ok(swatches.every((e,i)=>palette.children[i]===e));
});
test('failed rename does not prevent saving another tag or correcting the first',async()=>{
 const {get,calls}=await setup();const input=get('tag-settings-name');input.value='taken';input.oninput();input.onblur();await settle();
 get('tag-settings-list').children[1].onclick();get('tag-settings-palette').children[1].onclick();await settle();
 assert.equal(calls.at(-1).old,'beta');
 get('tag-settings-list').children[0].onclick();input.value='fixed';input.oninput();input.onblur();await settle();
 assert.equal(calls.at(-1).old,'alpha');assert.equal(calls.at(-1).name,'fixed');
});

test('counts cards once and can delete all tags without deleting cards',async()=>{
 const {get,deletions}=await setup();
 assert.equal(get('tag-settings-list').children[0].querySelector('.tag-settings-count').textContent,2);
 assert.equal(get('tag-settings-list').children[2].querySelector('.tag-settings-count').textContent,0);
 for(let i=0;i<3;i++){const pending=get('tag-settings-delete').onclick();get('tag-delete-accept').onclick();await pending;await settle();}
 assert.deepEqual(deletions,['alpha','beta','gamma']);
 assert.equal(get('tag-settings-list').children.length,0);
 assert.equal(get('tag-settings-name').disabled,true);
 assert.equal(get('tag-settings-delete').disabled,true);
 assert.ok(get('tag-settings-palette').children.every(b=>b.disabled));
});
test('deletion waits for pending rename and uses saved name',async()=>{
 const {get,deletions}=await setup(); const input=get('tag-settings-name');
 input.value='renamed';input.oninput();input.onblur();
 const pending=get('tag-settings-delete').onclick();get('tag-delete-accept').onclick();await pending;await settle();
 assert.deepEqual(deletions,['renamed']);
 assert.equal(get('tag-settings-list').children.length,2);
});

test('cancel and Escape keep tag settings open without deleting',async()=>{
 const {get,deletions}=await setup();
 let pending=get('tag-settings-delete').onclick();
 assert.equal(get('tag-delete-confirm').open,true);
 assert.equal(deletions.length,0);
 get('tag-delete-cancel').onclick();await pending;
 assert.equal(get('tag-settings-dialog').open,true);
 assert.equal(get('tag-settings-list').children.length,3);
 pending=get('tag-settings-delete').onclick();
 get('tag-delete-confirm').oncancel({preventDefault(){}});await pending;
 assert.equal(deletions.length,0);
 assert.equal(get('tag-settings-dialog').open,true);
});
