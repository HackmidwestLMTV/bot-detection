import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../static/lab.js', import.meta.url), 'utf8');
const { gateSummaryLines, buildRows } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
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
