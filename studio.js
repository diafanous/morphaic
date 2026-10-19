// Local, offline tools: cut stencils, a craft-knife playground, and a WebGL relief viewer.
const SHAPE_NAMES = ['rectangle','ellipse','triangle','diamond','hexagon','star','heart','custom'];
const SHAPE_COLORS = ['#9fbdd4','#a9c4b3','#d9a4a7','#b4bddd','#bfd4ca','#bca18b','#cc9386','#d7c8ae'];
st.exportMode = '2d'; st.lumFmt = 'stl';
st.cut = {cut_shape:'rectangle',multi_shape:false,shape_weights:Object.fromEntries(SHAPE_NAMES.map(n=>[n,n==='rectangle'?100:0])),shape_locks:{},custom_shape:[],stencil_name:'',stencil_id:''};
st.lum = {source:'collage',source_id:'',source_name:'',source_aspect:1,width_mm:100,height_mm:100,relief_mm:10,base_mm:2,spacing_mm:.5,gamma:1,contrast:1,smooth_mm:0,invert:false,encoding:'binary'};
Object.assign(st.lum,{cleat:false,include_wall_cleat:true,hardware:'screws',cleat_height_mm:14,cleat_depth_mm:5,cleat_width:.8,cleat_gap_mm:.3,pin_diameter_mm:1,screw_sixteenths:3,hole_clearance_mm:.3,hollow_back:false,shell_mm:1});
st.map.node_by_shape = false;
st.map.node_end_shapes = {rectangle:'square',ellipse:'ring',triangle:'arrow',diamond:'cut',hexagon:'cut',star:'cut',heart:'cut',custom:'cut'};
let lastCutCounts = {}, lumTimer, lumVersion = 0, lumRequest = false, lumQueued = false;
const lumControls = {};
const mmText=value=>+Number(value).toFixed(3);
let savedStencils = [];
function studioLinkSize(axis='width', value=st.lum.width_mm) {
  const aspect=st.h>0&&st.w>0?st.h/st.w:11/8.5;
  const size=StudioMath.dimensions(value,axis,aspect);if(size)Object.assign(st.lum,size);
  const unitScale=UN[st.unit]/25.4;
  if(document.activeElement!==$('#lumWidth'))$('#lumWidth').value=+(st.lum.width_mm*unitScale).toFixed(4);
  if(document.activeElement!==$('#lumHeight'))$('#lumHeight').value=+(st.lum.height_mm*unitScale).toFixed(4);
  document.querySelectorAll('.lum-size-unit').forEach(el=>el.textContent=st.unit);
}
for(const [id,axis] of [['#lumWidth','width'],['#lumHeight','height']]) {
  $(id).oninput=()=>{const value=$(id).valueAsNumber;if(value>0){studioLinkSize(axis,value*25.4/UN[st.unit]);outUI();studioSchedule();}};
  $(id).onchange=()=>{studioLinkSize();$(id).blur();studioLinkSize();};
}
function syncShares() {
  document.querySelectorAll('[data-shape-share]').forEach(el=>{const name=el.dataset.shapeShare,value=st.cut.shape_weights[name];el.value=value;el.style.setProperty('--p',value+'%');el.disabled=Boolean(st.cut.shape_locks?.[name])||name==='custom'&&!st.cut.custom_shape.length;});
  document.querySelectorAll('[data-shape-lock]').forEach(el=>{const name=el.dataset.shapeLock,locked=Boolean(st.cut.shape_locks?.[name]);el.setAttribute('aria-pressed',String(locked));el.setAttribute('aria-label',(locked?'unlock ':'lock ')+name+' percentage');el.title=(locked?'unlock ':'lock ')+name+' percentage';el.disabled=name==='custom'&&!st.cut.custom_shape.length;});
}
function setShapeShare(name,value) {
  st.cut.shape_weights=StudioMath.shares(st.cut.shape_weights,name,value,SHAPE_NAMES.filter(n=>n!=='custom'||st.cut.custom_shape.length),st.cut.shape_locks);syncShares();studioCounts({});
}
function stencilOptions() {
  const menu=$('#stencilLibrary');menu.replaceChildren();
  if(!savedStencils.length){const empty=document.createElement('div');empty.className='note';empty.textContent='no saved stencils yet';menu.append(empty);}
  for(const stencil of savedStencils){const button=document.createElement('button');button.textContent=stencil.name;button.setAttribute('role','menuitemradio');button.setAttribute('aria-checked',String(stencil.id===st.cut.stencil_id));button.onclick=()=>useSavedStencil(stencil);menu.append(button);}
}
function stencilMenu(open,focus=false){
  const menu=$('#stencilLibrary');menu.hidden=!open;$('#stencilLibraryToggle').setAttribute('aria-expanded',String(open));
  if(open){menu.style.top='calc(100% + 8px)';menu.style.bottom='auto';if(menu.getBoundingClientRect().bottom>$('#sideScroll').getBoundingClientRect().bottom-8){menu.style.top='auto';menu.style.bottom='calc(100% + 8px)';}if(focus)menu.querySelector('button')?.focus();}
}
$('#stencilLibraryToggle').onclick=()=>stencilMenu($('#stencilLibrary').hidden);
$('#stencilLibraryToggle').onkeydown=e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();stencilMenu(true,true);if(e.key==='ArrowUp')$('#stencilLibrary button:last-child')?.focus();}};
$('#stencilLibrary').onkeydown=e=>{const buttons=[...$('#stencilLibrary').querySelectorAll('button')],i=buttons.indexOf(document.activeElement);if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();}};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#stencilLibrary').hidden){e.preventDefault();stencilMenu(false);$('#stencilLibraryToggle').focus();}});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('.stencil-library-wrap'))stencilMenu(false);});
$('.stencil-library-wrap').addEventListener('focusout',()=>queueMicrotask(()=>{if(!$('.stencil-library-wrap').contains(document.activeElement))stencilMenu(false);}));
$('#cutDisclosure').addEventListener('toggle',()=>{if(!$('#cutDisclosure').open)stencilMenu(false);});
const stencilsReady=fetch('/stencils').then(async r=>{const data=await r.json();if(!r.ok)throw new Error(data.error);savedStencils=data.stencils;stencilOptions();}).catch(e=>toast('stencil library: '+e.message));
async function saveCurrentStencil(button) {
  const name=$('#stencilName').value.trim();button.disabled=true;
  try {
    await stencilsReady;
    const points=knifeSealed?fittedStencil(knifeSealed):st.cut.custom_shape,id=knifeSealed?knifeSavedId:st.cut.stencil_id;
    const r=await fetch('/stencils',{method:'POST',body:JSON.stringify({id,name,points})}),result=await r.json();if(!r.ok)throw new Error(result.error);
    if(knifeSealed)knifeSavedId=result.stencil.id;
    if(!knifeSealed||knifeApplied){st.cut.stencil_id=result.stencil.id;st.cut.stencil_name=result.stencil.name;}
    savedStencils=savedStencils.filter(s=>s.id!==result.stencil.id);savedStencils.push(result.stencil);stencilOptions();
    $('#stencilLibraryStatus').textContent='saved for future sessions';toast('saved stencil: '+result.stencil.name);
  }catch(e){toast(e.message);}finally{button.disabled=false;}
}
$('#stencilSave').onclick=()=>saveCurrentStencil($('#stencilSave'));
function useSavedStencil(stencil){
  stencilMenu(false);beginHistory();
  Object.assign(st.cut,{custom_shape:copy(stencil.points),stencil_name:stencil.name,stencil_id:stencil.id,cut_shape:'custom'});
  if(st.cut.multi_shape)setShapeShare('custom',Math.max(25,st.cut.shape_weights.custom));studioSync();draw(false);finishHistory();
  $('#stencilLibraryToggle').focus();
}

