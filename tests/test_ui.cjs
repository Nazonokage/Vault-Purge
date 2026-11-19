// Run with: node --test tests/test_ui.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

// A small DOM surface to exercise the actual app handlers without a browser dependency.
class Element {
  constructor(tag='div') {
    this.tagName=tag;this.children=[];this.dataset={};this.events={};this.value='';this.checked=false;
    const classes=new Set();this.classList={toggle:(c,on)=>on?classes.add(c):classes.delete(c),contains:c=>classes.has(c)};
  }
  set className(value){this.classes=value.split(' ');}
  get className(){return (this.classes||[]).join(' ');}
  setAttribute(key,value){this[key]=value;}
  append(...children){for(const child of children){if(child.tagName==='fragment')this.append(...child.children);else{child.parent=this;this.children.push(child);}}}
  prepend(child){child.parent=this;this.children.unshift(child);}
  replaceChildren(...children){this.children=[];this.append(...children);}
  add(child){this.append(child);}
  addEventListener(event,fn){(this.events[event]??=[]).push(fn);}
  querySelector(selector){return this.all().find(n=>selector==='input'?n.tagName==='input':n.classes?.includes(selector.slice(1)));}
  all(){return this.children.flatMap(c=>[c,...(c.all?.()||[])]);}
  closest(selector){return selector.split(',').includes(this.tagName)?this:this.parent?.closest(selector);}
  fire(event,extra={}){return Promise.all((this.events[event]||[]).map(fn=>fn({target:this,preventDefault(){},...extra})));}
  scrollIntoView(){this.scrolled=true;}
  focus(){this.focused=true;}
  showModal(){this.open=true;}
  close(){this.open=false;}
}

async function app() {
  const html=fs.readFileSync(path.join(__dirname,'../vault_purge/ui/static/index.html'),'utf8');
  const ids=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  const elements=()=>[...ids.values()].flatMap(n=>n.all());
  const doc={getElementById:id=>ids.get(id),createElement:tag=>new Element(tag),createDocumentFragment:()=>new Element('fragment'),
    querySelectorAll:selector=>selector.startsWith('.image-card')?elements().filter(n=>n.classes?.includes('image-card')||(n.classes?.includes('history-row')&&n.dataset.id)):[]};
  let respond=()=>({total:0,items:[]});const timers=[];
  const settings={show_recommendation:true,blur_threshold:100,dry_run:false,capabilities:{review_priority:true}};
  const ctx=vm.createContext({document:doc,localStorage:{getItem(){},setItem(){}},URLSearchParams,
    Option:function(text,value){const n=new Element('option');n.textContent=text;n.value=value;return n;},
    fetch:async url=>({ok:true,json:async()=>url==='/api/settings'?settings:respond(url)}),
    setTimeout:fn=>timers.push(fn),confirm:()=>true,Date});
  const source=fs.readFileSync(path.join(__dirname,'../vault_purge/ui/static/app.js'),'utf8');
  vm.runInContext(source+'\nglobalThis.app={state,load,setView,card,preselectedIds,scanStatusText,pollScan,scanActivity,showScanResults};',ctx);
  await new Promise(resolve=>setImmediate(resolve));
  ctx.app.state.scanId=1;
  return {...ctx.app,ids,timers,respond:fn=>respond=fn};
}
const image=id=>({id,path:`C:/photos/folder${id}/photo.jpg`,status:'active',media_type:'image',width:80,height:60,
  size:1000,orientation:'LANDSCAPE',blur_score:100,integrity:'checked'});
const group=(a,b,keep=a)=>({kind:'exact',members:[image(a),image(b)],recommendation:keep===null?null:{id:keep,reason:'test'}});
const selected=a=>[...a.state.selected.keys()];

