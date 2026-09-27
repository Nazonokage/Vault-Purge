const $ = id => document.getElementById(id);
const state = {view:'groups', layout:localStorage.getItem('vaultpurge_layout')||'grid', page:0, total:0, settings:null, selected:new Map(), preview:null, busy:false, generation:0, scanId:null};
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
  if(image.status==='active'||image.status==='moved'){
    const img=el('img');img.src=`/thumb/${image.id}`;img.alt=image.path.split(/[\\/]/).pop();img.loading='lazy';node.append(img);
  }else if(image.integrity==='suspect'){node.append(el('div','⚠ Possible corruption','integrity-placeholder'));}
  if(image.status==='active'||(image.status==='error'&&image.integrity==='suspect')){
    const label=el('label',undefined,'card-select');const checkbox=el('input');checkbox.type='checkbox';checkbox.setAttribute('aria-label',`Select ${image.path} for moving`);
    checkbox.addEventListener('change',()=>{checkbox.checked?state.selected.set(image.id,image):state.selected.delete(image.id);selectionChanged();});label.append(checkbox);node.append(label);
  }
  if(recommended){const badge=el('span','Suggested keep','keep-badge');badge.title=recommendation.reason;node.append(badge);}
  const meta=el('div',undefined,'meta');const name=el('p',image.path.split(/[\\/]/).pop(),'filename');name.title=image.path;meta.append(name);
  meta.append(el('p',`${image.width} × ${image.height} · ${(image.size/1024).toFixed(0)} KB`,'details'),el('span',image.orientation,'badge'));
  if(image.media_type==='video'){meta.append(el('p',`VIDEO · ${image.duration===null?'Unknown duration':image.duration.toFixed(1)+' seconds'}`,'details'));}
  if(image.blur_score!==null){const blurry=image.blur_score<state.settings.blur_threshold;meta.append(el('p',`${image.media_type==='video'?'Sampled frames · ':''}${blurry?'Potential blur':'Sharpness score'} · ${image.blur_score.toFixed(1)}`,'details'));}
  const integrityLabels={checked:'Image integrity checks passed',sampled:'Video samples decoded · not a full integrity check',unchecked:'Integrity not checked',suspect:'Possible corruption · review before removal',unreadable:'Cannot access file · corruption not established'};
  meta.append(el('p',integrityLabels[image.integrity]||'Integrity not checked',image.integrity==='suspect'?'error-detail':'details'));
  if(image.status==='error'&&image.integrity==='suspect'){const prepare=el('button','Prepare quarantine','secondary');prepare.addEventListener('click',()=>{state.selected.set(image.id,image);selectionChanged();$('preview').click();});meta.append(el('p','Try opening this file in another app or recover it from a backup. If unusable, move it aside for deletion review.','details'),prepare);}
  const reveal=el('button','Show in folder','secondary');reveal.type='button';reveal.title=image.status==='moved'?'Show moved file in backup folder':`Show ${image.path} in file manager`;reveal.onclick=run(async e=>{e.stopPropagation();await api(`/api/images/${image.id}/reveal`,{method:'POST'});});meta.append(reveal);
  if(image.error)meta.append(el('p',image.error,'error-detail'));
  node.append(meta);return node;
}
function empty(title, text) {const node=el('div',undefined,'empty');node.append(el('div','▧','symbol'),el('h3',title),el('p',text));return node;}
async function refreshSummary(){
  if(state.scanId===null){resetSummary();return;}
  const scanId=state.scanId;const data=await api(`/api/summary?scan_id=${scanId}`);if(state.scanId!==scanId)return;$('count-images').textContent=data.counts.active||0;$('count-blurry').textContent=data.blurry;$('count-moved').textContent=data.counts.moved||0;$('count-errors').textContent=data.counts.error||0;
  const selected=$('root').value;$('root').replaceChildren(new Option('Current scan',''));data.roots.forEach(root=>$('root').add(new Option(root,root)));$('root').value=selected;
}
async function load(){
  const generation=++state.generation;
  if(state.scanId===null && ['groups','images'].includes(state.view)){showBlank();return;}
  const params=new URLSearchParams({offset:state.page*pageSize(),limit:pageSize()});
  if(state.scanId!==null)params.set('scan_id',state.scanId);
  if($('root').value)params.set('root',$('root').value);
  if($('orientation').value)params.set('orientation',$('orientation').value);
  if($('media-type').value)params.set('media_type',$('media-type').value);
  params.set('sort',$('sort').value);
  const container=document.createDocumentFragment();
  let total=0;
  if(state.view==='groups'){
    if($('kind').value)params.set('kind',$('kind').value);
    const data=await api(`/api/groups?${params}`);total=data.total;
    data.items.forEach(group=>{const section=el('article',undefined,'group');const heading=el('div',undefined,'group-heading');const text=el('div');text.append(el('h3',`${group.members.length} files to compare`),el('p',group.kind==='near'?(group.members[0].media_type==='video'?'Similar duration and three matching frame samples. Audio and unsampled scenes may differ.':'Each matches the group anchor; members may differ from each other.'):'Identical file hashes. Choose the copies you want to move.'));heading.append(text,el('span',group.kind==='exact'?'Exact copies':'Possible duplicates',`badge ${group.kind}`));section.append(heading);const cards=el('div',undefined,'cards');group.members.forEach(image=>cards.append(card(image,group.recommendation)));section.append(cards);container.append(section);});
    if(!total)container.append(empty('A clearer view starts here','Scan a folder to find matching images. If you’ve already scanned, no groups match these filters.'));
  }else if(state.view==='images'){
    params.set('status',$('status').value==='suspect'?'error':$('status').value);if($('status').value==='suspect')params.set('integrity','suspect');params.set('blurry',$('blurry').checked);
    const data=await api(`/api/images?${params}`);total=data.total;const grid=el('div',undefined,'cards');data.items.forEach(image=>grid.append(card(image)));container.append(grid);
    if(!total)container.append(empty('No images in this view','Choose another filter or scan a folder to add images.'));
  }else if(state.view==='scans'){
    const data=await api(`/api/scans?${params}`);total=data.total;
    data.items.forEach(scan=>{const row=el('article',undefined,'history-row');
      row.append(el('strong',scan.root),el('p',`${scan.started_at?new Date(scan.started_at).toLocaleString():'Imported cache · original date unknown'} · ${scan.state}`));
      if(scan.stats_json){const stats=JSON.parse(scan.stats_json);row.append(el('p',`${stats.found} found · ${stats.cached} cached · ${stats.errors} errors`));}
      if(scan.error)row.append(el('p',scan.error,'error-detail'));
      const open=el('button','Show results','secondary');open.disabled=state.busy;open.onclick=run(()=>openScan(scan));row.append(open);container.append(row);
    });
    if(!data.items.length)container.append(empty('No scan history','Scans appear here after you choose a directory and scan it.'));
  }else{
    const data=await api(`/api/moves?${params}`);total=state.page*pageSize()+data.length+(data.length===pageSize()?1:0);
    data.forEach(move=>{const row=el('article',undefined,'history-row');row.append(el('strong',`Move #${move.id} · ${move.state}`),el('p',move.original),el('p',`→ ${move.destination}`));if(move.error)row.append(el('p',move.error,'error-detail'));const reveal=el('button','Show in folder','secondary');reveal.title=move.state==='restored'?'Show restored file in original folder':'Show moved file in backup folder';reveal.onclick=run(async()=>{await api(`/api/moves/${move.id}/reveal?target=${move.state==='restored'?'original':'destination'}`,{method:'POST'});});row.append(reveal);if(move.state==='moved'){const button=el('button','Restore original','secondary');button.disabled=state.settings.dry_run;button.addEventListener('click',run(async()=>{if(!confirm(`Restore this file to its original path?\n${move.original}`))return;const result=await api(`/api/moves/${move.id}/restore`,{method:'POST',body:JSON.stringify({token:'',confirm:true})});await refresh();if(result.state==='attention')message(result.error);}));row.append(button);}container.append(row);});
    if(!data.length)container.append(empty('Your moves will appear here','Completed moves can be restored here. Disable preview-only mode to restore.'));
  }
  if(generation!==state.generation)return;
  state.total=total;$('results').replaceChildren(container);$('result-count').textContent=state.view==='history'?'Recorded file operations':state.view==='scans'?`${total} scans`:`${total} ${state.view==='groups'?'groups':'files'}`;
  $('page').textContent=`Page ${state.page+1}`;$('prev').disabled=state.page===0;$('next').disabled=(state.page+1)*pageSize()>=total;selectionChanged();
}
function setLayout(layout){
  state.layout=layout;
  try{localStorage.setItem('vaultpurge_layout',layout);}catch(_){}
  $('layout-grid').classList.toggle('active',layout==='grid');
  $('layout-list').classList.toggle('active',layout==='list');
  $('results').classList.toggle('list-mode',layout==='list');
}
async function refresh(){await refreshSummary();await load();}
function setView(view){state.view=view;state.page=0;document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('title').textContent={groups:'Duplicate groups',images:'Your media library',history:'Move history',scans:'Scan history'}[view];$('kind').disabled=view!=='groups';$('status').disabled=view!=='images';$('blurry').disabled=view!=='images';$('orientation').disabled=['history','scans'].includes(view);$('root').disabled=['history','scans'].includes(view);$('media-type').disabled=['history','scans'].includes(view);$('sort').disabled=['history','scans'].includes(view);$('clear-scan-history').hidden=view!=='scans';$('layout-toggle').hidden=['history','scans'].includes(view);return load();}
document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',run(()=>setView(b.dataset.view))));
['root','orientation','kind','status','blurry','media-type','sort'].forEach(id=>$(id).addEventListener('change',run(async()=>{state.page=0;await load();})));
$('layout-grid').onclick=()=>setLayout('grid');$('layout-list').onclick=()=>setLayout('list');
$('prev').onclick=run(async()=>{state.page--;await load();});$('next').onclick=run(async()=>{state.page++;await load();});
$('clear').onclick=()=>{state.selected.clear();selectionChanged();};
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>$(button.dataset.close).close());
$('settings-open').onclick=()=>{const s=state.settings;$('dry-run').checked=s.dry_run;$('recommend').checked=s.show_recommendation;$('threshold').value=s.phash_threshold;$('blur-threshold').value=s.blur_threshold;$('settings-dialog').showModal();};
$('settings-form').onsubmit=run(async event=>{event.preventDefault();state.settings=await api('/api/settings',{method:'PUT',body:JSON.stringify({dry_run:$('dry-run').checked,show_recommendation:$('recommend').checked,phash_threshold:Number($('threshold').value),blur_threshold:Number($('blur-threshold').value)})});$('mode').textContent=state.settings.dry_run?'Preview only':'Moves enabled';$('settings-dialog').close();await refresh();});
async function pollScan(){
  const job=await api('/api/scan');state.busy=job.state==='running';$('scan-button').disabled=state.busy;selectionChanged();
  if(job.scan_id!==null)state.scanId=job.scan_id;
  if(job.stats)$('scan-state').textContent=`${state.busy?'Scanning':'Scan complete'} · ${job.stats.found} found · ${job.stats.analyzed} analyzed · ${job.stats.cached} cached · ${job.stats.errors} errors`;
  if(state.busy){setTimeout(()=>run(pollScan)(),750);return;}
  if(job.state==='error'){$('scan-state').textContent='Scan stopped';message(job.error);}
  await refresh();
}
$('scan-form').onsubmit=run(async event=>{event.preventDefault();await api('/api/scan',{method:'POST',body:JSON.stringify({path:$('folder').value,recursive:$('recursive').checked,classify_only:$('classify').checked,force:$('force').checked})});resetScanView();state.busy=true;await setView('groups');$('scan-state').textContent='Scanning…';await pollScan();});
$('preview').onclick=async()=>{
  state.preview=null;$('destination').value='';$('allow-move').checked=false;$('preview-list').replaceChildren();$('confirm-move').disabled=true;
  $('preview-note').textContent='Finding a destination beside the scanned folder…';$('move-dialog').showModal();
  try{const result=await api('/api/move/destination',{method:'POST',body:JSON.stringify({ids:[...state.selected.keys()]})});$('destination').value=result.destination;await buildMovePreview();}
  catch(error){$('preview-note').textContent=error.message;}
};
function updateMoveButton(){ $('confirm-move').disabled=!state.preview||!$('allow-move').checked; }
$('allow-move').onchange=updateMoveButton;
$('destination').oninput=()=>{state.preview=null;$('confirm-move').disabled=true;};
async function buildMovePreview(){try{$('refresh-preview').disabled=true;const data=await api('/api/move/preview',{method:'POST',body:JSON.stringify({ids:[...state.selected.keys()],destination:$('destination').value})});state.preview=data;$('preview-list').replaceChildren();data.items.forEach(item=>{const row=el('div',undefined,'preview-row');row.append(el('p',item.source),el('p',`→ ${item.destination}`));if(item.reason)row.append(el('p',item.reason,'error-detail'));$('preview-list').append(row);});$('preview-note').textContent=`${data.items.length} files will move to the destinations below. No files have moved yet.`;$('confirm-move').textContent=`Move ${data.items.length} files`;updateMoveButton();}catch(error){state.preview=null;$('confirm-move').disabled=true;$('preview-note').textContent=error.message;}finally{$('refresh-preview').disabled=false;}};
$('refresh-preview').onclick=buildMovePreview;
$('confirm-move').onclick=async()=>{if(!state.preview||!$('allow-move').checked)return;try{$('confirm-move').disabled=true;const result=await api('/api/move',{method:'POST',body:JSON.stringify({token:state.preview.token,confirm:true,allow_move:$('allow-move').checked})});state.selected.clear();state.preview=null;$('move-dialog').close();await setView('history');await refreshSummary();const failed=result.items.find(m=>m.state==='attention');if(failed)message(`Operation stopped: ${failed.error}. Inspect the paths in move history.`);}catch(error){$('preview-note').textContent=error.message;}};
run(async()=>{state.settings=await api('/api/settings');$('destination').value=state.settings.dest_folder;$('mode').textContent=state.settings.dry_run?'Preview only':'Moves enabled';setLayout(state.layout);showBlank();})();

