import assert from 'node:assert/strict';
import {plannedCount, planningWindow} from '../frontend/src/mapMath.ts';

for (const value of [undefined,null,NaN,Infinity,-1,0,10001]) assert.equal(plannedCount(value),null);
assert.equal(plannedCount(1200),38710);
assert.equal(plannedCount(645),20807);
assert.equal(plannedCount(42),1355);
assert.equal(plannedCount(1200,true),null);
assert.equal(plannedCount(.62),21);
const last = planningWindow(plannedCount(1200),99999);
assert.equal(last.points.at(-1).index,38710);
assert.ok(last.points.at(-1).meters <= 1200000);
assert.equal(last.points.at(-1).meters,1199979);
assert.equal(planningWindow(21,1).points.length,1);
assert.equal(planningWindow(21,1).points[0].meters,620);
assert.equal(planningWindow(21,-9).page,0);
console.log('Planning math: bounds, last partial interval, pagination and historical exclusion passed.');
