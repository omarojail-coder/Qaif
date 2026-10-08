import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { guestApi } from '../src/guestApi.ts';

const folder = new URL('../public', import.meta.url);
const requested = [];
globalThis.fetch = async url => {
  assert.match(url, /^\/guest-data\/(catalog|inspections|seraj-\d+)\.json$/);
  requested.push(url);
  return { ok: true, json: async () => JSON.parse(await readFile(new URL(`.${url}`, folder.href + '/'), 'utf8')) };
};

assert.equal((await guestApi('/auth/me')).role, 'viewer');
const snapshot = await guestApi('/snapshot');
assert.equal(snapshot.lpg_inspections.length, 6);
assert.equal(snapshot.cylinders.length, 189);
assert.equal(snapshot.config.demo_login_enabled, false);
for (const n of [1, 2, 6, 8, 14, 17, 20, 21]) {
  const serial = `CYL-${String(n).padStart(3, '0')}-01`;
  const passport = await guestApi(`/lpg/demo/cylinders/${serial}`);
  const journey = passport.journeys.at(-1);
  const evidence = await guestApi(`/lpg/demo/cylinders/${serial}/journeys/${journey.id}?until_s=425`);
  assert.ok(evidence.rows.every(r => r.timestamp_s >= 120 && r.timestamp_s <= 425));
  assert.ok(evidence.alerts.every(r => r.timestamp_s <= 425));
  const empty = await guestApi(`/lpg/demo/cylinders/${serial}/journeys/${journey.id}?until_s=0`);
  assert.equal(empty.expected_state, 'unknown');
  assert.equal(empty.sample_count, 0);
  const report = await guestApi(`/public/cylinders/${serial}/report`);
  assert.equal(report.serial, serial);
  assert.equal(report.journeys.length, 6);
  assert.ok(report.journeys.every(j => Array.isArray(j.observations)));
}
for (const task of snapshot.lpg_inspections) {
  const evidence = await guestApi(`/lpg/inspections/${task.id}/evidence`);
  assert.equal(evidence.window.end_s, task.evidence_until_s);
}
await assert.rejects(guestApi('/lpg/inspections', {}), /وضع الزائر/);
await assert.rejects(guestApi('/auth/login', {}), /وضع الزائر/);
await assert.rejects(guestApi('/auth/users'), /تحتاج خادم/);
await assert.rejects(guestApi('/public/cylinders/CYL-999-99/report'), /غير موجود/);
await assert.rejects(guestApi('/lpg/demo/cylinders/CYL-001-01/journeys/J-002-01-06'), /غير موجودة/);

// Optional independently computed Python reference verifies real-model summaries,
// quality gaps, peaks and event grouping across all 21 shipment scenarios.
if (process.argv[2]) {
  const cases = JSON.parse(await readFile(process.argv[2], 'utf8'));
  for (const sample of cases) {
    const value = await guestApi(sample.path);
    delete value.rows;
    assert.deepEqual(value, sample.expected);
  }
  console.log(`Passed ${cases.length} Python/browser evidence comparisons.`);
}
console.log(`Guest auth, membership windows, inspection/report links and write isolation passed (${requested.length} static files).`);
