// View navigation only: transforms never change the collage or export size.
window.canvasView={zoom:1,x:0,y:0};
const viewStage=$('#stage'),viewFrame=$('#frame');
viewStage.tabIndex=0;viewStage.addEventListener('pointerdown',event=>{if(!event.target.closest('button,input,select,dialog,#knifeCanvas'))viewStage.focus({preventScroll:true});});
viewStage.insertAdjacentHTML('beforeend',`<div id="viewNavigation" aria-label="canvas view controls"><button id="viewZoomOut" aria-label="zoom out">−</button><output id="viewZoom" aria-label="zoom percentage">100%</output><button id="viewZoomIn" aria-label="zoom in">+</button><button id="viewFit">fit</button></div>`);
let viewRenderTimer,viewPan=null,viewSpace=false;
function canvasViewApply(){
  const v=canvasView;viewFrame.style.transform=`translate(${v.x}px,${v.y}px) scale(${v.zoom})`;
  document.documentElement.style.setProperty('--grid-size',`${Math.max(5,25*v.zoom)}px`);
  document.documentElement.style.setProperty('--grid-x',`${v.x+viewStage.offsetLeft}px`);document.documentElement.style.setProperty('--grid-y',`${v.y+viewStage.offsetTop}px`);
  $('#viewZoom').value=Math.round(v.zoom*100)+'%';
}
function canvasViewFit(){Object.assign(canvasView,{zoom:1,x:0,y:0});canvasViewApply();viewRenderSoon();}
function viewRenderSoon(){clearTimeout(viewRenderTimer);viewRenderTimer=setTimeout(()=>draw(false),180);}
function canvasZoom(factor,clientX,clientY){
  const rect=viewStage.getBoundingClientRect(),v=canvasView;
  const px=(clientX??rect.left+rect.width/2)-rect.left-rect.width/2,py=(clientY??rect.top+rect.height/2)-rect.top-rect.height/2;
  const next=Math.max(.1,Math.min(16,v.zoom*factor)),ratio=next/v.zoom;
  v.x=px-(px-v.x)*ratio;v.y=py-(py-v.y)*ratio;v.zoom=next;canvasViewApply();viewRenderSoon();
}
$('#viewZoomOut').onclick=()=>canvasZoom(1/1.25);$('#viewZoomIn').onclick=()=>canvasZoom(1.25);$('#viewFit').onclick=canvasViewFit;
viewStage.addEventListener('wheel',event=>{
  if(event.target.closest('#knifeTopbar,footer,#viewNavigation,input,select,.knife-menu-panel'))return;
  event.preventDefault();const delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?viewStage.clientHeight:1);
  if(event.shiftKey){canvasView.x-=(delta||event.deltaX);canvasViewApply();}
  else if(event.altKey){canvasView.y-=delta;canvasView.x-=event.deltaX;canvasViewApply();}
  else canvasZoom(Math.exp(-Math.max(-300,Math.min(300,delta))*.002),event.clientX,event.clientY);
},{passive:false});
document.addEventListener('keydown',event=>{
  if(typingTarget(event.target)||event.target.closest('dialog:not(#knifeDialog)'))return;
  if(event.code==='Space'&&viewStage.contains(event.target)&&event.target.id!=='knifeCanvas'){viewSpace=true;event.preventDefault();viewStage.classList.add('view-hand');}
  if(!viewStage.contains(event.target)||event.target.id==='knifeCanvas')return;
  if(event.key==='0'&&(event.ctrlKey||event.metaKey)){event.preventDefault();canvasViewFit();}
  else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){
    event.preventDefault();const step=event.shiftKey?100:30;
    canvasView.x+=event.key==='ArrowLeft'?step:event.key==='ArrowRight'?-step:0;
    canvasView.y+=event.key==='ArrowUp'?step:event.key==='ArrowDown'?-step:0;canvasViewApply();
  }
});
document.addEventListener('keyup',event=>{if(event.code==='Space'){viewSpace=false;viewStage.classList.remove('view-hand');}});
addEventListener('blur',()=>{viewSpace=false;viewPan=null;viewStage.classList.remove('view-hand','view-panning');});
viewStage.addEventListener('pointerdown',event=>{
  if(event.button!==1&&!(event.button===0&&viewSpace))return;
  if(event.target.closest('button,input,select,summary'))return;
  event.preventDefault();event.stopImmediatePropagation();
  viewPan={id:event.pointerId,x:event.clientX,y:event.clientY};viewStage.setPointerCapture(event.pointerId);viewStage.classList.add('view-panning');
},true);
viewStage.addEventListener('pointermove',event=>{if(viewPan?.id!==event.pointerId)return;event.preventDefault();event.stopImmediatePropagation();canvasView.x+=event.clientX-viewPan.x;canvasView.y+=event.clientY-viewPan.y;viewPan.x=event.clientX;viewPan.y=event.clientY;canvasViewApply();},true);
function viewPanEnd(event){if(viewPan?.id!==event.pointerId)return;event.preventDefault();event.stopImmediatePropagation();viewPan=null;viewStage.classList.remove('view-panning');}
viewStage.addEventListener('pointerup',viewPanEnd,true);viewStage.addEventListener('pointercancel',viewPanEnd,true);
canvasViewApply();