function studioSync() {
  $('#cutShape').value=st.cut.cut_shape; $('#multiShape').setAttribute('aria-pressed',String(st.cut.multi_shape));
  $('#shapeMix').hidden=!st.cut.multi_shape; $('#cutShape').disabled=st.cut.multi_shape;
  document.querySelectorAll('[data-shape-share]').forEach(el=>{el.value=st.cut.shape_weights[el.dataset.shapeShare]; el.disabled=el.dataset.shapeShare==='custom'&&!st.cut.custom_shape.length;});
  $('#cutShape option[value=custom]').disabled=!st.cut.custom_shape.length;
  syncShares();
  $('#stencilSave').disabled=!st.cut.custom_shape.length&&!knifeSealed;if(!$('#knifeDialog').open)$('#stencilName').value=st.cut.stencil_name||'';stencilOptions();
  $('#nodeByShape').checked=st.map.node_by_shape; $('#shapeNodes').hidden=!st.map.node_by_shape;
  document.querySelectorAll('[data-shape-node]').forEach(el=>el.value=st.map.node_end_shapes[el.dataset.shapeNode]||st.map.node_end);
  st.lum.source='collage';
  $('#stlEncoding').value=st.lum.encoding; $('#lumInvert').checked=st.lum.invert;
  for (const [key,controls] of Object.entries(lumControls)) { controls.r.value=st.lum[key]; controls.n.value=st.lum[key]; controls.fill(); }
  studioLinkSize();mountingSync();studioCounts(lastCutCounts);studioOutput();studioSchedule();
}

function studioMeshEstimate(p=st.lum,format=st.lumFmt){
  const nx=Math.ceil(p.width_mm/p.spacing_mm)+1,ny=Math.ceil(p.height_mm/p.spacing_mm)+1;
  let vertices=nx*ny+2*nx+2*ny-3,triangles=2*vertices-4;
  // Allow for mounting geometry; text and Rhino encoding sizes are approximate.
  if(p.cleat){vertices+=1024;triangles+=2048;}
  const fileBytes=format==='3dm'?4096+24*vertices+16*triangles:
    p.encoding==='ascii'?64+280*triangles:84+50*triangles;
  return {fileBytes};
}
function studioBytes(value){return value>=1024**3?(value/1024**3).toFixed(2)+' GiB':(value/1024**2).toFixed(1)+' MiB';}
function studioOutput() {
  const three=st.exportMode==='3d', lum=three||st.fmt.startsWith('lum-');
  $('#output2d').hidden=three; $('#output3d').hidden=!three; $('#lumControls').hidden=!lum; $('#dpiRow').hidden=three;
  document.querySelectorAll('#exportMode button').forEach(b=>b.classList.toggle('on',b.dataset.mode===st.exportMode));
  document.querySelectorAll('#lum3d button').forEach(b=>b.classList.toggle('on',b.dataset.format===st.lumFmt));
  $('#stlEncodingRow').hidden=st.lumFmt!=='stl';
  document.querySelectorAll('[data-model-only]').forEach(el=>el.hidden=!three);
  if (!lum) return;
  const p=st.lum,estimate=studioMeshEstimate(p);
  const w=Math.max(1,Math.round(p.width_mm/25.4*st.dpi)),h=Math.max(1,Math.round(p.height_mm/25.4*st.dpi));
  $('#px').textContent=three ? `estimated size: ${studioBytes(estimate.fileBytes)}`
    : `${w} × ${h} px · grayscale luminosity · ${(w*h/1e6).toFixed(1)} MP${w*h>16e6?' · over the 16 MP limit':''}`;
  $('#px').classList.toggle('warn',!three&&w*h>16e6);
  $('#go').textContent=three?'export '+st.lumFmt:'export map '+st.fmt.slice(4);
}

