const $ = id => document.getElementById(id);
const state = {view:'groups', layout:localStorage.getItem('vaultpurge_layout')||'grid', page:0, total:0, settings:null, selected:new Map(), preview:null, busy:false, generation:0, scanId:null};
const pageSize = () => state.view === 'groups' ? 12 : 48;
Object.assign(state,{pageItems:new Map(),historySelected:new Map(),preselect:true,selectionScope:null,loading:false});
const selection = () => state.view==='history' ? state.historySelected : state.selected;
const selectable = image => image.status==='active'||(image.status==='error'&&image.integrity==='suspect');
const resultViews={groups:'results-duplicates',images:'results-media',errors:'results-errors'};
const mediaTypes=['','image','audio','video'];
const filterNames=['sort','kind','status','orientation','blurry'];
const mediaFilter=(name,type=$('media-type').value)=>$(type?`${type}-${name}`:name);
function syncMediaControls(){
  const history=['history','scans'].includes(state.view);
  for(const type of mediaTypes){
    $(`filters-${type||'all'}`).open=$('media-type').value===type;
    for(const name of filterNames){
      const control=mediaFilter(name,type);if(!control)continue;
      control.disabled=history||(state.view==='errors'&&['status','blurry','orientation'].includes(name))||(name==='kind'&&state.view!=='groups')||(['status','blurry'].includes(name)&&state.view!=='images');
      const label=control.closest('label');if(label)label.hidden=state.view==='errors'&&['status','blurry','orientation'].includes(name);
    }
  }
}
function preselectedIds(groups) {
  const keepers=new Set(groups.flatMap(g=>g.recommendation ? [g.recommendation.id] : g.members.map(r=>r.id)));
  return new Set(groups.flatMap(g=>g.recommendation ? g.members.filter(r=>selectable(r)&&!keepers.has(r.id)).map(r=>r.id) : []));
}
function toggleSelection(item) {
  if(state.loading)return;
  const selected=selection();selected.has(item.id)?selected.delete(item.id):selected.set(item.id,item);selectionChanged();
}
function makeSelectable(node,item) {
  node.dataset.id=item.id;node.tabIndex=0;node.setAttribute('role','group');
  node.setAttribute('aria-label',`Select ${item.path||item.original}`);
  node.addEventListener('click',event=>{if(!event.target.closest('button,input,label,a,video,audio'))toggleSelection(item);});
  node.addEventListener('keydown',event=>{if(event.target===node&&[' ','Enter'].includes(event.key)){event.preventDefault();toggleSelection(item);}});
}
function directoryMetadata(image,members=[]) {
  const folder=image.path.replace(/[\\/][^\\/]*$/,'');
  const parts=folder.split(/([\\/])/);const others=members.filter(r=>r.id!==image.id).map(r=>r.path.replace(/[\\/][^\\/]*$/,'').split(/([\\/])/));
  const node=el('p',undefined,'directory');node.title=folder;node.setAttribute('aria-label',folder);
  // Keep both ends visible, including the differing folder components.
  const full=[];parts.forEach((part,i)=>{for(const char of part)full.push({char,diff:others.some(p=>p[i]!==part)});});
  const visible=full.length>52?[...full.slice(0,24),{char:'…'},...full.slice(-27)]:full;
  let segment=null,lastDiff=null;
  visible.forEach(({char,diff})=>{if(!segment||diff!==lastDiff){segment=el(diff?'mark':'span','');node.append(segment);lastDiff=diff;}segment.textContent+=char;});
  return node;
}
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
  $('selected-count').textContent=`${selection().size} selected on this page`;
  $('preview').hidden=state.view==='history';$('restore-selected').hidden=state.view!=='history';
  $('restore-selected').disabled=!state.historySelected.size||state.busy||state.loading||state.settings?.dry_run;
  $('select-all').disabled=state.busy||state.loading||!state.pageItems.size;
  $('preselect-control').hidden=state.view!=='groups';
  $('preview').disabled=!state.selected.size||state.busy||state.loading;
  $('deep-compare').disabled=state.view==='history'||state.busy||state.loading||state.selected.size!==2||[...state.selected.values()].some(r=>r.status!=='active'||!['audio','video'].includes(r.media_type));
  document.querySelectorAll('.image-card,.history-row[data-id]').forEach(card=>{
    const selected=selection().has(Number(card.dataset.id));card.classList.toggle('selected',selected);
    const box=card.querySelector('input');if(box)box.checked=selected;
  });
}
function card(image, recommendation, members=[]) {
  const node=el('article',undefined,'image-card');node.dataset.id=image.id;
  const recommended=state.settings.show_recommendation&&recommendation?.id===image.id;
  node.classList.toggle('recommended',recommended);
  if(image.media_type==='audio'){node.append(el('div','♫ Audio','integrity-placeholder'));}
  else if(image.status==='active'||image.status==='moved'){
    const img=el('img');img.src=`/thumb/${image.id}`;img.alt=image.path.split(/[\\/]/).pop();img.loading='lazy';node.append(img);
  }else if(image.integrity==='suspect'){node.append(el('div','⚠ Possible corruption','integrity-placeholder'));}
  if(image.status==='active'||(image.status==='error'&&image.integrity==='suspect')){
    makeSelectable(node,image);
    const label=el('label',undefined,'card-select');const checkbox=el('input');checkbox.type='checkbox';checkbox.setAttribute('aria-label',`Select ${image.path} for moving`);
    checkbox.addEventListener('change',()=>{if(state.loading){selectionChanged();return;}checkbox.checked?state.selected.set(image.id,image):state.selected.delete(image.id);selectionChanged();});label.append(checkbox);node.append(label);
  }
  if(recommended){const badge=el('span','Suggested keep','keep-badge');badge.title=recommendation.reason;node.append(badge);}
  const meta=el('div',undefined,'meta');const name=el('p',image.path.split(/[\\/]/).pop(),'filename');name.title=image.path;meta.append(name);
  if(image.status==='error')meta.append(el('span','Scan error','badge error'));
  else if(image.duplicate_kind)meta.append(el('span',image.duplicate_kind==='exact'?'Exact duplicate':'Possible duplicate',`badge ${image.duplicate_kind}`));
  meta.append(directoryMetadata(image,members));
  if(image.media_type!=='audio')meta.append(el('p',`${image.width} × ${image.height} · ${(image.size/1024).toFixed(0)} KB`,'details'),el('span',image.orientation,'badge'));
  if(image.media_type==='audio'){meta.append(el('p',`${image.codec||'Audio'} · ${image.sample_rate||'?'} Hz · ${image.channels||'?'} channels · ${(image.size/1024).toFixed(0)} KB`,'details'));}
  if(['video','audio'].includes(image.media_type)){const play=el('button','Play preview','secondary');play.disabled=image.status!=='active';play.onclick=()=>openPlayer(image);meta.append(play);}
  if(['video','audio'].includes(image.media_type)){meta.append(el('p',`${image.media_type.toUpperCase()} · ${image.duration===null?'Unknown duration':image.duration.toFixed(1)+' seconds'}`,'details'));}
  if(image.blur_score!==null){const threshold=image.media_type==='video'?(state.settings.video_blur_threshold??state.settings.blur_threshold):state.settings.blur_threshold;const blurry=image.blur_score<threshold;meta.append(el('p',`${image.media_type==='video'?'Sampled frames · ':''}${blurry?'Potential blur':'Sharpness score'} · ${image.blur_score.toFixed(1)}`,'details'));}
  const integrityLabels={checked:image.media_type==='audio'?'Audio decoded fully · no errors reported':'Image integrity checks passed',unsupported:'Unsupported audio codec or stream',sampled:'Video samples decoded · not a full integrity check',unchecked:'Integrity not checked',suspect:'Possible corruption · review before removal',unreadable:'Cannot access file · corruption not established'};
  meta.append(el('p',integrityLabels[image.integrity]||'Integrity not checked',image.integrity==='suspect'?'error-detail':'details'));
  if(image.status==='error'&&image.integrity==='suspect'){const prepare=el('button','Prepare quarantine','secondary');prepare.addEventListener('click',()=>{state.selected.set(image.id,image);selectionChanged();$('preview').click();});meta.append(el('p','Try opening this file in another app or recover it from a backup. If unusable, move it aside for deletion review.','details'),prepare);}
  const reveal=el('button','Show in folder','secondary');reveal.type='button';reveal.title=image.status==='moved'?'Show moved file in backup folder':`Show ${image.path} in file manager`;reveal.onclick=run(async e=>{e.stopPropagation();await api(`/api/images/${image.id}/reveal`,{method:'POST'});});meta.append(reveal);
  if(image.analysis_note)meta.append(el('p',image.analysis_note,'details'));
  if(image.error)meta.append(el('p',image.error,'error-detail'));
  node.append(meta);return node;
}
function empty(title, text) {const node=el('div',undefined,'empty');node.append(el('div','▧','symbol'),el('h3',title),el('p',text));return node;}
async function refreshSummary(){
  if(state.scanId===null){resetSummary();return;}
  const scanId=state.scanId;const data=await api(`/api/summary?scan_id=${scanId}`);if(state.scanId!==scanId)return;$('count-images').textContent=data.counts.active||0;$('count-blurry').textContent=data.blurry;$('count-moved').textContent=data.counts.moved||0;$('count-errors').textContent=data.counts.error||0;$('results-errors-count').textContent=data.counts.error||0;
  const selected=$('root').value;$('root').replaceChildren(new Option('Current scan',''));data.roots.forEach(root=>$('root').add(new Option(root,root)));$('root').value=selected;
}
async function load(){
  const generation=++state.generation;state.loading=true;selectionChanged();
  try{
  if(state.scanId===null && ['groups','images','errors'].includes(state.view)){showBlank();return;}
  const params=new URLSearchParams({offset:state.page*pageSize(),limit:pageSize()});
  if(state.scanId!==null)params.set('scan_id',state.scanId);
  if($('root').value)params.set('root',$('root').value);
  if(state.view!=='errors'&&mediaFilter('orientation')?.value)params.set('orientation',mediaFilter('orientation').value);
  if($('media-type').value)params.set('media_type',$('media-type').value);
  params.set('sort',mediaFilter('sort').value||'name');
  const container=document.createDocumentFragment();
  let total=0;const pageItems=new Map();let groups=[];
  if(state.view==='groups'){
    if(mediaFilter('kind').value)params.set('kind',mediaFilter('kind').value);
    const data=await api(`/api/groups?${params}`);total=data.total;groups=data.items;groups.forEach(g=>g.members.filter(selectable).forEach(r=>pageItems.set(r.id,r)));
    data.items.forEach(group=>{const section=el('article',undefined,'group');const heading=el('div',undefined,'group-heading');const text=el('div');text.append(el('h3',`${group.members.length} files to compare`),el('p',group.kind==='near'?(group.members[0].media_type==='audio'?'Possible same recording: local fingerprints of up to 120 seconds match the anchor. Listen before choosing.':group.members[0].media_type==='video'?'Similar duration and three matching frame samples. Audio and unsampled scenes may differ.':'Each matches the group anchor; members may differ from each other.'):'Identical file hashes. Choose the copies you want to move.'));heading.append(text,el('span',group.kind==='exact'?'Exact copies':'Possible duplicates',`badge ${group.kind}`));section.append(heading);const cards=el('div',undefined,'cards');group.members.forEach(image=>{const item=card(image,group.recommendation,group.members);if(group.evidence?.[image.id])item.querySelector('.meta').append(el('p',`${(group.evidence[image.id]*100).toFixed(1)}% fingerprint bit agreement with anchor · not a probability`,'details'));cards.append(item);});section.append(cards);container.append(section);});
    if(!total)container.append(empty('A clearer view starts here','Scan a folder to find matching media. If you’ve already scanned, no groups match these filters.'));
  }else if(['images','errors'].includes(state.view)){
    if(state.view==='images'&&!state.settings.capabilities?.review_priority)throw new Error('The server is running an older version. Restart Vault Purge, reload this page, and choose Show last scan. Your saved scans are kept.');
    const status=state.view==='errors'?'error':(mediaFilter('status').value||'all');params.set('status',status==='suspect'?'error':status);if(status==='suspect')params.set('integrity','suspect');params.set('blurry',state.view==='images'&&(mediaFilter('blurry')?.checked||false));
    if(state.view==='images')params.set('review_first','true');
    const data=await api(`/api/images?${params}`);total=data.total;const grid=el('div',undefined,'cards');data.items.forEach(image=>{if(selectable(image))pageItems.set(image.id,image);grid.append(card(image));});container.append(grid);
    if(!total)container.append(state.view==='errors'?empty('No scan errors in this view','Errors from the current scan appear here. Try another media type or scanned folder.'):empty('No media in this view','Choose another filter or scan a folder to add media.'));
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
    params.set('paginated','true');
    const data=await api(`/api/moves?${params}`);total=data.total;
    data.items.forEach(move=>{
      const row=el('article',undefined,'history-row');
      row.append(el('strong',`Move #${move.id} · ${move.state}`),el('p',move.original),el('p',`→ ${move.destination}`));
      if(move.error)row.append(el('p',move.error,'error-detail'));
      const reveal=el('button','Show in folder','secondary');
      reveal.onclick=run(()=>api(`/api/moves/${move.id}/reveal?target=${move.state==='restored'?'original':'destination'}`,{method:'POST'}));row.append(reveal);
      if(move.state==='moved'){
        pageItems.set(move.id,move);makeSelectable(row,move);
        const label=el('label',undefined,'check'),box=el('input');box.type='checkbox';box.setAttribute('aria-label',`Select ${move.original} for restore`);
        box.onchange=()=>toggleSelection(move);label.append(box,el('span','Select for restore'));row.prepend(label);
        const button=el('button','Restore original','secondary');button.disabled=state.settings.dry_run||state.busy;
        button.onclick=run(()=>restoreMoves([move]));row.append(button);
      }
      container.append(row);
    });
    if(!data.items.length)container.append(empty('Your moves will appear here','Completed moves can be restored here. Disable preview-only mode to restore.'));
  }
  if(generation!==state.generation)return;
  if(state.page>0&&state.page*pageSize()>=total){state.page=Math.max(0,Math.ceil(total/pageSize())-1);return load();}
  const scope=`${state.view}:${params}`;const changed=state.selectionScope!==scope;
  state.selectionScope=scope;state.pageItems=pageItems;
  if(changed){state.selected.clear();state.historySelected.clear();}
  const selected=selection();for(const id of selected.keys()){if(!pageItems.has(id))selected.delete(id);else selected.set(id,pageItems.get(id));}
  if(changed&&state.view==='groups'&&state.preselect)for(const id of preselectedIds(groups))selected.set(id,pageItems.get(id));
  state.total=total;$('results').replaceChildren(container);$('result-count').textContent=state.view==='history'?`${total} recorded file operations`:state.view==='scans'?`${total} scans`:`${total} ${state.view==='groups'?(total===1?'group':'groups'):(total===1?'file':'files')}${state.view==='images'?' · errors and duplicates first':''}`;
  $('page').textContent=`Page ${state.page+1} of ${Math.max(1,Math.ceil(total/pageSize()))}`;$('prev').disabled=state.page===0;$('next').disabled=(state.page+1)*pageSize()>=total;selectionChanged();
  }catch(error){
    if(generation===state.generation){state.selected.clear();state.historySelected.clear();state.pageItems.clear();state.selectionScope=null;$('results').replaceChildren(empty('Results unavailable',error.message));}
    throw error;
  }finally{if(generation===state.generation){state.loading=false;selectionChanged();}}
}
function setLayout(layout){
  state.layout=layout;
  try{localStorage.setItem('vaultpurge_layout',layout);}catch(_){}
  $('layout-grid').classList.toggle('active',layout==='grid');
  $('layout-list').classList.toggle('active',layout==='list');
  $('results').classList.toggle('list-mode',layout==='list');
}
async function refresh(){await refreshSummary();await load();}
function setView(view){
  state.view=view;state.page=0;if(resultViews[view])state.reviewView=view;
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.view===view||(b.dataset.view==='review'&&!!resultViews[view])));
  $('title').textContent={groups:'Duplicate groups',images:'Your media library',errors:'Scan errors',history:'Move history',scans:'Scan history'}[view];
  syncMediaControls();const history=['history','scans'].includes(view);
  for(const id of ['root','media-type','sort'])$(id).disabled=history;
  $('clear-scan-history').hidden=view!=='scans';$('layout-toggle').hidden=history;$('result-tabs').hidden=history;
  $('results').setAttribute('role',history?'region':'tabpanel');
  for(const [tabView,id] of Object.entries(resultViews)){
    $(id).setAttribute('aria-selected',String(view===tabView));$(id).tabIndex=view===tabView?0:-1;
  }
  if(resultViews[view])$('results').setAttribute('aria-labelledby',resultViews[view]);
  return load();
}
document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',run(()=>setView(b.dataset.view==='review'?(state.reviewView||'groups'):b.dataset.view))));
const tabViews=Object.keys(resultViews);
for(const [view,id] of Object.entries(resultViews)){
  $(id).onclick=run(()=>setView(view));
  $(id).addEventListener('keydown',run(async event=>{
    const index=tabViews.indexOf(view);let next;
    if(event.key==='ArrowRight')next=tabViews[(index+1)%tabViews.length];
    if(event.key==='ArrowLeft')next=tabViews[(index+tabViews.length-1)%tabViews.length];
    if(event.key==='Home')next=tabViews[0];if(event.key==='End')next=tabViews.at(-1);
    if(next){event.preventDefault();$(resultViews[next]).focus();await setView(next);}
  }));
}
['root','media-type'].forEach(id=>$(id).addEventListener('change',run(async()=>{state.page=0;syncMediaControls();await load();})));
for(const type of mediaTypes){
  for(const name of filterNames){const control=mediaFilter(name,type);if(control)control.addEventListener('change',run(async()=>{state.page=0;await load();}));}
  $(`filters-${type||'all'}`).addEventListener('toggle',run(async event=>{
    if(!event.target.open||$('media-type').disabled||$('media-type').value===type)return;
    $('media-type').value=type;state.page=0;syncMediaControls();await load();
  }));
}
$('layout-grid').onclick=()=>setLayout('grid');$('layout-list').onclick=()=>setLayout('list');
$('prev').onclick=run(async()=>{state.page--;await load();});$('next').onclick=run(async()=>{state.page++;await load();});
$('clear').onclick=()=>{selection().clear();selectionChanged();};
$('select-all').onclick=()=>{state.pageItems.forEach((item,id)=>selection().set(id,item));selectionChanged();};
$('preselect').onchange=run(async()=>{state.preselect=$('preselect').checked;state.selectionScope=null;await load();});
$('restore-selected').onclick=run(()=>restoreMoves([...state.historySelected.values()]));
async function restoreMoves(moves){
  if(state.busy||!moves.length||!confirm(`Restore ${moves.length} file(s) to their original paths?`))return;
  state.busy=true;selectionChanged();
  try{for(const move of moves){const result=await api(`/api/moves/${move.id}/restore`,{method:'POST',body:JSON.stringify({token:'',confirm:true})});if(result.state==='attention')throw new Error(result.error);}}
  finally{state.busy=false;state.historySelected.clear();await refresh();}
}
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>$(button.dataset.close).close());
$('settings-open').onclick=()=>{const s=state.settings;$('dry-run').checked=s.dry_run;$('recommend').checked=s.show_recommendation;$('threshold').value=s.phash_threshold;$('blur-threshold').value=s.blur_threshold;$('video-threshold').value=s.video_phash_threshold??s.phash_threshold;$('video-blur-threshold').value=s.video_blur_threshold??s.blur_threshold;$('settings-dialog').showModal();};
$('settings-form').onsubmit=run(async event=>{event.preventDefault();state.settings=await api('/api/settings',{method:'PUT',body:JSON.stringify({dry_run:$('dry-run').checked,show_recommendation:$('recommend').checked,phash_threshold:Number($('threshold').value),blur_threshold:Number($('blur-threshold').value),video_phash_threshold:Number($('video-threshold').value),video_blur_threshold:Number($('video-blur-threshold').value)})});$('mode').textContent=state.settings.dry_run?'Preview only':'Moves enabled';$('settings-dialog').close();state.selectionScope=null;await refresh();});
function scanActivity(active){
  $('scan-progress').hidden=!active;$('scan-button').disabled=active;
  $('scan-form').setAttribute('aria-busy',String(active));
}
function scanStatusText(job){
  const stats=job.stats||{}, elapsed=Math.floor(job.elapsed||0);
  if(stats.stage==='discovery'||(job.state==='running'&&stats.stage!=='processing'))return `${job.state==='error'?'Scan stopped':'Finding files'} · found ${stats.found||0} files · ${elapsed}s elapsed`;
  const total=stats.total??stats.found??0,done=stats.processed??((stats.cached||0)+(stats.analyzed||0)+(stats.errors||0));
  const percent=total?Math.floor(100*Math.min(done,total)/total):100;
  // Estimate analysis time from work performed, excluding instant cache hits.
  const measured=done-(stats.cached||0),remaining=total-done;
  const seconds=measured>0&&remaining>0?Math.ceil(elapsed*remaining/measured):null;
  const eta=seconds===null?'':` · ~${seconds>=60?Math.ceil(seconds/60)+'m':seconds+'s'} left`;
  return `${job.state==='running'?'Scanning':job.state==='error'?'Scan stopped':'Scan complete'} · ${done.toLocaleString()} / ${total.toLocaleString()} · ${percent}% · ${elapsed}s elapsed${eta} · ${stats.cached||0} cached · ${stats.errors||0} errors`;
}
let lastScanAnnouncement=0;
function announceScan(text,force=false){
  const now=Date.now();if(force||now-lastScanAnnouncement>=1500){$('scan-state').textContent=text;lastScanAnnouncement=now;}
}
function resetMediaFilters(){
  $('media-type').value='';$('root').value='';
  for(const type of mediaTypes)for(const name of filterNames){
    const control=mediaFilter(name,type);if(!control)continue;
    if(name==='blurry')control.checked=false;
    else control.value=name==='status'?'all':name==='sort'?'name':'';
  }
  syncMediaControls();
}
async function showScanResults(job){
  resetMediaFilters();state.selectionScope=null;
  await refreshSummary();await setView('groups');
  if(!state.total){
    const stats=job.stats||{};
    await setView(stats.errors>0?'errors':'images');
  }
  $('result-label').scrollIntoView({block:'start'});
}
async function pollScan(){
  let job;
  try{job=await api('/api/scan');}
  catch(error){announceScan('Connection interrupted · retrying scan status…');setTimeout(pollScan,1500);return;}
  state.busy=job.state==='running';scanActivity(state.busy);selectionChanged();
  if(job.scan_id!==null)state.scanId=job.scan_id;
  const text=scanStatusText(job);announceScan(text,!state.busy);
  if(state.busy){setTimeout(pollScan,750);return;}
  if(job.state==='error')message(job.error);
  else{announceScan('Preparing results…',true);scanActivity(true);}
  try{if(job.state==='complete')await showScanResults(job);else await refresh();announceScan(text,true);}
  catch(error){announceScan('Scan finished · results could not load',true);message(error.message);}
  finally{scanActivity(false);}
}
$('scan-form').onsubmit=run(async event=>{
  event.preventDefault();if(state.busy)return;state.busy=true;scanActivity(true);selectionChanged();$('scan-state').textContent='Starting scan…';
  try{await api('/api/scan',{method:'POST',body:JSON.stringify({path:$('folder').value,recursive:$('recursive').checked,classify_only:$('classify').checked,force:$('force').checked})});resetScanView();await setView('groups');await pollScan();}
  catch(error){state.busy=false;scanActivity(false);selectionChanged();$('scan-state').textContent='Scan could not start';throw error;}
});
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
$('confirm-move').onclick=async()=>{if(!state.preview||!$('allow-move').checked)return;try{$('confirm-move').disabled=true;const result=await api('/api/move',{method:'POST',body:JSON.stringify({token:state.preview.token,confirm:true,allow_move:$('allow-move').checked})});state.selected.clear();state.preview=null;state.selectionScope=null;$('move-dialog').close();await refresh();const failed=result.items.find(m=>m.state==='attention');if(failed)message(`Operation stopped: ${failed.error}. Inspect the paths in move history.`);}catch(error){if($('move-dialog').open)$('preview-note').textContent=error.message;else message(error.message);}};
run(async()=>{state.settings=await api('/api/settings');$('destination').value=state.settings.dest_folder;$('mode').textContent=state.settings.dry_run?'Preview only':'Moves enabled';setLayout(state.layout);syncMediaControls();showBlank();})();

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
  ['count-images','count-blurry','count-moved','count-errors','results-errors-count'].forEach(id=>$(id).textContent='0');
  $('root').replaceChildren(new Option('Current scan',''));
}
function showBlank(){
  state.total=0;state.pageItems.clear();state.selected.clear();state.historySelected.clear();state.selectionScope=null;resetSummary();$('results').replaceChildren(empty('Ready for a new scan','Choose a target directory and click Scan folder. Previous results are available in Scan history.'));
  $('result-count').textContent='';$('page').textContent='';$('prev').disabled=true;$('next').disabled=true;selectionChanged();
}
function resetScanView(){
  state.scanId=null;state.page=0;state.generation++;state.selected.clear();state.historySelected.clear();state.pageItems.clear();state.selectionScope=null;state.preview=null;
  resetMediaFilters();
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

let playerGeneration=0, currentMedia=null;
function openPlayer(media){
  playerGeneration++;currentMedia=media;$('player-title').textContent=media.path.split(/[\\/]/).pop();
  const player=el(media.media_type==='video'?'video':'audio');player.controls=true;player.setAttribute('aria-label','Media player');player.preload='metadata';player.src=`/media/${media.id}`;
  player.onerror=()=>{$('player-status').textContent='This browser could not play the original. Prepare a compatible preview below.';};
  $('player-content').replaceChildren(player);$('player-status').textContent='Original file ready · press Play';$('convert-preview').disabled=false;$('player-progress').hidden=true;$('player-dialog').showModal();
}
$('player-dialog').addEventListener('close',()=>{playerGeneration++;const player=$('player-content').querySelector('video,audio');if(player){player.pause();player.removeAttribute('src');player.load();}$('player-content').replaceChildren();});
$('convert-preview').onclick=run(async()=>{
  const generation=playerGeneration, media=currentMedia;$('convert-preview').disabled=true;$('player-status').textContent='Preparing compatible preview…';$('player-progress').hidden=false;
  try{
    const result=await api(`/api/media/${media.id}/preview`,{method:'POST'});
    async function check(){
      if(generation!==playerGeneration)return;
      try{const status=await api(`/api/media/${media.id}/preview/${result.key}`);if(generation!==playerGeneration)return;
        if(status.state==='preparing'){setTimeout(check,1000);return;}
        if(status.state==='error')throw new Error(status.error);
        const player=$('player-content').querySelector('video,audio');player.src=status.url;$('player-status').textContent='Compatible preview ready · original unchanged';$('convert-preview').disabled=false;$('player-progress').hidden=true;
      }catch(error){if(generation===playerGeneration){$('player-status').textContent=error.message;$('convert-preview').disabled=false;$('player-progress').hidden=true;}}
    }
    await check();
  }catch(error){if(generation===playerGeneration){$('player-status').textContent=error.message;$('convert-preview').disabled=false;$('player-progress').hidden=true;}}
});

$('deep-compare').onclick=run(async()=>{
  await api('/api/compare',{method:'POST',body:JSON.stringify({ids:[...state.selected.keys()]})});
  state.busy=true;scanActivity(true);selectionChanged();$('compare-results').replaceChildren();$('compare-status').textContent='Comparing visual and audio segments…';$('compare-dialog').showModal();
  async function check(){
    let job;
    try{job=await api('/api/compare');}
    catch(error){$('compare-status').textContent='Connection interrupted · retrying comparison status…';setTimeout(check,1500);return;}
    if(job.state==='running'){setTimeout(check,1000);return;}
    state.busy=false;scanActivity(false);selectionChanged();
    if(job.state==='error'){$('compare-status').textContent=job.error;return;}
    $('compare-status').textContent='Comparison complete · evidence for manual review';
    const result=job.result;
    result.files.forEach((file,i)=>$('compare-results').append(el('p',`${i===0?'A':'B'}: ${file.path}`)));
    for(const kind of ['video','audio']){
      const evidence=result[kind];$('compare-results').append(el('h3',`${kind==='video'?'Visual':'Audio'} overlap`),el('p',`${(evidence.left_coverage*100).toFixed(1)}% of A · ${(evidence.right_coverage*100).toFixed(1)}% of B`));
      if(!evidence.ranges.length)$('compare-results').append(el('p','No sustained match found in the analyzed portion.'));
      evidence.ranges.forEach(r=>$('compare-results').append(el('p',`A ${r.left_start}–${r.left_end}s ↔ B ${r.right_start}–${r.right_end}s`)));
    }
    result.notes.forEach(note=>$('compare-results').append(el('p',note,'details')));
  }
  await check();
});
