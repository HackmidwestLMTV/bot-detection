// Disposable localhost only. This is automated fixture input, never human evidence.
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { Browser, sleep } from './browser_e2e.mjs';

const base = process.argv[2] || 'http://127.0.0.1:8813';
assert(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'use disposable localhost');
const key = process.env.RESEARCH_TEST_KEY;
assert(key && key.includes('test'), 'disposable test key required');
const enroll = await fetch(base + '/v1/research/enrollments', { method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-Lab-Key': key },
  body: JSON.stringify({ participant_id: 'fixture_browser_' + Date.now() }) });
assert.equal(enroll.status, 200);
const { code } = await enroll.json();
const browser = await Browser.launch();
try {
  const page = await browser.newPage('research fixture');
  const errors = [];
  page.c.on('Runtime.exceptionThrown', e => errors.push(e.exceptionDetails.text));
  await page.phone({ width: 390, dsf: 1 });
  await page.goto('/?tester=1');
  await page.waitFor('!document.getElementById("tester").hidden');
  await page.eval(`document.getElementById('research-code').value=${JSON.stringify(code)};
    document.getElementById('consent').checked=true;
    document.querySelector('input[value="trackpad"]').checked=true;
    document.getElementById('tester').dispatchEvent(new Event('change'));`);
  await sleep(200);
  assert.equal(page.req('/v1/challenges').length, 0, 'training consent must be explicit');
  await page.clickId('training-consent');
  await page.waitFor('document.getElementById("overlay").textContent.includes("inside the ring")');
  const request = page.lastReq('/v1/challenges');
  const ch = JSON.parse(await page.responseBody(request.id));
  assert.equal(ch.duration_ms, 5000);
  assert.equal(ch.presentation_version, 'plain_ring_5s_v2');
  const rect = await page.rect('#comet');
  const positions = await page.eval(`Array.from({length:301},(_,i)=>window.makePath(${ch.seed},${JSON.stringify(ch.path_version)})(i*5000/300))`);
  const started = Date.now();
  while (Date.now() - started < 5000) {
    const step = Math.min(300, Math.floor((Date.now() - started) * 300 / 5000));
    const [x, y] = positions[step];
    await page.c.send('Input.dispatchMouseEvent', { type: 'mouseMoved', button: 'none', buttons: 0,
      x: rect.x + x * rect.w / 600, y: rect.y + y * rect.h / 400, pointerType: 'mouse' });
    await sleep(12);
  }
  await page.waitFor('document.getElementById("result").textContent.includes("Research recording saved")');
  const attempt = JSON.parse(await page.postBody(page.lastReq('/attempt')));
  assert.equal(attempt.collector_version, 'pointer_v2');
  assert.equal(attempt.device, 'trackpad');
  assert(attempt.samples.length >= 40 && attempt.samples.at(-1)[0] - attempt.samples[0][0] >= 4500);
  assert.equal(attempt.session_id, JSON.parse(await page.postBody(request)).session_id);
  assert.deepEqual(errors, []);
  await page.eval('document.getElementById("tester").scrollIntoView({block:"start"})');
  const screenshot = await page.c.send('Page.captureScreenshot', { format: 'png' });
  mkdirSync('.ml-runs', { recursive: true });   // gitignored, so absent in a fresh clone
  writeFileSync('.ml-runs/research-tester-phone.png', Buffer.from(screenshot.data, 'base64'));
  console.log('PASS enrolled browser collection: consent, native events, session binding, storage outcome, 390px layout');
} finally {
  await browser.close();
}