async function studioExport() {
  if (!st.files.length) return toast('add an image or PDF to the canvas first');
  const b=$('#go'); b.disabled=true; b.textContent='building…';
  try {
    await exportFolderReady; await saveExportFolder();
    const format=st.exportMode==='3d'?st.lumFmt:st.fmt.slice(4);
    const r=await fetch('/luminosity/export/'+format,{method:'POST',body:body()});
    const result=await r.json(); if (!r.ok) throw new Error(result.error);
    toast('saved to '+result.path);
  } catch(e) { toast(e.message); }
  finally { b.disabled=false; outUI(); }
}

$('#exportMode').onclick=e=>{if(!e.target.dataset.mode)return; st.exportMode=e.target.dataset.mode; outUI();};
$('#lum3d').onclick=e=>{if(!e.target.dataset.format)return;st.lumFmt=e.target.dataset.format;outUI();};
$('#stlEncoding').onchange=e=>{st.lum.encoding=e.target.value;outUI();};
const LUM_SLIDERS = [['relief_mm','relief depth (mm)',0,100,.1,10,true],['base_mm','base thickness (mm)',.1,50,.1,2,true],
  ['spacing_mm','quality / mesh spacing (mm)',.01,20,.01,.5,true],['gamma','luminosity gamma',.2,5,.05,1],
  ['contrast','luminosity contrast',.1,4,.05,1],['smooth_mm','smoothing radius (mm)',0,10,.05,0]];
for (const [key,label,min,max,step,def,modelOnly] of LUM_SLIDERS) {
  const row=document.createElement('div');row.className='sl';if(modelOnly)row.dataset.modelOnly='';
  row.innerHTML=`<label for="lum-${key}">${label}</label><input class="val" type="number" min="${min}" max="${max}" step="${step}" aria-label="${label} value"><input id="lum-${key}" type="range" min="${min}" max="${max}" step="${step}" aria-label="${label}">`;
  const r=row.querySelector('[type=range]'),n=row.querySelector('[type=number]');
  const fill=()=>r.style.setProperty('--p',(st.lum[key]-min)/(max-min)*100+'%');
  const set=value=>{if(!Number.isFinite(value))return;st.lum[key]=Math.min(max,Math.max(min,value));r.value=st.lum[key];n.value=st.lum[key];fill();outUI();studioSchedule();};
  r.oninput=()=>set(+r.value);
  n.oninput=()=>{const value=n.valueAsNumber;if(Number.isFinite(value)&&value>=min&&value<=max){st.lum[key]=value;r.value=value;fill();outUI();studioSchedule();}};
  n.onchange=()=>set(+n.value);r.ondblclick=()=>set(def);
  lumControls[key]={r,n,fill};$('#lumSliders').append(row);
}
$('#lumInvert').onchange=e=>{st.lum.invert=e.target.checked;studioSchedule();};
const MOUNT_INPUTS={cleatEnabled:'cleat',includeWallCleat:'include_wall_cleat',hollowBack:'hollow_back',
  cleatHardware:'hardware',screwSize:'screw_sixteenths',pinDiameter:'pin_diameter_mm',holeClearance:'hole_clearance_mm',
  cleatHeight:'cleat_height_mm',cleatDepth:'cleat_depth_mm',cleatGap:'cleat_gap_mm',shellThickness:'shell_mm'};
let showCleatPreview=true;
function mountingSync() {
  for(const [id,key] of Object.entries(MOUNT_INPUTS)) {const el=$('#'+id);if(el.type==='checkbox')el.checked=st.lum[key];else if(document.activeElement!==el)el.value=st.lum[key];}
  $('#cleatOptions').hidden=!st.lum.cleat;$('#screwControl').hidden=st.lum.hardware!=='screws';$('#pinControl').hidden=st.lum.hardware==='screws';$('#shellControl').hidden=!st.lum.hollow_back;
  $('#screwSizeValue').textContent=`${st.lum.screw_sixteenths}/16 in · ${(st.lum.screw_sixteenths*25.4/16).toFixed(2)} mm`;
  $('#screwSize').style.setProperty('--p',(st.lum.screw_sixteenths-1)/7*100+'%');
  $('#showCleatPreview').checked=showCleatPreview;
}
$('#showCleatPreview').onchange=e=>{showCleatPreview=e.target.checked;lumVersion++;clearTimeout(lumTimer);updateRelief();};
for(const [id,key] of Object.entries(MOUNT_INPUTS)) {
  const el=$('#'+id);el.oninput=el.onchange=()=>{if(el.type==='number'&&!el.validity.valid)return;
    st.lum[key]=el.type==='checkbox'?el.checked:el.tagName==='SELECT'?el.value:+el.value;
    mountingSync();studioSchedule();outUI();
  };
}

