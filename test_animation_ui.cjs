// Run against an isolated Morphaic test server; requires Playwright + Edge.
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const base=process.env.MORPHAIC_TEST_URL||'http://127.0.0.1:8872';
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base);await page.waitForFunction(()=>window.effectsSync&&window.studioReset);
    await page.locator('#settings').click();await page.locator('#fmt').selectOption('gif');
    assert.equal(await page.locator('#anim_resolution').inputValue(),'full');
    assert.equal(await page.locator('#gifmb').count(),0);
    await page.locator('#closeSettings').click();
    const png=Buffer.from(await page.evaluate(()=>{
      const c=document.createElement('canvas');c.width=320;c.height=240;const g=c.getContext('2d');
      g.fillStyle='#ed6139';g.fillRect(0,0,320,240);g.fillStyle='white';g.fillRect(30,40,100,120);
      return c.toDataURL().split(',')[1];
    }),'base64');
    await page.locator('#pick').setInputFiles({name:'animation.png',mimeType:'image/png',buffer:png});
    await page.waitForFunction(()=>st.files.length===1);
    await page.locator('#settings').click();
    await page.waitForFunction(()=>document.querySelector('#animationEstimate').textContent.includes('320 × 240 px'),{},{timeout:60000});
    await page.locator('#pace').fill('3');await page.locator('#smoothness').fill('4');
    await page.locator('#anim_renderer').selectOption('gpu');
    await page.waitForFunction(()=>document.querySelector('#animationEstimate').textContent.includes('36 frames'),{},{timeout:60000});
    assert((await page.locator('#animationBackend').textContent()).includes('GIF encoding on CPU'));
    await page.locator('#animpreview').click();await page.locator('#motionDialog').waitFor({state:'visible',timeout:60000});
    await page.waitForFunction(()=>document.querySelector('#gifPreview').naturalWidth===320);
    await page.locator('#motionClose').click();
    await page.locator('#fmt').selectOption('mp4');
    await page.waitForFunction(()=>document.querySelector('#animationBackend').textContent.includes('MP4'),{},{timeout:60000});
    await page.locator('#anim_resolution').selectOption('720');
    // Resolution options never upscale a smaller canvas.
    await page.waitForFunction(()=>document.querySelector('#animationEstimate').textContent.includes('320 × 240 px'));
    const saved=page.waitForResponse(r=>r.url().endsWith('/export/mp4'));
    await page.locator('#go').click();assert.equal((await saved).status(),200);
    await page.reload();await page.waitForFunction(()=>window.effectsSync&&window.studioReset);
    await page.locator('#settings').click();await page.locator('#fmt').selectOption('mp4');
    assert.equal(await page.locator('#anim_resolution').inputValue(),'full');
    assert.deepEqual(errors,[]);
    console.log('ok: full-resolution launch default, GIF/MP4 resolution controls, measured estimates, GPU selection, GIF preview and MP4 save');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
