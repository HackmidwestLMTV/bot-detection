// Actual browser rendering and phone-sized catch areas; never saves human recordings.
// node web/tests/presentation_e2e.mjs http://127.0.0.1:8803 http://127.0.0.1:8804
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { Browser, sleep } from './browser_e2e.mjs';

const CHECKOUT = process.argv[2] || 'http://127.0.0.1:8803';
const RECORDER = process.argv[3] || 'http://127.0.0.1:8804';
const browser = await Browser.launch();
const failures = [];
const probe = `(() => {
  const prototype = CanvasRenderingContext2D.prototype;
  const fillRect = prototype.fillRect, arc = prototype.arc, lineTo = prototype.lineTo;
  window.targetFrame = { circles: [], lines: 0 };
  prototype.fillRect = function(x,y,w,h) {
    if(x===0 && y===0 && w>=600) window.targetFrame = { circles: [], lines: 0 };
    return fillRect.apply(this,arguments);
  };
  prototype.arc = function(x,y,r) {
    if(r>4) window.targetFrame.circles.push([x,y,r]);
    return arc.apply(this,arguments);
  };
  prototype.lineTo = function() {
    window.targetFrame.lines++;
    return lineTo.apply(this,arguments);
  };
})();`;

function ringOnly(frame) {
  assert.equal(frame.lines, 0, 'directional lines remain');
  assert(frame.circles.length >= 3, 'missing ball, glow, or ring');
  const centers = new Set(frame.circles.map(([x,y]) => `${x.toFixed(3)},${y.toFixed(3)}`));
  assert.equal(centers.size, 1, 'a movement trail or displaced cue remains');
}

async function run(label, callback) {
  const page = await browser.newPage(label);
  const errors = [];
  page.c.on('Runtime.exceptionThrown', e => errors.push(e.exceptionDetails.text));
  try {
    await page.phone({ mobile: true, dsf: 2 });
    await page.c.send('Page.addScriptToEvaluateOnNewDocument', { source: probe });
    await callback(page);
    assert.deepEqual(errors, []);
    console.log(`PASS ${label}`);
  } catch (error) {
    failures.push(label);
    console.error(`FAIL ${label}: ${error.stack}`);
  } finally {
    await page.close();
  }
}

try {
  await run('320px checkout keeps the entire start ring in the canvas across roaming seeds', async page => {
    await page.phone({ mobile: true, width: 320, dsf: 2 });
    await page.goto('/');
    await page.waitFor(`document.getElementById('overlay').textContent.includes('inside the ring')`);
    const rect = await page.rect('#comet');
    const margin = await page.eval(`(() => {
      let margin = Infinity;
      for(let seed = 0; seed < 200; seed++) {
        const path = window.makePath(seed, 'roaming_v3');
        for(let t = 0; t <= 5000; t += 20) {
          const [x,y] = path(t);
          margin = Math.min(margin,x,600-x,y,400-y);
        }
      }
      return margin;
    })()`);
    assert(margin * rect.w / 600 >= 33, `ring clipped: canvas ${rect.w}px, margin ${margin * rect.w / 600}px`);
    assert(await page.eval(`document.documentElement.scrollWidth <= innerWidth`), 'checkout overflows phone viewport');
    console.log(`INFO 320px viewport: canvas ${rect.w}px, sampled minimum ring clearance ${(margin * rect.w / 600).toFixed(1)}px`);
  });

  await run('checkout ring edge starts; moving target has no arrow or trail', async page => {
    await page.goto('/');
    await page.waitFor(`document.getElementById('overlay').textContent.includes('inside the ring')`);
    const request = page.lastReq('/v1/challenges');
    const challenge = JSON.parse(await page.responseBody(request.id));
    assert.equal(challenge.presentation_version, 'plain_ring_5s_v2');
    assert.equal(challenge.path_version, 'roaming_v3');
    assert.equal(challenge.duration_ms, 5000);
    const rect = await page.rect('#comet');
    const point = await page.eval(`window.makePath(${challenge.seed},${JSON.stringify(challenge.path_version)})(0)`);
    const x = rect.x + point[0]*rect.w/600 + 32*.9, y = rect.y + point[1]*rect.h/400;
    await page.c.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 1 }] });
    await page.waitFor(`document.getElementById('overlay').textContent === ''`, 2000);
    await sleep(200);
    ringOnly(await page.eval('window.targetFrame'));
    assert(await page.hidden('tester'));
    if(process.env.FOLLOWIT_SCREENSHOT_DIR) {
      const screenshot = await page.c.send('Page.captureScreenshot', { format: 'png' });
      writeFileSync(join(process.env.FOLLOWIT_SCREENSHOT_DIR,'checkout-phone.png'), Buffer.from(screenshot.data,'base64'));
    }
    await page.c.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await page.clickId('skip');
    await page.waitFor(`!document.getElementById('reserve').disabled`);
  });

  await run('recorder ring edge starts; display matches checkout without saving', async page => {
    await page.c.send('Page.navigate', { url: `${RECORDER}/dev/recorder` });
    await page.waitFor(`document.getElementById('new') && !document.getElementById('new').disabled`);
    await page.clickId('new');
    await page.waitFor(`document.getElementById('status').textContent.includes('Touch or point')`);
    const request = page.lastReq('/dev/challenges');
    const challenge = JSON.parse(await page.responseBody(request.id));
    assert.equal(challenge.presentation_version, 'plain_ring_5s_v2');
    assert.equal(challenge.path_version, 'roaming_v3');
    assert.equal(challenge.duration_ms, 5000);
    const rect = await page.rect('#trail');
    const point = await page.eval(`import('${RECORDER}/dev/path.js').then(m=>m.makePath(${challenge.seed},${JSON.stringify(challenge.path_version)})(0))`);
    const x = rect.x + point[0]*rect.w/600 + 32*.9, y = rect.y + point[1]*rect.h/400;
    await page.c.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 1 }] });
    await page.waitFor(`document.getElementById('status').textContent.includes('Follow the')`, 2000);
    await sleep(200);
    ringOnly(await page.eval('window.targetFrame'));
    if(process.env.FOLLOWIT_SCREENSHOT_DIR) {
      const screenshot = await page.c.send('Page.captureScreenshot', { format: 'png' });
      writeFileSync(join(process.env.FOLLOWIT_SCREENSHOT_DIR,'recorder-phone.png'), Buffer.from(screenshot.data,'base64'));
    }
    await page.c.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await page.waitFor(`document.getElementById('status').textContent.includes('Contact ended early')`);
    assert.equal(page.req('/dev/recordings').length, 0);
  });
} finally {
  await browser.close();
}
if(failures.length) process.exitCode = 1;