// Percentages stay at exactly 100%; the filled chart records actual cut counts.
for(const [i,name] of SHAPE_NAMES.entries()) {
  const option=document.createElement('option');option.value=name;option.textContent=name;$('#cutShape').append(option);
  const row=document.createElement('div');row.className='row';
  row.innerHTML=`<label style="width:80px" for="share-${name}"><i class="swatch" style="background:${SHAPE_COLORS[i]}"></i>${name}</label><input id="share-${name}" type="range" min="0" max="100" step="1" data-shape-share="${name}" aria-label="${name} share"><input type="number" min="0" max="100" step="1" data-shape-share="${name}" aria-label="${name} share value"><button class="share-lock" data-shape-lock="${name}" aria-label="lock ${name} percentage" aria-pressed="false"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="5" y="10" width="14" height="11" rx="2"/><path class="lock-open" d="M9 10V6a4 4 0 0 1 8 0"/><path class="lock-closed" d="M8 10V6a4 4 0 0 1 8 0v4"/></svg></button>`;
  row.querySelector('button').onclick=()=>{beginHistory();st.cut.shape_locks??={};st.cut.shape_locks[name]=!st.cut.shape_locks[name];syncShares();finishHistory();};
  const [range,num]=row.querySelectorAll('input');
  const set=value=>{setShapeShare(name,value);draw(true);};
  range.oninput=()=>set(+range.value);range.onchange=()=>draw(false);num.oninput=num.onchange=()=>set(+num.value);
  $('#shapeShares').append(row);
  const node=document.createElement('div');node.className='row';
  node.innerHTML=`<label class="grow" for="node-${name}">${name}</label><select id="node-${name}" data-shape-node="${name}" aria-label="${name} end node"><option value="none">none</option><option value="dot">dot</option><option value="ring">ring</option><option value="square">square</option><option value="plus">plus (+)</option><option value="arrow">arrow</option><option value="cut">cut shape</option></select>`;
  node.querySelector('select').onchange=e=>{st.map.node_end_shapes[name]=e.target.value;draw(false);};$('#shapeNodes').append(node);
}
$('#cutShape').onchange=e=>{st.cut.cut_shape=e.target.value;draw(false);};
$('#multiShape').onclick=()=>editAction(()=>{st.cut.multi_shape=!st.cut.multi_shape;studioSync();draw(false);});
$('#nodeByShape').onchange=e=>{st.map.node_by_shape=e.target.checked;studioSync();draw(false);};
function studioCounts(counts) {
  lastCutCounts=counts;let total=Object.values(counts).reduce((a,b)=>a+b,0);
  const actual=total>0, values=actual?counts:st.cut.shape_weights;
  $('#cutTotalText').textContent=(actual?total:0).toLocaleString()+' total cuts';
  if(!actual)total=Object.values(values).reduce((a,b)=>a+b,0)||1;
  const c=$('#shapeChart').getContext('2d');c.clearRect(0,0,512,512);let angle=-Math.PI/2;
  $('#shapeLegend').replaceChildren();
  for(const [i,name] of SHAPE_NAMES.entries()) {
    const count=values[name]||0;if(!count)continue;const slice=count/total*2*Math.PI;
    c.beginPath();c.moveTo(256,256);c.arc(256,256,242,angle,angle+slice);c.closePath();c.fillStyle=SHAPE_COLORS[i];c.fill();angle+=slice;
    const row=document.createElement('div');row.innerHTML=`<span><i class="swatch" style="background:${SHAPE_COLORS[i]}"></i>${name}</span><span>${(count/total*100).toFixed(1)}%</span>`;$('#shapeLegend').append(row);
  }
  $('#shapeChart').setAttribute('aria-label',actual?`${total} cuts: ${SHAPE_NAMES.filter(n=>values[n]).map(n=>`${n} ${(values[n]/total*100).toFixed(1)} percent`).join(', ')}`:'relative cut shape shares');
}