test('automatic selection protects keepers, overlapping groups, and groups with no keeper',async()=>{
  const a=await app();
  a.respond(()=>({total:3,items:[group(1,2),group(2,3,2),group(4,5,null)]}));
  await a.load();assert.deepEqual(selected(a),[3]);
  assert.equal(a.ids.get('selected-count').textContent,'1 selected on this page');
  a.ids.get('preselect').checked=false;await a.ids.get('preselect').onchange();assert.deepEqual(selected(a),[]);
  a.ids.get('select-all').onclick();assert.deepEqual(selected(a),[1,2,3,4,5]);
  a.ids.get('clear').onclick();assert.deepEqual(selected(a),[]);
});

test('image selection stays on the current page, including returning to an earlier page',async()=>{
  const a=await app();
  a.respond(url=>({total:49,items:url.includes('offset=48')?[image(49)]:Array.from({length:48},(_,i)=>image(i+1))}));
  await a.setView('images');a.ids.get('select-all').onclick();assert.equal(a.state.selected.size,48);
  await a.ids.get('next').onclick();assert.deepEqual(selected(a),[]);
  a.ids.get('select-all').onclick();assert.deepEqual(selected(a),[49]);
  await a.ids.get('prev').onclick();assert.deepEqual(selected(a),[]);
  a.ids.get('clear').onclick();assert.equal(a.state.selected.size,0);
});

test('card clicks and keyboard toggle while inner buttons and checkbox clicks do not double-toggle',async()=>{
  const a=await app();const card=a.card(image(1));
  card.fire('click');assert.deepEqual(selected(a),[1]);
  card.fire('click',{target:card.querySelector('.meta').children.find(n=>n.tagName==='button')});assert.deepEqual(selected(a),[1]);
  card.fire('keydown',{key:' '});assert.deepEqual(selected(a),[]);
  card.fire('keydown',{key:'Enter'});assert.deepEqual(selected(a),[1]);
  const box=card.querySelector('input');box.checked=false;box.fire('change');
  card.fire('click',{target:box});assert.deepEqual(selected(a),[]);
});

test('history page select and clear affect only restorable rows on that page',async()=>{
  const a=await app();
  a.respond(url=>({total:49,items:url.includes('offset=48')?[{id:49,state:'moved',original:'last',destination:'backup'}]:[
    {id:1,state:'moved',original:'first',destination:'backup'},{id:2,state:'restored',original:'other',destination:'backup'}]}));
  await a.setView('history');a.ids.get('select-all').onclick();assert.deepEqual([...a.state.historySelected.keys()],[1]);
  assert.equal(a.ids.get('page').textContent,'Page 1 of 2');
  await a.ids.get('next').onclick();assert.equal(a.state.historySelected.size,0);
  a.ids.get('select-all').onclick();assert.deepEqual([...a.state.historySelected.keys()],[49]);
  a.ids.get('clear').onclick();assert.equal(a.state.historySelected.size,0);
  assert.equal(a.ids.get('next').disabled,true);
});

test('removed last-page groups clamp to a filled page and prune moved selections',async()=>{
  const a=await app();let removed=false;
  a.respond(url=>({total:removed?12:13,items:removed&&url.includes('offset=12')?[]:[group(1,2)]}));
  a.state.page=1;await a.load();assert.deepEqual(selected(a),[2]);
  removed=true;await a.load();assert.equal(a.state.page,0);assert.equal(a.ids.get('page').textContent,'Page 1 of 1');
  a.respond(()=>({total:0,items:[]}));await a.load();assert.deepEqual(selected(a),[]);
});

test('directory metadata truncates the middle, preserves the full hover path, and marks differences',async()=>{
  const a=await app();const img=image(1);img.path='C:/a-very-long-common-directory-name/another-long-folder/unique/photo.jpg';
  const card=a.card(img,null,[img,{...image(2),path:img.path.replace('unique','other')}]);
  const directory=card.querySelector('.directory');
  assert.equal(directory.title,img.path.slice(0,-10));
  assert.ok(directory.children.some(n=>n.textContent.includes('…')));
  assert.ok(directory.children.some(n=>n.tagName==='mark'));
});

