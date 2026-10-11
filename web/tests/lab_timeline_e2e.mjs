// Real browser + disposable localhost app only. Fixtures are never human evidence.
// LAB_TIMELINE_TEST_KEY=... node web/tests/lab_timeline_e2e.mjs http://127.0.0.1:8863
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { Browser } from './browser_e2e.mjs';

const base = process.argv[2] || 'http://127.0.0.1:8863';
assert(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'use disposable localhost');
const key = process.env.LAB_TIMELINE_TEST_KEY;
assert(key?.includes('test'), 'disposable test key required');
const run = `browser_timestamp_test_${Date.now()}`;
const epoch = Math.floor(Date.now() / 1000) - 86400;
const gate = { candidate: 'timeline_test_candidate', baseline: 'v1', verdict: 'reject',
  forgeries_passed: { baseline: 2, candidate: 1, total: 2 }, humans_rejected: {},
  reasons: ['Disposable fixture: no human evidence'] };
const events = [
  ['red', 'round_started', { round: 1, variant: 'v1' }],
  ['red', 'tool_call', { tool: 'forge_and_submit', args: { lag_ms: 180, noise_px: 2 } }],
  ['red', 'tool_result', { summary: 'Timestamp fixture result' }],
  ['red', 'attempt_scored', { pass: false, score: 0.5, failed: ['jitter_px'], attempt_id: run }],
  ['blue', 'tool_call', { tool: 'propose_variant', args: { id: 'timeline_test_candidate' } }],
  ['gate', 'gate_result', gate],
  ['blue', 'approval_needed', { approval_id: run, variant_id: gate.candidate, gate }],
].map(([agent, type, data], i) => ({ agent, type, data, run_id: run, ts: epoch + i }));

async function publish(event) {
  const response = await fetch(base + '/v1/lab/events', { method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Lab-Key': key }, body: JSON.stringify(event) });
  assert.equal(response.status, 204, await response.text());
}
for (const event of events) await publish(event);

const browser = await Browser.launch();
try {
  const page = await browser.newPage('timestamp fixtures');
  const errors = [];
  page.c.on('Runtime.exceptionThrown', e => errors.push(e.exceptionDetails.text));
  page.c.on('Runtime.consoleAPICalled', e => {
    if (e.type === 'error') errors.push(e.args.map(a => a.value || a.description).join(' '));
  });
  await page.c.send('Emulation.setTimezoneOverride', { timezoneId: 'UTC' });
  await page.c.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `localStorage.setItem('followit_lab_key',${JSON.stringify(key)});`,
  });
  await page.phone({ width: 390, dsf: 1 });
  await page.goto('/lab');
  await page.waitFor(`document.querySelectorAll('#log time[datetime=${JSON.stringify(new Date(epoch * 1000).toISOString())}]').length === 1`);
  await page.waitFor(`document.querySelector('.decision-time')`);
  const captureTimes = () => page.eval(`Array.from(document.querySelectorAll('#log .line')).map(line => ({
    text:line.textContent, times:Array.from(line.querySelectorAll('time')).map(t=>({
      iso:t.dateTime, label:t.textContent, title:t.title,
      displayed:getComputedStyle(t).display!=='none' && getComputedStyle(t).visibility!=='hidden',
      width:t.getBoundingClientRect().width, right:t.getBoundingClientRect().right,
    }))
  }))`);
  const first = await captureTimes();
  for (let i = 0; i < events.length; i++) {
    const iso = new Date(events[i].ts * 1000).toISOString();
    const line = first.find(row => row.times.some(t => t.iso === iso));
    assert(line, `missing timestamp for ${events[i].type}`);
    assert.equal(line.times.length, 1);
    assert.match(line.times[0].label, /^\d{2}:\d{2}:\d{2}$/);
    assert(line.times[0].title.includes(String(new Date(epoch * 1000).getUTCFullYear())), 'original event date missing');
    assert(line.times[0].displayed && line.times[0].width > 0 && line.times[0].right <= 390,
      'timestamp hidden or outside mobile viewport');
  }
  const decisionISO = new Date(events.at(-1).ts * 1000).toISOString();
  assert(await page.eval(`Array.from(document.querySelectorAll('.decision-time')).some(t=>t.dateTime===${JSON.stringify(decisionISO)})`));
  const errorEvent = { run_id: run, agent: 'blue', type: 'error', ts: epoch + 20,
    data: { message: `Disposable fixture: model timeout leaves the active policy unchanged ${run}` } };
  await publish(errorEvent);
  await page.waitFor(`document.getElementById('log').textContent.includes(${JSON.stringify(errorEvent.data.message)})`);
  const errorRow = (await captureTimes()).find(row => row.text.includes(errorEvent.data.message));
  assert.equal(errorRow.times[0].iso, new Date(errorEvent.ts * 1000).toISOString());
  await page.clickId('btn-red');
  await page.waitFor(`document.getElementById('toast').textContent.includes('Red queued')`);
  assert.match(await page.text('toast'), /^\[\d{2}:\d{2}:\d{2}\] Red queued/);
  console.log('PASS mobile live/history timestamps: every event, quiet tool result, failure, decision and queued update');

  await page.goto('/lab?replay=1');
  await page.waitFor(`document.getElementById('log').textContent.includes(${JSON.stringify(errorEvent.data.message)})`);
  const replay = await captureTimes();
  for (const event of [...events, errorEvent]) {
    const iso = new Date(event.ts * 1000).toISOString();
    assert(replay.some(row => row.times.some(t => t.iso === iso)), 'replay replaced the recorded timestamp');
  }
  assert.equal(await page.hidden('replay-banner'), false);
  assert(await page.eval(`document.getElementById('btn-red').disabled && document.getElementById('btn-blue').disabled`));
  assert(await page.eval(`Array.from(document.querySelectorAll('.card button')).every(b=>b.disabled)`));
  const requestedTime = new Date(events.at(-1).ts * 1000).toISOString().slice(11, 19);
  assert((await page.eval(`Array.from(document.querySelectorAll('.decision-time')).find(t=>t.dateTime===${JSON.stringify(decisionISO)}).closest('.card').querySelector('.outcome').textContent`)).startsWith(`[${requestedTime}] Recorded decision`));
  await page.eval(`document.getElementById('h-agents').scrollIntoView({block:'start'})`);
  mkdirSync('output/playwright', { recursive: true });
  const shot = await page.c.send('Page.captureScreenshot', { format: 'png' });
  writeFileSync('output/playwright/lab-timeline-phone.png', Buffer.from(shot.data, 'base64'));
  assert.deepEqual(errors, []);
  console.log('PASS replay/reconnect preserve original timestamps and recorded controls remain disabled');
  await page.close();
} finally { await browser.close(); }