// Debounced, serialized mesh requests. Stale replies are discarded.
function studioSchedule() {
  lumVersion++;clearTimeout(lumTimer);
  if(!$('#reliefDialog').open||!$('#reliefLive').checked)return;
  lumTimer=setTimeout(updateRelief,220);
}
async function updateRelief() {
  if(!$('#reliefDialog').open)return;
  if(lumRequest){lumQueued=true;return;}
  lumRequest=true;const version=lumVersion;$('#reliefStatus').textContent='building preview…';
  try {
    const request=JSON.parse(body());request.luminosity.cleat=Boolean(request.luminosity.cleat&&showCleatPreview);
    const r=await fetch('/luminosity/preview',{method:'POST',body:JSON.stringify(request)});const result=await r.json();
    if(!r.ok)throw new Error(result.error);
    if(version===lumVersion){reliefSet(result);$('#reliefStatus').textContent=`${mmText(result.width_mm)} × ${mmText(result.height_mm)} mm · ${result.faces.length.toLocaleString()} preview triangles`;}
  } catch(e){$('#reliefStatus').textContent=e.message;}
  finally{lumRequest=false;if(lumQueued){lumQueued=false;updateRelief();}}
}
$('#reliefOpen').onclick=()=>{if(!st.files.length)return toast('add an image or PDF to the canvas first');if(!$('#reliefDialog').open)$('#reliefDialog').show();viewerPosition();lumVersion++;updateRelief();};
$('#reliefClose').onclick=()=>$('#reliefDialog').close();
$('#reliefRefresh').onclick=()=>{lumVersion++;updateRelief();};
$('#reliefLive').onchange=studioSchedule;
let reliefGL, reliefProgram, reliefBuffer, reliefSize=0, orbit=[-.65,-.55], reliefZoom=1, reliefDrag=null;
const reliefCanvas=$('#reliefCanvas');
function initRelief() {
  reliefGL=reliefCanvas.getContext('webgl',{antialias:true});
  if(!reliefGL)throw new Error('this viewer needs WebGL; model exports remain available');
  const g=reliefGL;
  const shader=(type,text)=>{const s=g.createShader(type);g.shaderSource(s,text);g.compileShader(s);if(!g.getShaderParameter(s,g.COMPILE_STATUS))throw new Error(g.getShaderInfoLog(s));return s;};
  const vs=shader(g.VERTEX_SHADER,`attribute vec3 position;attribute vec3 normal;uniform vec2 orbit;uniform vec2 scale;varying vec3 litNormal;varying float height;
    vec3 turn(vec3 p){float c=cos(orbit.x),s=sin(orbit.x);p=vec3(c*p.x-s*p.y,s*p.x+c*p.y,p.z);c=cos(orbit.y);s=sin(orbit.y);return vec3(p.x,c*p.y-s*p.z,s*p.y+c*p.z);}
    void main(){vec3 p=turn(position);litNormal=turn(normal);height=position.z;gl_Position=vec4(p.xy*scale,-p.z*.25,1.);}`);
  const fs=shader(g.FRAGMENT_SHADER,`precision mediump float;varying vec3 litNormal;varying float height;void main(){vec3 n=normalize(litNormal);if(!gl_FrontFacing)n=-n;float light=.25+.75*max(0.,dot(n,normalize(vec3(-.4,.5,1.))));vec3 color=mix(vec3(.48),vec3(.83),clamp(height+0.5,0.,1.));gl_FragColor=vec4(color*light,1.);}`);
  reliefProgram=g.createProgram();g.attachShader(reliefProgram,vs);g.attachShader(reliefProgram,fs);g.linkProgram(reliefProgram);
  if(!g.getProgramParameter(reliefProgram,g.LINK_STATUS))throw new Error(g.getProgramInfoLog(reliefProgram));
  reliefBuffer=g.createBuffer();g.enable(g.DEPTH_TEST);
}
function reliefSet(model) {
  if(!reliefGL)initRelief();const g=reliefGL,bounds=model.bounds||[[0,0,0],[model.width_mm,model.height_mm,model.depth_mm]],center=bounds[0].map((v,i)=>(v+bounds[1][i])/2),max=Math.max(...bounds[0].map((v,i)=>bounds[1][i]-v)),data=[];
  for(const face of model.faces) {
    const [a,b,c]=face.map(i=>model.vertices[i]);const u=b.map((x,i)=>x-a[i]),v=c.map((x,i)=>x-a[i]);
    const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],len=Math.hypot(...n)||1;
    for(const vertex of [a,b,c])data.push(...vertex.map((v,i)=>(v-center[i])/max),...n.map(x=>x/len));
  }
  reliefSize=data.length/6;g.bindBuffer(g.ARRAY_BUFFER,reliefBuffer);g.bufferData(g.ARRAY_BUFFER,new Float32Array(data),g.STATIC_DRAW);reliefDraw();
}
function reliefDraw() {
  if(!reliefGL||!$('#reliefDialog').open)return;const g=reliefGL,c=reliefCanvas;
  c.width=Math.round(c.clientWidth*devicePixelRatio);c.height=Math.round(c.clientHeight*devicePixelRatio);g.viewport(0,0,c.width,c.height);
  g.clearColor(.08,.08,.08,1);g.clear(g.COLOR_BUFFER_BIT|g.DEPTH_BUFFER_BIT);g.useProgram(reliefProgram);g.bindBuffer(g.ARRAY_BUFFER,reliefBuffer);
  for(const [name,offset] of [['position',0],['normal',12]]){const a=g.getAttribLocation(reliefProgram,name);g.enableVertexAttribArray(a);g.vertexAttribPointer(a,3,g.FLOAT,false,24,offset);}
  g.uniform2f(g.getUniformLocation(reliefProgram,'orbit'),...orbit);
  const aspect=c.width/c.height;g.uniform2f(g.getUniformLocation(reliefProgram,'scale'),1.5*reliefZoom/Math.max(1,aspect),1.5*reliefZoom*Math.min(1,aspect));g.drawArrays(g.TRIANGLES,0,reliefSize);
}
reliefCanvas.onpointerdown=e=>{reliefDrag=[e.clientX,e.clientY];reliefCanvas.setPointerCapture(e.pointerId);};
reliefCanvas.onpointermove=e=>{if(!reliefDrag)return;orbit[0]+=(e.clientX-reliefDrag[0])*.008;orbit[1]+=(e.clientY-reliefDrag[1])*.008;reliefDrag=[e.clientX,e.clientY];reliefDraw();};
reliefCanvas.onpointerup=reliefCanvas.onpointercancel=()=>reliefDrag=null;
reliefCanvas.onwheel=e=>{e.preventDefault();reliefZoom=Math.min(5,Math.max(.25,reliefZoom*Math.exp(-e.deltaY*.001)));reliefDraw();};
$('#reliefReset').onclick=()=>{orbit=[-.65,-.55];reliefZoom=1;reliefDraw();};
$('#reliefBack').onclick=()=>{orbit=[-.65,Math.PI-.55];reliefZoom=1;reliefDraw();};
const viewerTitlebar=$('#reliefTitlebar'),viewerMoveHandle=$('#reliefMoveHandle');
let viewerDrag=null;
function viewerPosition(left,top) {
  const dialog=$('#reliefDialog');if(!dialog.open)return;
  const rect=dialog.getBoundingClientRect(),position=StudioMath.viewerPosition(left??rect.left,top??rect.top,rect.width,rect.height,innerWidth,innerHeight);
  dialog.style.left=position.left+'px';dialog.style.top=position.top+'px';
}
viewerTitlebar.onpointerdown=e=>{if(e.button!==0||e.target.closest('button'))return;const rect=$('#reliefDialog').getBoundingClientRect();viewerDrag={id:e.pointerId,x:e.clientX-rect.left,y:e.clientY-rect.top};viewerTitlebar.setPointerCapture(e.pointerId);e.preventDefault();};
viewerTitlebar.onpointermove=e=>{if(viewerDrag?.id===e.pointerId)viewerPosition(e.clientX-viewerDrag.x,e.clientY-viewerDrag.y);};
viewerTitlebar.onpointerup=viewerTitlebar.onpointercancel=()=>viewerDrag=null;
viewerMoveHandle.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const rect=$('#reliefDialog').getBoundingClientRect(),step=e.shiftKey?36:12;viewerPosition(rect.left+(e.key==='ArrowLeft'?-step:e.key==='ArrowRight'?step:0),rect.top+(e.key==='ArrowUp'?-step:e.key==='ArrowDown'?step:0));};
addEventListener('resize',()=>{viewerPosition();reliefDraw();});

