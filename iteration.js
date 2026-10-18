// Local v0.2.1 test controls. Source bytes stay in the session store for undo.
P.grain_source_id = '';
P.grain_source_name = '';
P.gradient_stops = [{position:0,color:'#000000'},{position:1,color:'#ffffff'}];
const iterationDefaults = copy(editSnapshot());
$('#panelTitle').title = 'morphaic v0.2.1 test';

function editAction(action) {
  finishHistory(); beginHistory(true);
  try { action(); } finally { finishHistory(); }
}
function removeSources(id) {
  editAction(() => { st.files = id ? st.files.filter(f => f.id !== id) : []; after(); });
  toast(id ? 'image removed · undo to restore' : 'attached images removed · undo to restore');
}
function neutralSources() {
  return st.files.map(f => ({...f,w:f.original_w || f.w,page:1,edited:false}));
}
function resetCanvas() {
  if(window.canvasViewFit)canvasViewFit();
  editAction(() => {
    const snapshot = editSnapshot(), first = st.files[0];
    snapshot.P = copy(iterationDefaults.P);
    Object.assign(snapshot.settings, {cut:copy(iterationDefaults.settings.cut),bg:iterationDefaults.settings.bg,
      seed:1,grid:false,inkOn:false,touched:false,w:first?.w || 0,h:first ? first.w*first.aspect : 0});
    snapshot.strokes = []; snapshot.cpts = [[0,0],[1,1]];
    restoreEdit(snapshot);
  });
  toast('canvas reset · undo to restore');
}
function resetAllSettings() {
  if(window.canvasViewFit)canvasViewFit();
  editAction(() => {
    const snapshot = copy(iterationDefaults);
    snapshot.files = neutralSources();
    const first = snapshot.files[0];
    snapshot.settings.w = first?.w || 0; snapshot.settings.h = first ? first.w*first.aspect : 0;
    if (window.studioReset) studioReset();
    restoreEdit(snapshot);
  });
  toast('all settings reset · undo to restore');
}

document.body.insertAdjacentHTML('beforeend', `<dialog id="resetDialog" aria-labelledby="resetTitle">
  <h2 id="resetTitle">Reset all settings?</h2>
  <p>Restore the original image sizes, neutral canvas, colors, cut shapes and export settings. Attached images stay available. You can undo this reset.</p>
  <div class="row"><label><input type="checkbox" id="skipResetWarning">don't show me this again</label></div>
  <footer><button id="cancelReset">cancel</button><button id="confirmReset">reset all</button></footer>
</dialog>
<div id="canvasMenu" role="menu" aria-label="canvas actions" hidden>
  <button role="menuitem" id="canvasReset">reset canvas</button>
  <button role="menuitem" id="canvasRemove">remove attached images</button>
  <button role="menuitem" id="canvasExport">quick export</button>
</div>`);
let skipResetWarning = false;
const preferencesReady = fetch('/preferences').then(async response => {
  if (!response.ok) throw new Error('could not load reset preference');
  skipResetWarning = Boolean((await response.json()).skip_reset_warning);
}).catch(() => {});
$('#resetAll').onclick = async () => {
  await preferencesReady;
  if (skipResetWarning) return resetAllSettings();
  $('#skipResetWarning').checked = false; $('#resetDialog').showModal(); $('#cancelReset').focus();
};
$('#cancelReset').onclick = () => $('#resetDialog').close();
$('#confirmReset').onclick = async () => {
  const skip = $('#skipResetWarning').checked;
  $('#resetDialog').close(); resetAllSettings();
  if (skip) {
    try {
      const response = await fetch('/preferences',{method:'POST',body:JSON.stringify({skip_reset_warning:true})});
      if (!response.ok) throw new Error('could not save reset preference');
      skipResetWarning = true;
    } catch (error) { toast(error.message); }
  }
};
const canvasMenu = $('#canvasMenu');
let canvasMenuReturnFocus;
function closeCanvasMenu(restoreFocus=false) {
  canvasMenu.hidden = true;
  if (restoreFocus) canvasMenuReturnFocus?.focus();
}
function openCanvasMenu(x,y) {
  canvasMenuReturnFocus = document.activeElement;
  $('#canvasRemove').disabled = !st.files.length;
  $('#canvasExport').disabled = $('#go').disabled || (!st.files.length && !(st.lum.source==='import' && st.lum.source_id) && st.fmt!=='txt');
  $('#canvasExport').textContent = 'quick export ' + (st.exportMode==='3d' ? st.lumFmt.toUpperCase() : st.fmt.replace('lum-','luminosity ').toUpperCase());
  canvasMenu.hidden = false;
  const bounds = canvasMenu.getBoundingClientRect();
  canvasMenu.style.left = Math.max(8,Math.min(x,innerWidth-bounds.width-8))+'px';
  canvasMenu.style.top = Math.max(8,Math.min(y,innerHeight-bounds.height-8))+'px';
  $('#canvasReset').focus();
}
$('#stage').tabIndex = 0;
$('#stage').setAttribute('aria-label','collage canvas; right click for canvas actions');
$('#stage').addEventListener('contextmenu', event => {
  if (event.target.closest('#knifeDialog,#knifeCanvas,button,input')) return;
  event.preventDefault(); openCanvasMenu(event.clientX,event.clientY);
});
$('#stage').addEventListener('keydown', event => {
  if (event.target.closest('#knifeDialog,#knifeCanvas')) return;
  if (event.key==='ContextMenu' || (event.shiftKey && event.key==='F10')) {
    event.preventDefault();const box=$('#stage').getBoundingClientRect();openCanvasMenu(box.left+box.width/2,box.top+box.height/2);
  }
});
$('#canvasReset').onclick = () => {closeCanvasMenu(true);resetCanvas();};
$('#canvasRemove').onclick = () => {closeCanvasMenu(true);removeSources();};
$('#canvasExport').onclick = () => {closeCanvasMenu(true);$('#go').click();};
canvasMenu.onkeydown = event => {
  const buttons = [...canvasMenu.querySelectorAll('button:not(:disabled)')], i=buttons.indexOf(document.activeElement);
  if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
    event.preventDefault();buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(i+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();
  } else if (event.key==='Escape' || event.key==='Tab') {closeCanvasMenu(true);if(event.key==='Escape')event.preventDefault();}
};
document.addEventListener('pointerdown',event=>{if(!canvasMenu.hidden&&!canvasMenu.contains(event.target))closeCanvasMenu();});
addEventListener('resize',()=>closeCanvasMenu());
document.addEventListener('scroll',()=>closeCanvasMenu(),true);