addEventListener('resize',canvasViewApply);

// F11 enters true full screen; Escape returns to the desktop window.
addEventListener('keydown',event=>{
  const api=window.pywebview?.api;
  if(!api?.set_fullscreen)return;
  if(event.key==='F11'){
    event.preventDefault();
    if(!event.repeat)api.set_fullscreen().catch(error=>toast(String(error)));
  }else if(event.key==='Escape'){
    api.set_fullscreen(false).catch(error=>toast(String(error)));
  }
});

function setupWindowControls(){
  const api=window.pywebview?.api;
  if(!api?.window_action||document.body.classList.contains('desktop-window'))return;
  document.body.classList.add('desktop-window');
  const controls=$('#windowControls');controls.hidden=false;
  const titlebar=$('#desktopTitlebar');titlebar.hidden=false;
  titlebar.ondblclick=()=>api.window_action('maximize').catch(error=>toast(String(error)));
  $('#panelTitle').classList.add('pywebview-drag-region');
  $('#panelTitle').title='Drag to move; double-click to maximize';
  $('#panelTitle').ondblclick=()=>api.window_action('maximize');
  controls.onclick=event=>{const action=event.target.closest('button')?.dataset.window;if(action)api.window_action(action).catch(error=>toast(String(error)));};
  document.body.insertAdjacentHTML('beforeend','<button id="desktopResize" aria-label="resize window" title="Drag to resize; arrow keys adjust size"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m5 13 8-8m-4 8 4-4"/></svg></button>');
  const grip=$('#desktopResize');let drag=null,pending=null,sending=false;
  async function resize(...size){pending=size;if(sending)return;sending=true;try{while(pending){const next=pending;pending=null;await api.resize_window(...next);}}catch(error){toast(String(error));}finally{sending=false;}}
  const handles=[['se',grip]];
  for(const edge of ['n','s','e','w','ne','nw','sw']){
    const handle=document.createElement('div');handle.className='window-resize-edge edge-'+edge;handle.setAttribute('aria-hidden','true');document.body.append(handle);handles.push([edge,handle]);
  }
  for(const [edge,handle] of handles){
    handle.onpointerdown=async event=>{
      if(event.button!==0)return;event.preventDefault();handle.setPointerCapture(event.pointerId);
      const gesture={id:event.pointerId,edge,startX:event.screenX,startY:event.screenY};drag=gesture;
      try{const state=await api.window_state();if(drag===gesture)Object.assign(drag,state);}catch(error){drag=null;toast(String(error));}
    };
    handle.onpointermove=event=>{
      if(drag?.id!==event.pointerId||!drag.width||drag.maximized)return;
      const dx=event.screenX-drag.startX,dy=event.screenY-drag.startY;
      const width=Math.max(840,Math.min(8192,drag.width+(edge.includes('e')?dx:edge.includes('w')?-dx:0)));
      const height=Math.max(620,Math.min(8192,drag.height+(edge.includes('s')?dy:edge.includes('n')?-dy:0)));
      resize(width,height,drag.x+(edge.includes('w')?drag.width-width:0),drag.y+(edge.includes('n')?drag.height-height:0));
    };
    handle.onpointerup=handle.onpointercancel=()=>{drag=null;};
  }
  grip.onkeydown=async event=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();const state=await api.window_state(),step=event.shiftKey?50:10;resize(state.width+(event.key==='ArrowRight'?step:event.key==='ArrowLeft'?-step:0),state.height+(event.key==='ArrowDown'?step:event.key==='ArrowUp'?-step:0));};


}
addEventListener('pywebviewready',setupWindowControls);setupWindowControls();

let controllerModeActive=false,controllerReturnFocus=null;
function setControllerMode(enabled){
  if(controllerModeActive===enabled)return;
  controllerModeActive=enabled;
  document.body.classList.toggle('controller-mode',enabled);
  if(enabled){controllerReturnFocus=document.activeElement;viewStage.focus({preventScroll:true});toast('Canvas only - Escape or F8 to return');}
  else if(controllerReturnFocus?.isConnected)controllerReturnFocus.focus({preventScroll:true});
  requestAnimationFrame(()=>{canvasViewApply();draw(false);});
}
$('#controllerMode').onclick=()=>setControllerMode(true);
addEventListener('keydown',event=>{
  if(event.key==='F8'){event.preventDefault();if(!event.repeat)setControllerMode(!controllerModeActive);}
  else if(event.key==='Escape'&&controllerModeActive){event.preventDefault();setControllerMode(false);}
},true);

  function alignWindowControls(){
    const panel=$('#settingsPanel').hidden?$('#sideScroll'):$('#settingsPanel');
    const card=panel.querySelector('section'),header=document.querySelector('aside>header');
    if(card&&card.getBoundingClientRect().width)header.style.paddingRight=Math.max(0,header.getBoundingClientRect().right-card.getBoundingClientRect().right)+'px';
  }
  const alignmentObserver=new ResizeObserver(alignWindowControls);
  alignmentObserver.observe($('#sideScroll'));alignmentObserver.observe($('#settingsPanel'));
  alignWindowControls();