const folderBrowser = {path:'', parent:null, offset:0, target:'scan', name:''};
async function browseFolder(path='', offset=0) {
  try {
    $('folder-error').textContent='';
    const params=new URLSearchParams({offset});if(path)params.set('path',path);
    const data=await api(`/api/folders?${params}`,{method:'POST'});
    folderBrowser.path=data.path;folderBrowser.parent=data.parent;folderBrowser.offset=offset;
    $('folder-location').value=data.path;$('folder-list').replaceChildren();
    data.items.forEach(path=>{const button=el('button',path.split(/[\\/]/).filter(Boolean).pop()||path,'folder-item secondary');button.title=path;button.onclick=()=>browseFolder(path);$('folder-list').append(button);});
    if(!data.items.length)$('folder-list').append(el('p','No subfolders here. You can select this folder.'));
    $('folder-up').disabled=data.parent===null;$('folder-choose').disabled=!data.path;
    $('folder-prev').disabled=offset===0;$('folder-next').disabled=offset+100>=data.total;
  } catch(error) {$('folder-error').textContent=error.message;}
}
$('browse-folder').onclick=()=>{folderBrowser.target='scan';$('folder-dialog').querySelector('h2').textContent='Choose a scan folder';$('folder-choose').textContent='Use this folder';$('folder-dialog').showModal();browseFolder($('folder').value);};
$('folder-form').onsubmit=event=>{event.preventDefault();browseFolder($('folder-location').value);};
$('folder-up').onclick=()=>browseFolder(folderBrowser.parent);
$('folder-drives').onclick=()=>browseFolder();
$('folder-prev').onclick=()=>browseFolder(folderBrowser.path,Math.max(0,folderBrowser.offset-100));
$('folder-next').onclick=()=>browseFolder(folderBrowser.path,folderBrowser.offset+100);
$('choose-destination').onclick=()=>{
  folderBrowser.target='destination';const parts=$('destination').value.replaceAll('\\','/').split('/');folderBrowser.name=parts.pop()||'moved_files';
  $('folder-dialog').querySelector('h2').textContent='Choose where to create the destination folder';$('folder-choose').textContent='Create destination here';$('folder-dialog').showModal();browseFolder(parts.join('/')||'');
};
$('folder-choose').onclick=()=>{
  if(folderBrowser.target==='destination'){$('destination').value=folderBrowser.path.replace(/[\\/]+$/,'')+'/'+folderBrowser.name;state.preview=null;$('confirm-move').disabled=true;$('folder-dialog').close();buildMovePreview();}
  else{$('folder').value=folderBrowser.path;$('folder-dialog').close();}
};

