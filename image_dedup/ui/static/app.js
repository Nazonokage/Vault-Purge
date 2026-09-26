const $ = id => document.getElementById(id);
const state = {view:'groups', page:0, total:0, settings:null, selected:new Map(), preview:null, busy:false, generation:0};
const pageSize = () => state.view === 'groups' ? 12 : 48;
function el(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
function message(text='') {$('message').textContent=text; $('message').hidden=!text;}
async function api(path, options={}) {
  const response=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Session-Token':state.settings?.session_token||'',...options.headers}});
  const body=await response.json();
  if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));
  return body;
}
function run(fn) {return async (...args)=>{try {message(); await fn(...args);}catch(error){message(error.message);}};}
function selectionChanged() {
  $('selected-count').textContent=`${state.selected.size} selected`;
  $('preview').disabled=!state.selected.size||state.busy;
  document.querySelectorAll('.image-card').forEach(card=>{
    const selected=state.selected.has(Number(card.dataset.id));card.classList.toggle('selected',selected);
    const box=card.querySelector('input');if(box)box.checked=selected;
  });
}
function card(image, recommendation) {
  const node=el('article',undefined,'image-card');node.dataset.id=image.id;
  const recommended=state.settings.show_recommendation&&recommendation?.id===image.id;
  node.classList.toggle('recommended',recommended);
  if(image.status==='active'){
    const img=el('img');img.src=`/thumb/${image.id}`;img.alt=image.path.split(/[\\/]/).pop();img.loading='lazy';node.append(img);
    const label=el('label',undefined,'card-select');const checkbox=el('input');checkbox.type='checkbox';checkbox.setAttribute('aria-label',`Select ${image.path} for moving`);
    checkbox.addEventListener('change',()=>{checkbox.checked?state.selected.set(image.id,image):state.selected.delete(image.id);selectionChanged();});label.append(checkbox);node.append(label);
  }
  if(recommended){const badge=el('span','Suggested keep','keep-badge');badge.title=recommendation.reason;node.append(badge);}
  const meta=el('div',undefined,'meta');const name=el('p',image.path.split(/[\\/]/).pop(),'filename');name.title=image.path;meta.append(name);
  meta.append(el('p',`${image.width} × ${image.height} · ${(image.size/1024).toFixed(0)} KB`,'details'),el('span',image.orientation,'badge'));
  if(image.blur_score!==null){const blurry=image.blur_score<state.settings.blur_threshold;meta.append(el('p',`${blurry?'Potential blur':'Sharpness score'} · ${image.blur_score.toFixed(1)}`,'details'));}
  if(image.error)meta.append(el('p',image.error,'error-detail'));
  node.append(meta);return node;
}
function empty(title, text) {const node=el('div',undefined,'empty');node.append(el('div','▧','symbol'),el('h3',title),el('p',text));return node;}
async function refreshSummary(){
  const data=await api('/api/summary');$('count-images').textContent=data.counts.active||0;$('count-blurry').textContent=data.blurry;$('count-moved').textContent=data.counts.moved||0;$('count-errors').textContent=data.counts.error||0;
  const selected=$('root').value;$('root').replaceChildren(new Option('All folders',''));data.roots.forEach(root=>$('root').add(new Option(root,root)));$('root').value=selected;
}
async function load(){
  const generation=++state.generation;
  const params=new URLSearchParams({offset:state.page*pageSize(),limit:pageSize()});
  if($('root').value)params.set('root',$('root').value);
  if($('orientation').value)params.set('orientation',$('orientation').value);
  const container=document.createDocumentFragment();
  let total=0;
  if(state.view==='groups'){
    if($('kind').value)params.set('kind',$('kind').value);
    const data=await api(`/api/groups?${params}`);total=data.total;
    data.items.forEach(group=>{const section=el('article',undefined,'group');const heading=el('div',undefined,'group-heading');const text=el('div');text.append(el('h3',`${group.members.length} images to compare`),el('p',group.kind==='near'?'Each matches the group anchor; members may differ from each other.':'Identical file hashes. Choose the copies you want to move.'));heading.append(text,el('span',group.kind==='exact'?'Exact copies':'Possible duplicates',`badge ${group.kind}`));section.append(heading);const cards=el('div',undefined,'cards');group.members.forEach(image=>cards.append(card(image,group.recommendation)));section.append(cards);container.append(section);});
    if(!total)container.append(empty('A clearer view starts here','Scan a folder to find matching images. If you’ve already scanned, no groups match these filters.'));
  }else if(state.view==='images'){
    params.set('status',$('status').value);params.set('blurry',$('blurry').checked);
    const data=await api(`/api/images?${params}`);total=data.total;const grid=el('div',undefined,'cards');data.items.forEach(image=>grid.append(card(image)));container.append(grid);
    if(!total)container.append(empty('No images in this view','Choose another filter or scan a folder to add images.'));
  }else{
    const data=await api(`/api/moves?${params}`);total=state.page*pageSize()+data.length+(data.length===pageSize()?1:0);
    data.forEach(move=>{const row=el('article',undefined,'history-row');row.append(el('strong',`Move #${move.id} · ${move.state}`),el('p',move.original),el('p',`→ ${move.destination}`));if(move.error)row.append(el('p',move.error,'error-detail'));if(move.state==='moved'){const button=el('button','Restore original','secondary');button.disabled=state.settings.dry_run;button.addEventListener('click',run(async()=>{if(!confirm(`Restore this image to its original path?\n${move.original}`))return;const result=await api(`/api/moves/${move.id}/restore`,{method:'POST',body:JSON.stringify({token:'',confirm:true})});await refresh();if(result.state==='attention')message(result.error);}));row.append(button);}container.append(row);});
    if(!data.length)container.append(empty('Your moves will appear here','Completed moves can be restored here. Disable preview-only mode to restore.'));
  }
  if(generation!==state.generation)return;
  state.total=total;$('results').replaceChildren(container);$('result-count').textContent=state.view==='history'?'Recorded file operations':`${total} ${state.view==='groups'?'groups':'images'}`;
  $('page').textContent=`Page ${state.page+1}`;$('prev').disabled=state.page===0;$('next').disabled=(state.page+1)*pageSize()>=total;selectionChanged();
}
async function refresh(){await refreshSummary();await load();}
function setView(view){state.view=view;state.page=0;document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('title').textContent={groups:'Duplicate groups',images:'Your image library',history:'Move history'}[view];$('kind').disabled=view!=='groups';$('status').disabled=view!=='images';$('blurry').disabled=view!=='images';$('orientation').disabled=view==='history';$('root').disabled=view==='history';return load();}
document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',run(()=>setView(b.dataset.view))));
['root','orientation','kind','status','blurry'].forEach(id=>$(id).addEventListener('change',run(async()=>{state.page=0;await load();})));
$('prev').onclick=run(async()=>{state.page--;await load();});$('next').onclick=run(async()=>{state.page++;await load();});
$('clear').onclick=()=>{state.selected.clear();selectionChanged();};
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>$(button.dataset.close).close());
$('settings-open').onclick=()=>{const s=state.settings;$('dry-run').checked=s.dry_run;$('recommend').checked=s.show_recommendation;$('threshold').value=s.phash_threshold;$('blur-threshold').value=s.blur_threshold;$('settings-dialog').showModal();};
$('settings-form').onsubmit=run(async event=>{event.preventDefault();state.settings=await api('/api/settings',{method:'PUT',body:JSON.stringify({dry_run:$('dry-run').checked,show_recommendation:$('recommend').checked,phash_threshold:Number($('threshold').value),blur_threshold:Number($('blur-threshold').value)})});$('mode').textContent=state.settings.dry_run?'Preview only':'Moves enabled';$('settings-dialog').close();await refresh();});
async function pollScan(){
  const job=await api('/api/scan');state.busy=job.state==='running';$('scan-button').disabled=state.busy;selectionChanged();
  if(job.stats)$('scan-state').textContent=`${state.busy?'Scanning':'Scan complete'} · ${job.stats.found} found · ${job.stats.analyzed} analyzed · ${job.stats.cached} cached · ${job.stats.errors} errors`;
  if(state.busy){setTimeout(()=>run(pollScan)(),750);return;}
  if(job.state==='error'){$('scan-state').textContent='Scan stopped';message(job.error);}
  await refresh();
}
$('scan-form').onsubmit=run(async event=>{event.preventDefault();await api('/api/scan',{method:'POST',body:JSON.stringify({path:$('folder').value,recursive:$('recursive').checked,classify_only:$('classify').checked,force:$('force').checked})});state.selected.clear();$('scan-state').textContent='Scanning…';await pollScan();});
$('preview').onclick=()=>{state.preview=null;$('preview-list').replaceChildren();$('preview-note').textContent='Build a preview to review the destination of each selected image.';$('confirm-move').disabled=true;$('move-dialog').showModal();};
$('destination').oninput=()=>{state.preview=null;$('confirm-move').disabled=true;};
$('refresh-preview').onclick=async()=>{try{$('refresh-preview').disabled=true;const data=await api('/api/move/preview',{method:'POST',body:JSON.stringify({ids:[...state.selected.keys()],destination:$('destination').value})});state.preview=data;$('preview-list').replaceChildren();data.items.forEach(item=>{const row=el('div',undefined,'preview-row');row.append(el('p',item.source),el('p',`→ ${item.destination}`));$('preview-list').append(row);});$('preview-note').textContent=data.dry_run?'Preview only. Close this dialog and disable preview-only mode in settings to allow moves.':`${data.items.length} files ready. Confirming will move exactly these files.`;$('confirm-move').disabled=data.dry_run;}catch(error){state.preview=null;$('confirm-move').disabled=true;$('preview-note').textContent=error.message;}finally{$('refresh-preview').disabled=false;}};
$('confirm-move').onclick=async()=>{if(!state.preview)return;try{$('confirm-move').disabled=true;const result=await api('/api/move',{method:'POST',body:JSON.stringify({token:state.preview.token,confirm:true})});state.selected.clear();state.preview=null;$('move-dialog').close();await setView('history');await refreshSummary();const failed=result.items.find(m=>m.state==='attention');if(failed)message(`Operation stopped: ${failed.error}. Inspect the paths in move history.`);}catch(error){$('preview-note').textContent=error.message;}};
run(async()=>{state.settings=await api('/api/settings');$('destination').value=state.settings.dest_folder;$('mode').textContent=state.settings.dry_run?'Preview only':'Moves enabled';await setView('groups');await pollScan();})();
