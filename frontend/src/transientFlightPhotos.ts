import { ARRIVAL_GALLERIES } from "./arrivalGallery";
import { flightState, type FlightPlan } from "./droneFlight";
import type { RecordData } from "./api";

export function flightPhotoKey(mission: RecordData): string {
  return `${mission.id}:${mission.virtual_flight?.started_ms ?? "unstarted"}`;
}

export type ArrivalPhotos = { key: string; missionId: string; captures: RecordData[] };

// Per-page memory. A newly opened page never replays arrival events for already finished flights.
export class ArrivalPhotoTracker {
  private runs = new Map<string, { armed: boolean; delivered: boolean }>();

  poll(missions: RecordData[], now: number, random: () => number = Math.random): ArrivalPhotos[] {
    const arrivals: ArrivalPhotos[] = [];
    for (const mission of missions) {
      const plan = mission.virtual_flight as FlightPlan | undefined;
      if (!plan || plan.source !== "virtual_display" || plan.started_ms === null) continue;
      const key = flightPhotoKey(mission);
      const state = flightState(plan, now, mission.status === "cancelled");
      let run = this.runs.get(key);
      if (!run) {
        run = { armed: false, delivered: false };
        this.runs.set(key, run);
      }
      if (state.phase === "stopped") { run.armed = false; continue; }
      if (state.phase === "flying") { run.armed = true; continue; }
      const gallery = ARRIVAL_GALLERIES[mission.saddle_id];
      if (state.phase !== "arrived" || !run.armed || run.delivered || !gallery) continue;
      run.delivered = true;
      // Pick a random visit pair, preserving the same scene in RGB and thermal views.
      const variant = Math.max(0, Math.min(gallery.rgb.length - 1, Math.floor(random() * gallery.rgb.length)));
      const captures = (["rgb", "thermal"] as const).map(mode => {
        const options = gallery[mode];
        const chosen = options[variant];
        return {
          id: `preview:${key}:${mode}`, mission_id: mission.id, saddle_id: mission.saddle_id,
          mode, image_url: chosen.url, note: chosen.note, source: "prepared_demo",
          asset_origin: "ai_generated", asset_pack: "drone-arrival-v37", transient: true,
          displayed_at: new Date(now).toISOString(), captured_at: null, thermal: null,
        };
      });
      arrivals.push({ key, missionId: mission.id, captures });
    }
    return arrivals;
  }
}
