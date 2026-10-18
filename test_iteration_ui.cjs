// Requires Playwright and Edge; run against an isolated server/settings directory.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.MORPHAIC_TEST_URL || 'http://127.0.0.1:8872';
const output = path.resolve('tmp/ui-test');
fs.mkdirSync(output,{recursive:true});

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900},colorScheme:'dark'});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const check=async(fn)=>assert(await page.evaluate(fn));
  const settle=async()=>{await page.waitForFunction(()=>!busy&&again===null);await page.waitForTimeout(150);};
  try {
    await page.goto(base);await page.waitForFunction(()=>window.effectsSync&&window.studioReset);
    await page.request.post(base+'/preferences',{data:{skip_reset_warning:false}});
    await page.reload();await page.waitForFunction(()=>window.effectsSync&&window.studioReset);
    const png=Buffer.from(await page.evaluate(()=>{
      const c=document.createElement('canvas');c.width=603;c.height=471;const g=c.getContext('2d');
      const gradient=g.createLinearGradient(0,0,603,471);gradient.addColorStop(0,'#0d275b');gradient.addColorStop(.5,'#ea7350');gradient.addColorStop(1,'#ffe8b3');
      g.fillStyle=gradient;g.fillRect(0,0,603,471);g.fillStyle='#fff';g.fillRect(47,51,103,179);g.fillStyle='#29252d';g.beginPath();g.arc(420,234,95,0,Math.PI*2);g.fill();return c.toDataURL().split(',')[1];
    }),'base64');
    await page.locator('#pick').setInputFiles({name:'test-original.png',mimeType:'image/png',buffer:png});
    await page.waitForFunction(()=>st.files.length===1&&document.querySelector('#view').naturalWidth>0);await settle();
    await check(()=>P.rot===0&&P.scatter===0&&P.var===0&&P.layers===1&&P.exposure===0&&P.grain===0);
    await page.locator('#undo').click();await check(()=>st.files.length===0);
    await page.locator('#redo').click();await settle();await check(()=>st.files.length===1&&st.w>0&&st.h>0);
    await page.screenshot({path:path.join(output,'neutral-import.png')});
    await check(()=>!document.querySelector('#sl-cut input[aria-label="width value"]')&&document.querySelector('#cutDisclosure').children[1].querySelector('#multiShape'));
    await page.locator('#viewZoomIn').click();await check(()=>canvasView.zoom>1);
    const original=await page.evaluate(()=>({w:st.w,h:st.h}));
    await page.locator('#stage').focus();await page.keyboard.press('ArrowRight');await check(()=>canvasView.x<0);
    await page.mouse.move(240,360);await page.mouse.wheel(0,-120);await check(()=>canvasView.zoom>1.25);
    await page.keyboard.down('Shift');await page.mouse.wheel(0,100);await page.keyboard.up('Shift');
    await check(()=>canvasView.x!==0);assert.deepEqual(await page.evaluate(()=>({w:st.w,h:st.h})),original);
    await page.locator('#viewFit').click();await settle();
    await page.locator('#frame').click();await page.keyboard.down('Space');await page.mouse.move(280,350);await page.mouse.down();await page.mouse.move(320,380,{steps:3});await page.mouse.up();await page.keyboard.up('Space');await check(()=>canvasView.x===40&&canvasView.y===30);
    await page.locator('#viewFit').click();await settle();await check(()=>canvasView.zoom===1&&canvasView.x===0&&canvasView.y===0);
    await page.locator('#settings').click();await page.locator('#fmt').selectOption('indesign');
    await check(()=>document.querySelector('#templateName').textContent==='No template selected'&&!document.querySelector('#templatePanel').hidden);
    if(process.env.MORPHAIC_TEST_TEMPLATE){
      await page.locator('#templateFile').setInputFiles(process.env.MORPHAIC_TEST_TEMPLATE);
      await page.waitForFunction(()=>st.template.frames.length===2,{},{timeout:60000});
      await check(()=>Object.values(st.template.mapping).includes('collage')&&Object.values(st.template.mapping).includes('migration'));
      await page.locator('#templateTitle').fill('Browser template check');
      const completed=page.waitForResponse(r=>r.url().endsWith('/indesign/export'),{timeout:90000});
      await page.locator('#go').click();const response=await completed;assert.equal(response.status(),200);assert(fs.statSync((await response.json()).path).size>1000);
      await page.screenshot({path:path.join(output,'template-import.png')});
    }
    await page.locator('#fmt').selectOption('png');await page.locator('#closeSettings').click();

    await page.locator('#gradingDisclosure summary').click();
    await page.getByRole('textbox',{name:'exposure value',exact:true}).fill('1');
    await page.getByRole('textbox',{name:'exposure value',exact:true}).press('Tab');await settle();
    await check(()=>P.exposure===1);
    await page.locator('#gradientDisclosure summary').click();
    await page.locator('#gradientPreset').selectOption('sunset');
    await page.getByRole('textbox',{name:'gradient amount value',exact:true}).fill('65');
    await page.getByRole('textbox',{name:'gradient amount value',exact:true}).press('Tab');await settle();
    await check(()=>P.gradient_stops.length===3&&P.gradient_amount===.65);
    await page.locator('#gradientAdd').click();await check(()=>P.gradient_stops.length===4);
    await page.locator('#undo').click();await check(()=>P.gradient_stops.length===3);
    await page.locator('#grainDisclosure summary').click();
    await page.locator('#grainFile').setInputFiles({name:'custom-grain.png',mimeType:'image/png',buffer:png});
    await page.waitForFunction(()=>Boolean(P.grain_source_id));
    await page.getByRole('textbox',{name:'grain amount value',exact:true}).fill('30');
    await page.getByRole('textbox',{name:'grain amount value',exact:true}).press('Tab');await settle();
    await check(()=>P.grain===.3&&P.grain_source_name==='custom-grain.png');

    await page.locator('#frame').click({button:'right'});
    assert(await page.locator('#canvasMenu').isVisible());
    await page.locator('#canvasReset').click();await settle();
    await check(()=>P.exposure===0&&P.gradient_amount===0&&P.grain_source_id===''&&st.files.length===1);
    await page.locator('#undo').click();await settle();
    await check(()=>P.exposure===1&&P.grain===.3&&P.grain_source_name==='custom-grain.png');
    await page.locator('#frame').click({button:'right'});await page.locator('#canvasRemove').click();
    assert(await page.locator('#empty').isVisible());
    await page.locator('#undo').click();await settle();await check(()=>st.files.length===1);

    await page.locator('#resetAll').click();assert(await page.locator('#resetDialog').isVisible());
    await page.locator('#cancelReset').click();await check(()=>P.exposure===1);
    await page.locator('#resetAll').click();await page.locator('#confirmReset').click();await settle();
    await check(()=>P.exposure===0&&P.grain===0&&st.cut.cut_shape==='rectangle'&&st.files.length===1);
    await page.locator('#undo').click();await settle();await check(()=>P.exposure===1);

    // Real pointer cuts and local cut history; overlay must not cover the sidebar.
    await page.locator('#knifeOpen').click();
    await page.waitForFunction(()=>document.querySelector('#knifeCanvas').clientWidth>0);
    await check(()=>document.querySelector('#knifeDialog').parentElement.id==='stage');
    for(const viewport of [{width:1280,height:900},{width:840,height:620},{width:600,height:900}]){
      await page.setViewportSize(viewport);await page.waitForTimeout(160);await page.screenshot({path:path.join(output,'mat-'+viewport.width+'.png')});
      await check(()=>{const stage=document.querySelector('#stage').getBoundingClientRect(),dialog=document.querySelector('#knifeDialog').getBoundingClientRect(),c=document.querySelector('#knifeCanvas').getBoundingClientRect();return dialog.left>=stage.left&&dialog.right<=stage.right&&dialog.bottom<=stage.bottom&&c.width>100&&c.height>80&&Math.abs(c.width/c.height-document.querySelector('#frame').clientWidth/document.querySelector('#frame').clientHeight)<.02&&document.querySelector('#knifeCanvas').parentElement.id==='frame';});
    }
    await page.setViewportSize({width:1280,height:900});await page.waitForTimeout(200);
    const box=await page.locator('#knifeCanvas').boundingBox();
    const points=[[250,180],[650,180],[650,450],[250,450],[250,180]].map(([x,y])=>({x:box.x+x/1000*box.width,y:box.y+y/650*box.height}));
    await page.mouse.move(points[0].x,points[0].y);await page.mouse.down();
    for(const point of points.slice(1))await page.mouse.move(point.x,point.y,{steps:12});
    await page.mouse.up();await page.locator('#knifeSeal').click();
    assert(await page.locator('#knifeUse').isEnabled());
    await page.locator('#knifeUndo').click();assert(await page.locator('#knifeUse').isDisabled());
    await page.locator('#knifeRedo').click();assert(await page.locator('#knifeUse').isEnabled());
    await page.screenshot({path:path.join(output,'cutting-mat.png')});
    await page.locator('#knifeUse').click();await settle();
    await check(()=>st.cut.cut_shape==='custom'&&st.cut.custom_shape.length>=3);
    await page.locator('#knifeOpen').click();await page.locator('#knifeCanvas').press('Escape');
    assert(!(await page.locator('#knifeDialog').isVisible()));

    // Quick export uses current format; verify HTTP success and a real file.
    await page.locator('#frame').click({button:'right'});
    const exported=page.waitForResponse(response=>response.url().endsWith('/export/png'));
    await page.locator('#canvasExport').click();const exportResponse=await exported;
    assert.equal(exportResponse.status(),200);const saved=await exportResponse.json();assert(fs.statSync(saved.path).size>100);
    await page.locator('#resetAll').click();await page.locator('#skipResetWarning').check();
    const preference=page.waitForResponse(response=>response.url().endsWith('/preferences')&&response.request().method()==='POST');
    await page.locator('#confirmReset').click();assert.equal((await preference).status(),200);await settle();

    await page.locator('#settings').click();await page.locator('#exportMode [data-mode="3d"]').click();
    await check(()=>lumControls.spacing_mm.r.min==='0.01'&&lumControls.spacing_mm.r.step==='0.01');
    await page.screenshot({path:path.join(output,'relief-settings.png')});
    await page.reload();await page.waitForFunction(()=>window.effectsSync&&window.studioReset);
    await page.locator('#resetAll').click();await page.waitForTimeout(200);
    assert(!(await page.locator('#resetDialog').isVisible()));
    await page.locator('#pick').setInputFiles([{name:'one.png',mimeType:'image/png',buffer:png},{name:'two.png',mimeType:'image/png',buffer:png}]);
    await page.waitForFunction(()=>st.files.length===2);await settle();
    await page.locator('#undo').click();await check(()=>st.files.length===0);
    await page.locator('#redo').click();await settle();await check(()=>st.files.length===2&&st.w>0&&st.h>0);
    await page.emulateMedia({colorScheme:'light'});await page.screenshot({path:path.join(output,'light-interface.png')});
    assert.deepEqual(errors,[]);
    console.log('ok: neutral import, grading, custom grain, gradient stops, undo, context actions, reset warning persistence, canvas mat fit/cut/history, quick export and relief quality UI');
  } finally {
    await page.request.post(base+'/preferences',{data:{skip_reset_warning:false}}).catch(()=>{});
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});

