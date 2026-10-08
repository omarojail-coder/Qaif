type Reading = {
  timestamp_s: number; packet_valid: boolean; lpg_valid: boolean;
  mount_temperature_C: number | null; lpg_ppm: number | null;
  mount_strain_a: number | null; mount_strain_b: number | null;
  acceleration_g: number; latch_closed: boolean;
};
type Signal = { score: number | null; state: string };
export type GuestDemo = {
  rows: Reading[];
  inference_history: { timestamp_s: number; signals: Record<string, Signal> }[];
  alerts: { timestamp_s: number; signal: string }[];
  model_source: string;
};
export type GuestJourney = {
  id: string; current: boolean; reading_start_s: number; reading_end_s: number;
  scenario_number: number; membership: { saddle_id: string };
};

// Summarize saved predictions only within this cylinder's membership window.
// The browser never runs or pretends to retrain the frozen pipe AI model.
export function guestEvidence(serial: string, journey: GuestJourney, demo: GuestDemo, until = 1200) {
  const start = journey.reading_start_s;
  const end = journey.current ? Math.max(0, Math.min(until, journey.reading_end_s)) : journey.reading_end_s;
  const inWindow = (r: { timestamp_s: number }) => r.timestamp_s >= start && r.timestamp_s <= end;
  const rows = demo.rows.filter(inWindow), valid = rows.filter(r => r.packet_valid);
  const history = demo.inference_history.filter(inWindow), alerts = demo.alerts.filter(inWindow);
  const peak = (key: 'mount_temperature_C' | 'lpg_ppm' | 'mount_strain_a' | 'mount_strain_b' | 'acceleration_g', gas = false, absolute = false) => {
    const candidates = valid.filter(r => r[key] !== null && (!gas || r.lpg_valid));
    if (!candidates.length) return null;
    const value = (r: Reading) => absolute ? Math.abs(r[key]!) : r[key]!;
    const row = candidates.reduce((best, next) => value(next) > value(best) ? next : best);
    return { value: row[key], timestamp_s: row.timestamp_s };
  };
  const signals = Object.fromEntries(['mount_anomaly', 'thermal_anomaly', 'lpg_anomaly'].map(head => {
    const scores = history.map(h => h.signals[head].score).filter((s): s is number => s !== null);
    return [head, { max_score: scores.length ? Math.max(...scores) : null,
      confirmed: alerts.some(a => a.signal === head), latest_state: history.at(-1)?.signals[head].state || 'unknown' }];
  }));
  const shocks = valid.filter(r => r.acceleration_g >= 1.5), opened = valid.filter(r => !r.latch_closed);
  const events = (items: Reading[]) => items.filter((r, i) => !i || r.timestamp_s - items[i-1].timestamp_s > 5).length;
  const percent = (count: number) => rows.length ? Math.round(count / rows.length * 1000) / 10 : 0;
  const coverage = percent(valid.length);
  const incomplete = !rows.length || coverage < 90 || !rows.at(-1)!.packet_valid || Object.values(signals).some(s => s.latest_state === 'unknown');
  return { source: 'display_scenario', serial, journey_id: journey.id,
    saddle_id: journey.membership.saddle_id, shared_cage_evidence: true,
    window: { start_s: start, end_s: end }, sample_interval_s: 5,
    sample_count: rows.length, valid_sample_count: valid.length, coverage_percent: coverage,
    lpg_coverage_percent: percent(valid.filter(r => r.lpg_valid).length),
    expected_state: alerts.length || shocks.length || opened.length ? 'review' : incomplete ? 'unknown' : 'clear', incomplete,
    peaks: { temperature: peak('mount_temperature_C'), lpg: peak('lpg_ppm', true),
      strain_a: peak('mount_strain_a', false, true), strain_b: peak('mount_strain_b', false, true), shock: peak('acceleration_g') },
    shock_events: events(shocks), lock_open_events: events(opened), lock_open_observed_s: opened.length * 5,
    signals, alerts, rows, model_source: demo.model_source, lpg_model_trained: false };
}