const gradientPresets = {
  mono:[{position:0,color:'#000000'},{position:1,color:'#ffffff'}],
  sepia:[{position:0,color:'#21190f'},{position:.5,color:'#987451'},{position:1,color:'#fff3d8'}],
  duotone:[{position:0,color:'#162d55'},{position:1,color:'#ffe5b0'}],
  sunset:[{position:0,color:'#291943'},{position:.55,color:'#e57a45'},{position:1,color:'#fff1cd'}]
};
function gradientPaint() {
  const stops = [...P.gradient_stops].sort((a,b)=>a.position-b.position);
  $('#gradientPreview').style.background = `linear-gradient(to right,${stops.map(stop=>`${stop.color} ${stop.position*100}%`).join(',')})`;
}
function effectsSync() {
  $('#grainName').textContent = P.grain_source_name || 'generated monochrome grain';
  $('#grainClear').hidden = !P.grain_source_id;
  $('#gradientPreset').value = 'custom';
  const parent = $('#gradientStops'); parent.replaceChildren();
  P.gradient_stops ||= copy(gradientPresets.mono);
  P.gradient_stops.forEach((stop,index) => {
    const row = document.createElement('div'); row.className='gradient-stop';
    row.innerHTML=`<input type="color" aria-label="color stop ${index+1}" value="${stop.color}"><input type="range" aria-label="position stop ${index+1}" min="0" max="100" step="1" value="${Math.round(stop.position*100)}"><input type="number" aria-label="position stop ${index+1} percent" min="0" max="100" step="1" value="${Math.round(stop.position*100)}"><span>%</span><button aria-label="remove color stop ${index+1}" title="remove color stop" ${P.gradient_stops.length<=2?'disabled':''}>×</button>`;
    const [color,range,num]=row.querySelectorAll('input');
    const setPosition=value=>{if(!Number.isFinite(value))return;stop.position=Math.max(0,Math.min(100,value))/100;range.value=num.value=Math.round(stop.position*100);gradientPaint();draw(true);};
    color.oninput=()=>{stop.color=color.value;gradientPaint();draw(true);};color.onchange=()=>draw(false);
    range.oninput=()=>setPosition(range.valueAsNumber);range.onchange=()=>draw(false);
    num.oninput=()=>setPosition(num.valueAsNumber);num.onchange=()=>draw(false);
    row.querySelector('button').onclick=()=>editAction(()=>{P.gradient_stops.splice(index,1);effectsSync();draw(false);});
    parent.append(row);
  });
  $('#gradientAdd').disabled=P.gradient_stops.length>=16;
  gradientPaint();
}
$('#gradientPreset').onchange=event=>{
  const preset=gradientPresets[event.target.value]; if(!preset)return;
  editAction(()=>{P.gradient_stops=copy(preset);effectsSync();draw(false);});
};
$('#gradientAdd').onclick=()=>editAction(()=>{
  if(P.gradient_stops.length>=16)return;
  const sorted=[...P.gradient_stops].sort((a,b)=>a.position-b.position);
  let start=0,end=1,gap=-1;
  for(let i=1;i<sorted.length;i++){const span=sorted[i].position-sorted[i-1].position;if(span>gap){gap=span;start=sorted[i-1].position;end=sorted[i].position;}}
  P.gradient_stops.push({position:(start+end)/2,color:'#808080'});P.gradient_stops.sort((a,b)=>a.position-b.position);effectsSync();draw(false);
});
$('#gradientReverse').onclick=()=>editAction(()=>{P.gradient_stops=P.gradient_stops.map(stop=>({...stop,position:1-stop.position})).sort((a,b)=>a.position-b.position);effectsSync();draw(false);});
$('#grainImport').onclick=()=>$('#grainFile').click();
$('#grainFile').onchange=async event=>{
  const file=event.target.files[0];event.target.value='';if(!file)return;
  $('#grainImport').disabled=true;
  try {
    const response=await fetch('/source',{method:'POST',headers:{'X-Name':encodeURIComponent(file.name)},body:file});
    const source=await response.json();if(!response.ok)throw new Error(source.error);
    if(source.pdf)throw new Error('choose an image for the grain texture');
    editAction(()=>{P.grain_source_id=source.id;P.grain_source_name=source.name;effectsSync();draw(false);});
  } catch(error){toast(error.message);} finally{$('#grainImport').disabled=false;}
};
$('#grainClear').onclick=()=>editAction(()=>{P.grain_source_id='';P.grain_source_name='';effectsSync();draw(false);});
effectsSync();
