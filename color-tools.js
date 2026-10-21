// Shared tools for every tone swatch, including controls created after page load.
(()=>{
  document.body.insertAdjacentHTML('beforeend',`<dialog id="toneEditor" aria-labelledby="toneEditorTitle">
    <h2 id="toneEditorTitle">edit color</h2>
    <div class="row"><label class="grow" for="tonePicker">color picker</label><input id="tonePicker" type="color" aria-label="tone color picker"></div>
    <div class="row"><label class="grow" for="toneHex">hex code</label><input id="toneHex" aria-label="tone hex code" maxlength="7" spellcheck="false" autocomplete="off"></div>
    <label for="toneHue">hue <output id="toneHueValue"></output></label><input id="toneHue" type="range" min="0" max="360" step="1" aria-label="tone hue">
    <label for="toneSaturation">saturation <output id="toneSaturationValue"></output></label><input id="toneSaturation" type="range" min="0" max="100" step="1" aria-label="tone saturation">
    <label for="toneLightness">lightness <output id="toneLightnessValue"></output></label><input id="toneLightness" type="range" min="0" max="100" step="1" aria-label="tone lightness">
    <p class="note" id="toneMessage" role="status">Use the picker, hue sliders, or a 3- or 6-digit hex code.</p>
    <footer><button id="toneDone" aria-label="done editing color">done</button></footer></dialog>`);
  const dialog=document.querySelector('#toneEditor'),hex=document.querySelector('#toneHex'),picker=document.querySelector('#tonePicker');
  const sliders=['Hue','Saturation','Lightness'].map(name=>document.querySelector('#tone'+name));
  let target=null,returnFocus=null,hsl=[0,0,0];
  function toHsl(color){
    const [r,g,b]=[1,3,5].map(i=>parseInt(color.slice(i,i+2),16)/255);
    const max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min,l=(max+min)/2;
    let h=0,s=0;
    if(d){s=d/(1-Math.abs(2*l-1));h=max===r?((g-b)/d)%6:max===g?(b-r)/d+2:(r-g)/d+4;h=(h*60+360)%360;}
    return [h,s*100,l*100];
  }
  function fromHsl([h,s,l]){
    s/=100;l/=100;
    const c=(1-Math.abs(2*l-1))*s,x=c*(1-Math.abs((h/60)%2-1)),m=l-c/2;
    const rgb=h<60?[c,x,0]:h<120?[x,c,0]:h<180?[0,c,x]:h<240?[0,x,c]:h<300?[x,0,c]:[c,0,x];
    return '#'+rgb.map(v=>Math.round((v+m)*255).toString(16).padStart(2,'0')).join('');
  }
  function sync(color,updateHsl=true){
    hex.value=picker.value=color;hex.setCustomValidity('');
    if(updateHsl)hsl=toHsl(color);
    sliders.forEach((el,i)=>{el.value=Math.round(hsl[i]);document.querySelector('#tone'+['Hue','Saturation','Lightness'][i]+'Value').value=Math.round(hsl[i])+(i===0?'°':'%');});
  }
  function apply(color,updateHsl=true){
    if(!target?.isConnected||target.disabled)return;
    target.value=color;target.dispatchEvent(new Event('input',{bubbles:true}));sync(color,updateHsl);
  }
  function open(input,button){
    if(input.disabled)return;
    finishHistory();beginHistory();target=input;returnFocus=button;
    document.querySelector('#toneEditorTitle').textContent=input.getAttribute('aria-label')||'edit color';
    sync(input.value);dialog.showModal();hex.focus();hex.select();
  }
  hex.oninput=()=>{
    let value=hex.value.trim().replace(/^#/,'');
    if(!/^(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(value)){hex.setCustomValidity('Enter a valid 3- or 6-digit hex code');return;}
    if(value.length===3)value=[...value].map(c=>c+c).join('');
    // Keep typing stable while normalizing the color sent to the source control.
    const entered=hex.value;apply('#'+value.toLowerCase());hex.value=entered;
  };
  picker.oninput=()=>apply(picker.value);
  sliders.forEach((el,i)=>el.oninput=()=>{
    hsl[i]=+el.value;
    if(i===0&&hsl[1]===0){hsl[1]=100;if(hsl[2]===0||hsl[2]===100)hsl[2]=50;}
    apply(fromHsl(hsl),false);
  });
  document.querySelector('#toneDone').onclick=()=>{if(hex.reportValidity())dialog.close();};
  dialog.addEventListener('close',()=>{
    if(target?.isConnected)target.dispatchEvent(new Event('change',{bubbles:true}));
    finishHistory();target=null;if(returnFocus?.isConnected&&!returnFocus.disabled)returnFocus.focus();
  });
  function enhance(){
    document.querySelectorAll('input[type=color]').forEach(input=>{
      if(input.closest('#toneEditor'))return;
      let button=input.parentElement.querySelector(':scope>.tone-edit');
      if(!input.dataset.toneEnhanced){
        input.dataset.toneEnhanced='true';
        const wrap=document.createElement('span');wrap.className='tone-control';input.before(wrap);wrap.append(input);
        button=document.createElement('button');button.type='button';button.className='tone-edit';button.textContent='⋯';
        const label=input.getAttribute('aria-label')||input.id||'color';
        button.setAttribute('aria-label',`edit ${label} hue and hex`);button.title='Hue, hex code and color picker';
        button.onclick=()=>open(input,button);wrap.append(button);
      }
      if(button&&button.disabled!==input.disabled)button.disabled=input.disabled;
    });
    document.querySelectorAll('input[type=range][aria-label*="opacity"]').forEach(input=>{
      const text=Math.round(+input.value*100)+'%';
      if(input.getAttribute('aria-valuetext')!==text)input.setAttribute('aria-valuetext',text);
      input.title=text;
    });
  }
  window.controlToolsSync=enhance;
  document.addEventListener('input',enhance);
  new MutationObserver(enhance).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled']});
  enhance();
})();