// Knife playground. The path is normalized to a reusable stencil when lifted.
const mat=$('#knifeCanvas'),matCtx=mat.getContext('2d'),sheet={x:0,y:0,w:1000,h:650};
const knifeDialog=$('#knifeDialog');
$('#frame').append(mat);mat.hidden=true;
// Keep the mat on the canvas so controls and the document remain in context.
$('#stage').append(knifeDialog);knifeDialog.setAttribute('aria-modal','false');
$('#knifeOpen').setAttribute('aria-controls','knifeDialog');$('#knifeOpen').setAttribute('aria-expanded','false');
function knifeSize(){
  if(!knifeDialog.open)return;
  const frame=$('#frame');if(!frame.clientWidth)return;
  mat.width=1000;mat.height=Math.max(1,Math.round(1000*frame.clientHeight/frame.clientWidth));
  Object.assign(sheet,{x:0,y:0,w:mat.width,h:mat.height});knifeRender();
}
new ResizeObserver(knifeSize).observe($('#frame'));
let knifeMode='free',knifeStrokes=[],knifeSealed=null,knifePointer=null,knifeDown=false,knifeShavings=[],knifeFrame=0,knifeSound=false,knifeAudio,knifeAudioAt=0,liftTime=0,knifeSavedId='',knifeApplied=false;
function knifeSnapshot(){return {strokes:knifeStrokes,sealed:knifeSealed,savedId:knifeSavedId,applied:knifeApplied,status:$('#knifeStatus').textContent};}
let knifeHistory=StudioMath.history(knifeSnapshot());
function knifeHistoryButtons(){$('#knifeUndo').disabled=!knifeHistory.canUndo;$('#knifeRedo').disabled=!knifeHistory.canRedo;}
function knifeCommit(){knifeHistory.record(knifeSnapshot());knifeHistoryButtons();}
function knifeRestore(state){
  if(!state)return;knifeStrokes=state.strokes;knifeSealed=state.sealed;knifeSavedId=state.savedId;knifeApplied=state.applied;knifeDown=false;knifeShavings=[];
  $('#knifeStatus').textContent=state.status;$('#knifeUse').disabled=!knifeSealed;$('#stencilSave').disabled=!knifeSealed&&!st.cut.custom_shape.length;
  liftTime=performance.now();knifeHistoryButtons();knifeRender();
}
function knifeFinishGesture(){if(knifeDown){knifeDown=false;knifeCommit();}}
function knifeUndoAction(){knifeFinishGesture();knifeRestore(knifeHistory.undo());}
function knifeRedoAction(){knifeFinishGesture();knifeRestore(knifeHistory.redo());}
function knifePath(){return knifeStrokes.flat();}
function knifeCoordinates(e){const r=mat.getBoundingClientRect();return [(e.clientX-r.left)*mat.width/r.width,(e.clientY-r.top)*mat.height/r.height];}
function onSheet([x,y]){return x>=sheet.x&&x<=sheet.x+sheet.w&&y>=sheet.y&&y<=sheet.y+sheet.h;}
function paperPoint([x,y]){return [(x-sheet.x)/sheet.w,(y-sheet.y)/sheet.h];}
function knifeTone() {
  if(!knifeSound||performance.now()-knifeAudioAt<80)return;knifeAudioAt=performance.now();
  try{knifeAudio??=new (window.AudioContext||window.webkitAudioContext)();if(knifeAudio.state==='suspended')knifeAudio.resume();
    const buffer=knifeAudio.createBuffer(1,Math.round(knifeAudio.sampleRate*.05),knifeAudio.sampleRate),channel=buffer.getChannelData(0);
    for(let i=0;i<channel.length;i++)channel[i]=(Math.random()*2-1)*(1-i/channel.length)*.04;
    const source=knifeAudio.createBufferSource();source.buffer=buffer;source.connect(knifeAudio.destination);source.start();
  }catch(e){knifeSound=false;knifeSoundSync();$('#knifeSound').title='Cutting sound unavailable';$('#knifeSound').disabled=true;}
}
function knifeSoundSync(){$('#knifeSound').setAttribute('aria-pressed',String(knifeSound));$('#knifeSound').title='Cutting sound '+(knifeSound?'on':'off');$('#knifeSoundWaves').toggleAttribute('hidden',!knifeSound);$('#knifeSoundMute').toggleAttribute('hidden',knifeSound);}
function knifePaint(now=performance.now()) {
  knifeFrame=0;if(!knifeDialog.open)return;const c=matCtx;c.clearRect(0,0,mat.width,mat.height);
  const pts=knifePath();
  if(pts.length){c.beginPath();c.moveTo(sheet.x+pts[0][0]*sheet.w,sheet.y+pts[0][1]*sheet.h);for(const [x,y]of pts.slice(1))c.lineTo(sheet.x+x*sheet.w,sheet.y+y*sheet.h);
    c.lineWidth=4;c.strokeStyle='#333';c.stroke();c.lineWidth=1.5;c.strokeStyle='#fff';c.stroke();
    const [x,y]=pts[0];c.beginPath();c.arc(sheet.x+x*sheet.w,sheet.y+y*sheet.h,9,0,Math.PI*2);c.strokeStyle='#fff';c.lineWidth=5;c.stroke();c.strokeStyle='#111';c.lineWidth=2;c.stroke();}
  if(knifeSealed){const lift=Math.min(1,(now-liftTime)/450);c.save();c.translate(0,-lift*15);c.beginPath();const first=knifeSealed[0];c.moveTo(sheet.x+first[0]*sheet.w,sheet.y+first[1]*sheet.h);for(const [x,y]of knifeSealed.slice(1))c.lineTo(sheet.x+x*sheet.w,sheet.y+y*sheet.h);c.closePath();
    c.fillStyle='#ffffff22';c.fill();c.lineWidth=4;c.strokeStyle='#111';c.stroke();c.lineWidth=1.5;c.strokeStyle='#fff';c.stroke();c.restore();}
  knifeShavings=knifeShavings.filter(p=>now-p.t<800);
  for(const p of knifeShavings){const age=(now-p.t)/800;c.save();c.globalAlpha=1-age;c.translate(p.x+p.vx*age,p.y+p.vy*age+40*age*age);c.rotate(p.r+age*3);c.fillStyle=p.color;c.fillRect(-2,-1,8,3);c.restore();}
  if(knifePointer){const [x,y]=knifePointer;c.save();c.translate(x,y);c.rotate(-.65);c.shadowColor='#0008';c.shadowBlur=7;c.shadowOffsetY=5;
    c.fillStyle='#ddd';c.beginPath();c.moveTo(0,0);c.lineTo(13,-30);c.lineTo(-4,-23);c.closePath();c.fill();c.shadowBlur=0;
    c.fillStyle='#eee';c.fillRect(-7,-112,18,83);c.fillStyle='#333';for(let i=0;i<5;i++)c.fillRect(-5,-101+i*12,14,4);c.fillStyle='#888';c.fillRect(-4,-43,12,7);c.restore();}
  if(knifeShavings.length||knifeSealed&&now-liftTime<450)knifeFrame=requestAnimationFrame(knifePaint);
}
function knifeRender(){if(!knifeFrame)knifeFrame=requestAnimationFrame(knifePaint);}
function knifeReset(){knifeFinishGesture();knifeStrokes=[];knifeSealed=null;knifeSavedId='';knifeApplied=false;knifeShavings=[];knifeDown=false;$('#knifeUse').disabled=true;$('#stencilSave').disabled=!st.cut.custom_shape.length;$('#knifeStatus').textContent='fresh sheet · start anywhere on the paper';knifeCommit();knifeRender();}
function knifeSetMode(mode){knifeMode=mode;$('#knifeFree').classList.toggle('on',mode==='free');$('#knifePrecision').classList.toggle('on',mode==='points');$('#knifeHelp').textContent=mode==='free'?'hold and drag to cut · return to the start ring to close your shape':'click to place each corner · click the start ring or seal & lift to finish';}
$('#knifeOpen').onclick=()=>{if(!st.files.length)return toast('add an image or PDF to cut on the canvas');if(!knifeDialog.open)knifeDialog.show();mat.hidden=false;$('#stage').classList.add('cutting-active');$('#knifeOpen').setAttribute('aria-expanded','true');knifeSize();knifeRender();mat.focus({preventScroll:true});};
$('#knifeClose').onclick=()=>knifeDialog.close();
$('#knifeFree').onclick=()=>{knifeFinishGesture();knifeSetMode('free');};$('#knifePrecision').onclick=()=>{knifeFinishGesture();knifeSetMode('points');};
$('#knifeSound').onclick=()=>{knifeSound=!knifeSound;knifeSoundSync();};
$('#knifeNew').onclick=knifeReset;
$('#knifeUndo').onclick=knifeUndoAction;$('#knifeRedo').onclick=knifeRedoAction;
mat.onpointerdown=e=>{
  if(e.button!==0)return;
  const xy=knifeCoordinates(e);knifePointer=xy;if(!onSheet(xy)||knifeSealed)return;mat.setPointerCapture(e.pointerId);
  const point=paperPoint(xy),pts=knifePath();
  if(knifeMode==='points'&&pts.length>=3&&Math.hypot((point[0]-pts[0][0])*sheet.w,(point[1]-pts[0][1])*sheet.h)<18){knifeSeal();return;}
  knifeFinishGesture();knifeStrokes.push([point]);knifeDown=knifeMode==='free';knifeTone();$('#knifeStatus').textContent=knifeMode==='free'?'blade down · follow your line':'corner set · choose your next turn';if(knifeMode==='points')knifeCommit();knifeRender();
};
mat.onpointermove=e=>{
  const xy=knifeCoordinates(e);knifePointer=xy;
  if(knifeDown&&onSheet(xy)){
    const stroke=knifeStrokes.at(-1),point=paperPoint(xy),last=stroke.at(-1);
    if(Math.hypot((point[0]-last[0])*sheet.w,(point[1]-last[1])*sheet.h)>3){stroke.push(point);knifeTone();
      for(let i=0;i<2;i++)knifeShavings.push({x:xy[0],y:xy[1],vx:(Math.random()-.5)*90,vy:-Math.random()*65,r:Math.random()*6,t:performance.now(),color:'#ddd'});
    }
  }knifeRender();
};
mat.onpointerup=()=>{if(knifeDown){knifeDown=false;const pts=knifePath();if(pts.length>12&&Math.hypot((pts[0][0]-pts.at(-1)[0])*sheet.w,(pts[0][1]-pts.at(-1)[1])*sheet.h)<18)knifeSeal();else $('#knifeStatus').textContent='blade up · continue the outline or seal & lift';knifeCommit();}knifeRender();};
mat.onpointercancel=()=>{knifeFinishGesture();knifeRender();};
mat.onpointerleave=()=>{if(!knifeDown){knifePointer=null;knifeRender();}};
mat.onfocus=()=>{knifePointer??=[sheet.w/2,sheet.h/2];knifeRender();};
mat.onkeydown=e=>{
  if(e.key==='Escape'){e.preventDefault();knifeDialog.close();return;}
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown',' ','Enter'].includes(e.key)||knifeSealed)return;
  e.preventDefault();knifePointer??=[sheet.w/2,sheet.h/2];
  if(e.key==='Enter'){knifeFinishGesture();knifeSeal();return;}
  if(e.key===' '){
    if(knifeMode==='points')knifeStrokes.push([paperPoint(knifePointer)]);
    else{knifeDown=!knifeDown;if(knifeDown)knifeStrokes.push([paperPoint(knifePointer)]);}
    knifeTone();$('#knifeStatus').textContent=knifeMode==='points'?'corner set · move to your next turn':knifeDown?'blade down · arrows guide the cut':'blade up · seal & lift when ready';if(!knifeDown)knifeCommit();
  }else{
    const step=e.shiftKey?5:20;
    knifePointer[0]=Math.max(sheet.x,Math.min(sheet.x+sheet.w,knifePointer[0]+(e.key==='ArrowLeft'?-step:e.key==='ArrowRight'?step:0)));
    knifePointer[1]=Math.max(sheet.y,Math.min(sheet.y+sheet.h,knifePointer[1]+(e.key==='ArrowUp'?-step:e.key==='ArrowDown'?step:0)));
    if(knifeDown){knifeStrokes.at(-1).push(paperPoint(knifePointer));knifeTone();}
  }knifeRender();
};
knifeDialog.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();if($('#knifeSettings').open){$('#knifeSettings').open=false;$('#knifeSettings summary').focus();}else knifeDialog.close();}});
knifeDialog.addEventListener('close',()=>{knifeFinishGesture();cancelAnimationFrame(knifeFrame);knifeFrame=0;mat.hidden=true;$('#stage').classList.remove('cutting-active');$('#knifeSettings').open=false;$('#knifeOpen').setAttribute('aria-expanded','false');$('#knifeOpen').focus({preventScroll:true});});
function simplified(points,tolerance=.002) {
  if(points.length<=2)return points;const a=points[0],b=points.at(-1),dx=b[0]-a[0],dy=b[1]-a[1],length=dx*dx+dy*dy;let best=0,index=0;
  for(let i=1;i<points.length-1;i++){const p=points[i],t=length?Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length)):0,d=Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy);if(d>best){best=d;index=i;}}
  return best>tolerance?[...simplified(points.slice(0,index+1),tolerance).slice(0,-1),...simplified(points.slice(index),tolerance)]:[a,b];
}
function crossing(a,b,c,d){const cross=(u,v,w)=>(v[0]-u[0])*(w[1]-u[1])-(v[1]-u[1])*(w[0]-u[0]);return cross(a,b,c)*cross(a,b,d)<-1e-12&&cross(c,d,a)*cross(c,d,b)<-1e-12;}
function knifeSeal(){
  knifeFinishGesture();
  const pts=simplified(knifePath()).filter((p,i,a)=>!i||Math.hypot(p[0]-a[i-1][0],p[1]-a[i-1][1])>.001);
  if(pts.length>3&&Math.hypot(pts[0][0]-pts.at(-1)[0],pts[0][1]-pts.at(-1)[1])<.015)pts.pop();
  if(pts.length<3){$('#knifeStatus').textContent='give your stencil at least three corners';return;}
  const area=Math.abs(pts.reduce((s,p,i)=>{const q=pts[(i+1)%pts.length];return s+p[0]*q[1]-q[0]*p[1];},0)/2);
  if(area<.005){$('#knifeStatus').textContent='that sliver needs a little more paper · try a wider cut';return;}
  for(let i=0;i<pts.length;i++)for(let j=i+2;j<pts.length;j++){if(i===0&&j===pts.length-1)continue;if(crossing(pts[i],pts[(i+1)%pts.length],pts[j],pts[(j+1)%pts.length])){$('#knifeStatus').textContent='your cuts cross · undo a stroke and leave one clear outline';return;}}
  if(pts.length>512){$('#knifeStatus').textContent='too many tiny edges · try a smoother outline';return;}
  knifeSealed=pts;knifeSavedId='';knifeApplied=false;liftTime=performance.now();$('#knifeUse').disabled=false;$('#stencilSave').disabled=false;$('#knifeStatus').textContent=`clean lift! · ${Math.round(area*100)}% of the sheet · stencil ready`;
  for(let i=0;i<36;i++)knifeShavings.push({x:500,y:325,vx:(Math.random()-.5)*450,vy:-Math.random()*250,r:Math.random()*6,t:liftTime,color:['#fff','#ddd','#aaa'][i%3]});knifeCommit();knifeRender();
}
$('#knifeSeal').onclick=knifeSeal;
function fittedStencil(points){const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),x=Math.min(...xs),y=Math.min(...ys),w=Math.max(...xs)-x,h=Math.max(...ys)-y;return points.map(([px,py])=>[+((px-x)/w).toFixed(5),+((py-y)/h).toFixed(5)]);}
$('#knifeUse').onclick=async()=>{
  if(!knifeSealed)return;beginHistory();st.cut.custom_shape=fittedStencil(knifeSealed);knifeApplied=true;
  st.cut.cut_shape='custom';st.cut.stencil_name=$('#stencilName').value.trim()||'Untitled stencil';st.cut.stencil_id=knifeSavedId;if(st.cut.multi_shape)setShapeShare('custom',Math.max(25,st.cut.shape_weights.custom));
  studioSync();draw(false);finishHistory();$('#knifeDialog').close();toast('stencil lifted · your custom cut is now in the collage');
  if($('#knifeSaveLibrary').checked)await saveCurrentStencil($('#stencilSave'));
};
studioSync();
// Initial values are captured after linked sizing has settled; global reset can
// restore these without removing sources or touching the saved-stencil library.
window.studioDefaults=copy({cut:st.cut,lum:st.lum,exportMode:st.exportMode,lumFmt:st.lumFmt,
  map:{node_by_shape:st.map.node_by_shape,node_end_shapes:st.map.node_end_shapes}});
