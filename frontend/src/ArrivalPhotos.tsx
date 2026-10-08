import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { RecordData } from "./api";
import CapturePair from "./CapturePair";
import "./arrival-photos.css";

export default function ArrivalPhotos({ captures }: { captures: RecordData[] }) {
  const [selected, setSelected] = useState<RecordData | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (selected) dialog.current?.showModal();
    else dialog.current?.close();
  }, [selected]);
  return <div className="arrival-photos" data-arrival-photos data-mission-id={captures[0]?.mission_id}>
    <p className="gallery-context small muted" role="status">وصلت الدرون · صور الجولة</p>
    <CapturePair captures={captures} selectionPurpose="preview" onSelect={id => setSelected(captures.find(c => c.id === id) || null)} />
    <dialog ref={dialog} className="modal arrival-photo-dialog" aria-label="عرض صورة الوصول" onCancel={() => setSelected(null)} onClick={event => { if (event.target === event.currentTarget) setSelected(null); }}>
      <div className="modal-heading"><h2>{selected?.mode === "thermal" ? "الصورة الحرارية" : "الصورة العادية · RGB"}</h2><button className="icon-button" aria-label="إغلاق صورة الوصول" onClick={() => setSelected(null)}><X size={20} /></button></div>
      {selected && <img src={selected.image_url} alt={selected.note} />}
    </dialog>
  </div>;
}