test('scan text has unknown discovery totals, real percentages, cache accounting, and failure counts',async()=>{
  const a=await app();
  const discovery=a.scanStatusText({state:'running',elapsed:3,stats:{stage:'discovery',found:1200,total:null}});
  assert.match(discovery,/found 1200/);assert.doesNotMatch(discovery,/%/);
  const processing=a.scanStatusText({state:'running',elapsed:30,stats:{stage:'processing',total:4000,processed:3100,cached:3000}});
  assert.match(processing,/3,100 \/ 4,000 · 77%/);assert.match(processing,/~5m left/);
  assert.match(a.scanStatusText({state:'error',elapsed:3,stats:{stage:'processing',total:100,processed:20}}),/Scan stopped.*20%/);
  assert.doesNotMatch(a.scanStatusText({state:'error',stats:{stage:'discovery',found:12,total:null}}),/%/);
});

test('scan failure stops the loader while retaining partial progress',async()=>{
  const a=await app();
  a.respond(url=>url==='/api/scan'?{state:'error',error:'Drive disconnected',scan_id:1,stats:{stage:'processing',total:4000,processed:1000}}:
    url.startsWith('/api/summary')?{counts:{},roots:[],blurry:0}:{total:0,items:[]});
  a.scanActivity(true);await a.pollScan();
  assert.equal(a.ids.get('scan-progress').hidden,true);
  assert.match(a.ids.get('scan-state').textContent,/25%/);
  assert.equal(a.ids.get('message').textContent,'Drive disconnected');
});

test('page transitions disable operations and a failed load clears stale selections',async()=>{
  const a=await app();a.respond(()=>({total:2,items:[group(1,2)]}));await a.load();
  assert.deepEqual(selected(a),[2]);
  let reject;const waiting=new Promise((resolve,rejectRequest)=>reject=rejectRequest);a.respond(()=>waiting);
  a.state.page=1;const loading=a.load();
  assert.equal(a.ids.get('preview').disabled,true);assert.equal(a.ids.get('select-all').disabled,true);
  reject(new Error('Connection interrupted'));await assert.rejects(loading,/Connection interrupted/);
  assert.deepEqual(selected(a),[]);assert.equal(a.state.pageItems.size,0);assert.equal(a.state.loading,false);
  assert.equal(a.ids.get('preview').disabled,true);
});

test('media dropdowns keep their own filters and audio never inherits image orientation or blur',async()=>{
  const a=await app(),urls=[];
  a.respond(url=>{urls.push(url);return {total:0,items:[]};});
  a.ids.get('media-type').value='image';await a.ids.get('media-type').fire('change');
  a.ids.get('image-orientation').value='LANDSCAPE';a.ids.get('image-sort').value='blur';
  a.ids.get('image-blurry').checked=true;await a.setView('images');
  assert.match(urls.at(-1),/orientation=LANDSCAPE/);assert.match(urls.at(-1),/blurry=true/);
  a.ids.get('filters-audio').open=true;await a.ids.get('filters-audio').fire('toggle');
  a.ids.get('audio-sort').value='duration';await a.ids.get('audio-sort').fire('change');
  assert.equal(a.ids.get('media-type').value,'audio');assert.match(urls.at(-1),/media_type=audio/);
  assert.match(urls.at(-1),/sort=duration/);assert.doesNotMatch(urls.at(-1),/orientation=/);
  assert.match(urls.at(-1),/blurry=false/);
  a.ids.get('media-type').value='image';await a.ids.get('media-type').fire('change');
  assert.match(urls.at(-1),/orientation=LANDSCAPE/);assert.match(urls.at(-1),/sort=blur/);
  assert.equal(a.ids.get('filters-image').open,true);assert.equal(a.ids.get('filters-audio').open,false);
  a.ids.get('media-type').value='';await a.ids.get('media-type').fire('change');
  assert.equal(a.ids.has('orientation'),false);assert.doesNotMatch(urls.at(-1),/orientation=/);
});

