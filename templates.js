// Templates are session imports. No default document or frame assignments.
st.template={id:'',name:'',frames:[],mapping:{},fit:'contain',title:''};
$('#fmt').add(new Option('InDesign','indesign'));
$('#fmt').parentElement.insertAdjacentHTML('afterend',`<section id="templatePanel" hidden aria-label="InDesign template">
  <div class="row"><strong>InDesign template</strong><button id="templateImport">import file</button></div>
  <input id="templateFile" type="file" accept=".indd,.indt,.idml" hidden>
  <p id="templateName" class="note">No template selected</p>
  <p id="templateStatus" class="note" role="status">Uses Adobe InDesign on Windows to fill a copy of your template.</p>
  <div id="templateAssignments"></div>
  <div class="row"><label for="templateFit">image fit</label><select id="templateFit"><option value="contain">fit entire image</option><option value="cover">fill frame</option></select></div>
  <div class="row"><label for="templateTitle">drawing title</label><input id="templateTitle" placeholder="Morphaic drawing" maxlength="200"></div>
  <p class="note">Labeled frames choose their drawings automatically. Assign any remaining frames below. Export includes INDD, IDML and PDF.</p>
</section>`);
function templateChoices(){return [['','keep template content'],['collage','finished collage'],['initial','initial drawing'],['migration','migration drawing'],['final','final drawing'],['map','layered migration map'],...st.files.map((f,i)=>['source:'+(i+1),'source '+(i+1)+' · '+f.name])];}
function templateAssignments(){
  const container=$('#templateAssignments');container.replaceChildren();
  for(const frame of st.template.frames){
    const row=document.createElement('label');row.className='template-frame';
    const label=document.createElement('span');label.textContent=`page ${frame.page} · ${frame.label||'frame '+(+frame.key+1)}`;
    const select=document.createElement('select');select.dataset.frame=frame.key;
    for(const [value,name] of templateChoices())select.add(new Option(name,value));
    select.value=st.template.mapping[frame.key]||'';
    select.onchange=()=>{st.template.mapping[frame.key]=select.value;};
    row.append(label,select);container.append(row);
  }
}
window.templateOutput=()=>{
  const active=st.fmt==='indesign'&&st.exportMode!=='3d';$('#templatePanel').hidden=!active;
  if(active){$('#go').textContent='export template';$('#px').textContent='template layout · INDD + IDML + PDF';$('#px').classList.remove('warn');}
};
$('#templateImport').onclick=()=>$('#templateFile').click();
$('#templateFile').onchange=async event=>{
  const file=event.target.files[0];event.target.value='';if(!file)return;
  if(file.size>150*1024*1024)return toast('Choose a template smaller than 150 MB.');
  const button=$('#templateImport');button.disabled=true;$('#templateStatus').textContent='Reading template in InDesign…';
  try {
    const response=await fetch('/indesign/template',{method:'POST',headers:{'X-Name':encodeURIComponent(file.name)},body:file});
    const data=await response.json();if(!response.ok)throw Error(data.error);
    const choices=new Set(templateChoices().map(([key])=>key)),mapping={};
    for(const frame of data.frames){const key=frame.label.trim().toLowerCase().replace(/^morphaic:/,'');mapping[frame.key]=choices.has(key)?key:'';}
    st.template={...st.template,...data,mapping};$('#templateName').textContent=data.name;
    templateAssignments();$('#templateStatus').textContent=`${data.frames.length} frames found · your original template stays unchanged`;
  }catch(error){$('#templateStatus').textContent=error.message;toast(error.message);}
  finally{button.disabled=false;}
};
$('#templateFit').onchange=event=>st.template.fit=event.target.value;
$('#templateTitle').oninput=event=>st.template.title=event.target.value;
window.templateExport=async()=>{
  if(!st.template.id)return toast('Import an InDesign template first.');
  if(!st.files.length)return toast('Add an image or PDF first.');
  if(!Object.values(st.template.mapping).some(Boolean))return toast('Assign a drawing to at least one template frame.');
  const button=$('#go');button.disabled=true;button.textContent='filling template…';
  try{
    await exportFolderReady;await saveExportFolder();
    const request=JSON.parse(body());request.template={template_id:st.template.id,mapping:st.template.mapping,fit:st.template.fit,title:st.template.title};
    const response=await fetch('/indesign/export',{method:'POST',body:JSON.stringify(request)});
    const result=await response.json();if(!response.ok)throw Error(result.error);toast('saved to '+result.path);
  }catch(error){toast(error.message);}finally{button.disabled=false;outUI();}
};
$('#fmt').addEventListener('change',()=>{if(st.fmt==='indesign')templateAssignments();});
fetch('/indesign/status').then(r=>r.json()).then(result=>{if(!result.available)$('#templateStatus').textContent='Template export requires Adobe InDesign installed on Windows.';}).catch(()=>{});
templateOutput();
