import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../static/lab.js', import.meta.url), 'utf8');
const { gateSummaryLines, buildRows, formatTimestamp, formatEvent, stampedMessage } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const gate = { candidate: 'blue_1', baseline: 'v1', verdict: 'approve_for_review', reasons: [],
  forgeries_passed: { candidate: 6, baseline: 9, total: 16 },
  humans_rejected: { mouse: { candidate: 1, baseline: 1, total: 8 }, trackpad: { candidate: 0, baseline: 0, total: 1 } } };
test('decision names missing devices as untested, preserving gate counts', () => {
  const lines = gateSummaryLines(gate);
  assert(lines.some(line => line === 'touch: untested — no human evidence'));
  assert(lines.some(line => line.includes('mouse: 1 of 8')));
  assert(lines.some(line => line.includes('trackpad: 0 of 1')));
  assert(lines.some(line => line.includes('6 of 16 (baseline 9 of 16)')));
});
test('missing gate data cannot appear to have passed a device check', () => {
  const lines = gateSummaryLines({});
  assert.equal(lines.filter(line => line.includes('untested')).length, 3);
  assert(!lines.some(line => line.includes('0 of 0')));
});
test('comparison preserves latest candidate evidence and active status', () => {
  const rows = buildRows([{ id: 'v1' }, { id: 'blue_1' }], [gate], 'blue_1');
  assert.equal(rows[0].forgeries, '9 of 16');
  assert.equal(rows[1].forgeries, '6 of 16');
  assert.equal(rows[1].active, true);
  assert.deepEqual(rows[1].humans.map(row => row.device), ['mouse', 'trackpad']);
});

test('timestamps preserve source time, seconds, full date and timezone across replays', () => {
  const ts = Date.parse('2026-10-11T10:38:16.125Z') / 1000;
  const stamp = formatTimestamp(ts, { locale: 'en-US', timeZone: 'UTC' });
  assert.equal(stamp.label, '10:38:16');
  assert.equal(stamp.dateTime, '2026-10-11T10:38:16.125Z');
  assert.match(stamp.title, /2026/);
  assert.match(stamp.title, /UTC/);
  for (const type of ['round_started', 'tool_call', 'tool_result', 'attempt_scored', 'gate_result', 'approval_needed', 'round_report', 'variant_activated', 'error']) {
    const event = { agent: 'red', type, ts, data: { summary: 'Tool failed', pass: false } };
    const first = formatEvent(event);
    assert.equal(first.timestamp.dateTime, stamp.dateTime, type);
    assert(first.text.startsWith('['), type);
    assert.deepEqual(formatEvent(event), first, 'replaying must not replace recorded time');
  }
});

test('missing or malformed timestamps cannot look like events that happened just now', () => {
  for (const ts of [undefined, null, '123', NaN, Infinity, 1e30]) {
    assert.equal(formatTimestamp(ts).label, 'Time unavailable');
    assert.equal(formatTimestamp(ts).dateTime, '');
  }
  assert.equal(formatTimestamp(0).dateTime, '1970-01-01T00:00:00.000Z');
  assert.equal(stampedMessage(''), '');
  assert.match(stampedMessage('Red queued', 0), /^\[.+\] Red queued$/);
});

test('Blue reports proposals and activations instead of calling them forged attempts', () => {
  const report = formatEvent({ agent: 'blue', type: 'round_report', ts: 1, data: { round: 2, passed: 1, attempts: 3 } });
  assert.match(report.head, /1 of 3 proposals activated/);
  assert(!report.head.includes('forgeries'));
});
