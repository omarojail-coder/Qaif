import { useEffect, useRef, useState } from "react";
import type { RecordData } from "./api";
import { ArrivalPhotoTracker } from "./transientFlightPhotos";

export default function useTransientFlightPhotos(missions: RecordData[], clockOffset: number) {
  const tracker = useRef<ArrivalPhotoTracker | null>(null);
  if (!tracker.current) tracker.current = new ArrivalPhotoTracker();
  const [photos, setPhotos] = useState<Record<string, RecordData[]>>({});
  useEffect(() => {
    const tick = () => {
      const arrivals = tracker.current!.poll(missions, Date.now() + clockOffset);
      if (arrivals.length) setPhotos(previous => ({
        ...previous,
        ...Object.fromEntries(arrivals.map(arrival => [arrival.key, arrival.captures])),
      }));
    };
    tick();
    const interval = setInterval(tick, 250);
    return () => clearInterval(interval);
  }, [missions, clockOffset]);
  return photos;
}