window.studioReset=function(){
  if(knifeDialog.open)knifeDialog.close();if($('#reliefDialog').open)$('#reliefDialog').close();
  const defaults=copy(window.studioDefaults);
  st.cut=defaults.cut;st.lum=defaults.lum;st.exportMode=defaults.exportMode;st.lumFmt=defaults.lumFmt;Object.assign(st.map,defaults.map);
  clearTimeout(lumTimer);lumVersion++;lumQueued=false;lastCutCounts={};
  showCleatPreview=true;orbit=[-.65,-.55];reliefZoom=1;reliefDrag=null;viewerDrag=null;
  $('#reliefDialog').style.left='';$('#reliefDialog').style.top='';$('#reliefLive').checked=true;$('#reliefStatus').textContent='';
  $('#cleatOptions').open=false;$('#knifeSettings').open=false;$('#knifeSaveLibrary').checked=false;$('#stencilLibraryStatus').textContent='';stencilMenu(false);
  knifeStrokes=[];knifeSealed=null;knifePointer=null;knifeDown=false;knifeShavings=[];knifeSavedId='';knifeApplied=false;
  knifeSound=false;knifeSoundSync();knifeSetMode('free');$('#knifeStatus').textContent='fresh sheet · start anywhere on the paper';
  $('#knifeUse').disabled=true;$('#stencilName').value='';knifeHistory=StudioMath.history(knifeSnapshot());knifeHistoryButtons();
  studioSync();
};
