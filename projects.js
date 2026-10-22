// Portable projects keep original assets, the editable recipe and the canvas view.
async function projectResponse(response){const value=await response.json();if(!response.ok)throw Error(value.error||'Project operation failed.');return value;}
function projectSize(bytes){return bytes<1024*1024?(bytes/1024).toFixed(1)+' KB':(bytes/1024/1024).toFixed(1)+' MB';}
$('#projectSave').onclick=async()=>{
  const button=$('#projectSave'),status=$('#projectStatus');button.disabled=true;status.textContent='Saving project…';
  try{
    finishHistory();await exportFolderReady;await saveExportFolder();
    const request={...JSON.parse(body()),snapshot:editSnapshot(),view:copy(canvasView),template:copy(st.template),kind:$('#projectKind').value};
    const value=await projectResponse(await fetch('/project/save',{method:'POST',body:JSON.stringify(request)}));
    status.textContent=`${value.name} · ${projectSize(value.bytes)} · saved to ${value.path}`;
  }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
};
$('#projectOpen').onclick=()=>$('#projectFile').click();
async function openProject(file){
  const status=$('#projectStatus'),button=$('#projectOpen');button.disabled=true;status.textContent='Opening project…';
  try{
    const value=await projectResponse(await fetch('/project/open',{method:'POST',body:file}));
    const snapshot={...value.snapshot,template:value.template,view:value.view};
    editAction(()=>restoreEdit(snapshot));status.textContent=`${file.name} · ${projectSize(file.size)} · ready to edit`;
  }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
}
$('#projectFile').onchange=event=>{const file=event.target.files[0];event.target.value='';if(file)openProject(file);};
$('#settingsTextCurrent').onclick=()=>{
  const request=JSON.parse(body()),parameters={...request.p};
  for(const key of ['unit','grid_visible','stencil_id'])delete parameters[key];
  $('#settingsText').value=JSON.stringify({format:'morphaic settings',schema_version:1,parameters,units:st.unit,guides:{grid_visible:st.grid},portion_linework:request.lines,luminosity:request.luminosity},null,2);
  $('#settingsTextStatus').textContent='Current recipe copied into the editor.';
};
$('#settingsTextApply').onclick=async()=>{
  const status=$('#settingsTextStatus'),button=$('#settingsTextApply');button.disabled=true;
  try{
    const value=await projectResponse(await fetch('/settings/parse',{method:'POST',body:JSON.stringify({text:$('#settingsText').value,current:JSON.parse(body())})}));
    const snapshot=editSnapshot(),p=value.p;
    for(const key of Object.keys(snapshot.P))if(key in p)snapshot.P[key]=copy(p[key]);
    for(const section of ['map','cut'])for(const key of Object.keys(snapshot.settings[section]))if(key in p)snapshot.settings[section][key]=copy(p[key]);
    for(const key of ['w','h','dpi','bg','seed'])if(key in p)snapshot.settings[key]=p[key];
    if(value.unit!==undefined)snapshot.settings.unit=value.unit;
    if(value.grid_visible!==undefined)snapshot.settings.grid=value.grid_visible;
    if(value.lines!==undefined)snapshot.lines=value.lines;
    if(value.luminosity)snapshot.settings.lum=copy(value.luminosity);
    const document=JSON.parse($('#settingsText').value),changed=document.format==='morphaic settings'?(document.parameters||{}):document;
    if(Object.hasOwn(changed,'pts'))snapshot.strokes=p.pts.length?[copy(p.pts)]:[];
    if(Object.hasOwn(changed,'curve'))snapshot.cpts=Array.from({length:17},(_,i)=>{const x=Math.round(i*255/16);return [x/255,p.curve[x]/255];});
    editAction(()=>restoreEdit(snapshot));status.textContent='Settings applied. Undo restores the previous image.';
  }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
};