function resetSummary(){
  ['count-images','count-blurry','count-moved','count-errors'].forEach(id=>$(id).textContent='0');
  $('root').replaceChildren(new Option('Current scan',''));
}
function showBlank(){
  state.total=0;resetSummary();$('results').replaceChildren(empty('Ready for a new scan','Choose a target directory and click Scan folder. Previous results are available in Scan history.'));
  $('result-count').textContent='';$('page').textContent='';$('prev').disabled=true;$('next').disabled=true;selectionChanged();
}
function resetScanView(){
  state.scanId=null;state.page=0;state.generation++;state.selected.clear();state.preview=null;
  ['orientation','media-type','kind','root'].forEach(id=>$(id).value='');$('status').value='active';$('blurry').checked=false;
  resetSummary();selectionChanged();
}
async function openScan(scan){
  resetScanView();state.scanId=scan.id;$('folder').value=scan.root;
  $('scan-state').textContent=`Viewing saved scan: ${scan.root}. File membership is saved; displayed details reflect the latest cached state.`;
  await setView('groups');await refreshSummary();
}
$('show-last-scan').onclick=run(async()=>{
  if(state.busy){message('Wait for the current scan to finish.');return;}
  const data=await api('/api/scans?limit=1');if(!data.items.length){message('No saved scans yet. Choose a directory and scan it first.');return;}
  await openScan(data.items[0]);
});
$('clear-scan-view').onclick=run(async()=>{
  if(state.busy){message('Wait for the current scan to finish.');return;}
  resetScanView();$('scan-state').textContent='Choose a folder to begin. Scanning never moves your files.';await setView('groups');
});
$('clear-scan-history').onclick=run(async()=>{
  if(!confirm('Clear all scan history entries? Your files, analysis cache, and move/restore history will be kept.'))return;
  await api('/api/scans',{method:'DELETE'});resetScanView();$('scan-state').textContent='Scan history cleared. Choose a directory to start again.';await load();
});
