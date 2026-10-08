export type FlightPosition = [number, number];
export type FlightPlan = {
  version: number;
  source: "virtual_display";
  origin: { id: string; name: string; type: string; position: FlightPosition };
  target: { id: string; name: string; position: FlightPosition };
  path: FlightPosition[];
  distance_km: number;
  duration_s: number;
  started_ms: number | null;
  stopped_ms: number | null;
};
export function flightState(plan: FlightPlan, now: number, cancelled = false) {
  const end = plan.stopped_ms ?? now;
  const elapsed = plan.started_ms === null ? 0 : Math.max(0, (end - plan.started_ms) / 1000);
  const progress = plan.started_ms === null ? 0 : plan.duration_s <= 0 ? 1 : Math.min(1, elapsed / plan.duration_s);
  const phase = cancelled || plan.stopped_ms !== null ? "stopped" : plan.started_ms === null ? "planned" : progress >= 1 ? "arrived" : "flying";
  return { progress, phase, remaining: Math.max(0, Math.ceil(plan.duration_s - elapsed)) };
}
export function flightPoint(path: FlightPosition[], progress: number): FlightPosition {
  const t = Math.max(0, Math.min(1, progress)) * (path.length - 1);
  const i = Math.min(path.length - 2, Math.floor(t));
  const fraction = t - i;
  return [path[i][0] + (path[i+1][0] - path[i][0]) * fraction, path[i][1] + (path[i+1][1] - path[i][1]) * fraction];
}
export function travelledPath(path: FlightPosition[], progress: number) {
  const count = Math.floor(Math.max(0, Math.min(1, progress)) * (path.length - 1));
  return [...path.slice(0, count + 1), flightPoint(path, progress)];
}
export const DRONE_ICON = '<svg viewBox="0 0 32 32" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="7" cy="7" r="4.5"/><circle cx="25" cy="7" r="4.5"/><circle cx="7" cy="25" r="4.5"/><circle cx="25" cy="25" r="4.5"/><path d="m10 10 4 4m8-4-4 4m-8 8 4-4m8 4-4-4"/><rect x="12" y="11" width="8" height="10" rx="2"/><path d="M15 24h2"/></svg>';