test('every completed scan opens duplicate results and scrolls to the review queue',async()=>{
  const a=await app();
  a.respond(url=>url==='/api/scan'?{state:'complete',scan_id:1,stats:{found:2,cached:2,analyzed:0,errors:0}}:
    url.startsWith('/api/summary')?{counts:{active:2},roots:[],blurry:0}:{total:1,items:[group(1,2)]});
  a.state.view='history';a.ids.get('media-type').value='audio';await a.pollScan();
  assert.equal(a.state.view,'groups');assert.equal(a.ids.get('media-type').value,'');
  assert.equal(a.ids.get('result-label').scrolled,true);assert.equal(a.ids.get('scan-progress').hidden,true);
  assert.deepEqual(selected(a),[2]);
});

test('scan without duplicates shows all scanned files, including cached rescans',async()=>{
  const a=await app();
  a.respond(url=>url.startsWith('/api/summary')?{counts:{active:1},roots:[],blurry:0}:
    url.startsWith('/api/groups')?{total:0,items:[]}:{total:1,items:[image(1)]});
  await a.showScanResults({stats:{cached:1,analyzed:0,errors:0}});
  assert.equal(a.state.view,'images');assert.equal(a.state.total,1);assert.equal(a.ids.get('result-label').scrolled,true);
});

test('scan with only failed media shows the errors as results',async()=>{
  const a=await app();let imagesUrl;
  a.respond(url=>url.startsWith('/api/summary')?{counts:{error:1},roots:[],blurry:0}:
    url.startsWith('/api/groups')?{total:0,items:[]}:(imagesUrl=url,{total:0,items:[]}));
  await a.showScanResults({stats:{cached:0,analyzed:0,errors:1}});
  assert.equal(a.state.view,'errors');assert.match(imagesUrl,/status=error/);
});

test('results tabs switch between duplicates and errors without leaking status or blur filters',async()=>{
  const a=await app(),urls=[];
  a.respond(url=>{urls.push(url);return {total:0,items:[]};});
  a.ids.get('media-type').value='image';
  a.ids.get('image-blurry').checked=true;
  a.ids.get('image-orientation').value='LANDSCAPE';
  await a.ids.get('results-errors').onclick();
  assert.equal(a.state.view,'errors');assert.match(urls.at(-1),/status=error/);
  assert.match(urls.at(-1),/blurry=false/);assert.equal(a.ids.get('results-errors')['aria-selected'],'true');
  assert.doesNotMatch(urls.at(-1),/orientation=/);
  await a.ids.get('results-duplicates').onclick();assert.match(urls.at(-1),/\/api\/groups/);
  assert.equal(a.ids.get('results-errors')['aria-selected'],'false');
  await a.ids.get('results-duplicates').fire('keydown',{key:'End'});
  assert.equal(a.state.view,'errors');assert.equal(a.ids.get('results-errors').focused,true);
});

test('scan with errors and no duplicates opens Errors even when some files succeeded',async()=>{
  const a=await app();
  a.respond(url=>url.startsWith('/api/summary')?{counts:{active:3,error:1},roots:[],blurry:0}:{total:0,items:[]});
  await a.showScanResults({stats:{cached:3,analyzed:0,errors:1}});
  assert.equal(a.state.view,'errors');assert.equal(a.ids.get('results-errors-count').textContent,1);
});

test('All media requests errors and active files with review priority, and labels duplicate cards',async()=>{
  const a=await app();let request;
  a.respond(url=>{request=url;return {total:1,items:[{...image(1),duplicate_kind:'near'}]};});
  await a.setView('images');
  assert.match(request,/status=all/);assert.match(request,/review_first=true/);
  const card=a.card({...image(1),duplicate_kind:'exact'});
  assert.ok(card.querySelector('.meta').children.some(n=>n.textContent==='Exact duplicate'));
  await a.setView('errors');assert.match(request,/status=error/);assert.doesNotMatch(request,/review_first=/);
});

test('new UI with an older running server reports the mismatch instead of an empty All media list',async()=>{
  const a=await app();a.state.settings.capabilities=undefined;
  await assert.rejects(a.setView('images'),/server is running an older version/);
  assert.equal(a.ids.get('results').children[0].children[1].textContent,'Results unavailable');
});
