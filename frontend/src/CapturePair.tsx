import { useState } from "react";
import { Image, Thermometer, Upload } from "lucide-react";
import type { RecordData } from "./api";
import { DISPLAY_LOCALE } from "./locale";

const sources: Record<string, string> = {
  uploaded: "صورة مرفوعة",
  camera_export: "تصدير كاميرا",
  prepared_demo: "صورة مُعدّة للعرض",
};
const timestamp = (capture: RecordData) =>
  capture.transient && capture.displayed_at
    ? "وقت العرض: " + new Date(capture.displayed_at).toLocaleString(DISPLAY_LOCALE, { calendar: "gregory", dateStyle: "short", timeStyle: "short" })
    : capture.captured_at
    ? new Date(capture.captured_at).toLocaleString(DISPLAY_LOCALE, {
        calendar: "gregory",
        dateStyle: "short",
        timeStyle: "short",
      })
    : "وقت التصوير غير موثق";

export default function CapturePair({
  captures,
  activeId,
  onSelect,
  onUpload,
  selectionPurpose = "review",
}: {
  captures: RecordData[];
  activeId?: string;
  onSelect?: (id: string) => void;
  onUpload?: () => void;
  selectionPurpose?: "preview" | "review";
}) {
  const [chosen, setChosen] = useState<Record<string, string>>({});
  return (
    <>
      <div className="capture-pair">
        {(["rgb", "thermal"] as const).map((mode) => {
          const items = captures.filter((c) => c.mode === mode);
          const image =
            items.find((c) => c.id === chosen[mode]) ||
            items.find((c) => c.id === activeId) ||
            items[0];
          const Icon = mode === "rgb" ? Image : Thermometer;
          return (
            <section
              key={mode}
              className={`capture-slot ${mode} ${image?.id === activeId ? "selected" : ""}`}
            >
              <div className="capture-slot-heading">
                <h4>
                  <Icon size={18} />
                  {mode === "rgb" ? "الصورة العادية · RGB" : "الصورة الحرارية"}
                </h4>
                {items.length > 1 && (
                  <select
                    aria-label={
                      mode === "rgb"
                        ? "الصورة العادية للجولة"
                        : "الصورة الحرارية للجولة"
                    }
                    value={image?.id || ""}
                    onChange={(e) => {
                      setChosen({ ...chosen, [mode]: e.target.value });
                      onSelect?.(e.target.value);
                    }}
                  >
                    {items.map((c, i) => (
                      <option key={c.id} value={c.id}>
                        صورة {i + 1} · {timestamp(c)}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              {image ? (
                <figure>
                  <button
                    className="capture-image-button"
                    aria-label={selectionPurpose === "preview" ? `عرض ${mode === "rgb" ? "الصورة العادية" : "الصورة الحرارية"} من وصول الدرون` : `اختيار ${mode === "rgb" ? "الصورة العادية" : "الصورة الحرارية"} للمراجعة`}
                    aria-pressed={image.id === activeId}
                    onClick={() => onSelect?.(image.id)}
                    disabled={!onSelect}
                  >
                    <img
                      src={image.image_url || "/api/files/" + image.file}
                      alt={
                        image.note ||
                        (mode === "rgb"
                          ? "صورة RGB من الجولة"
                          : "الصورة الحرارية من الجولة")
                      }
                    />
                  </button>
                  <figcaption>
                    <span>{sources[image.source] || image.source}</span>
                    <span>{timestamp(image)}</span>
                  </figcaption>
                </figure>
              ) : (
                <div className="capture-placeholder">
                  <Icon size={34} />
                  <strong>
                    {mode === "rgb"
                      ? "لم تُرفع صورة عادية"
                      : "لم تُرفع صورة حرارية"}
                  </strong>
                  <p>أضف الصورة من الجولة نفسها لتظهر هنا.</p>
                  {onUpload && (
                    <button onClick={onUpload}>
                      <Upload size={15} />
                      إضافة صورة
                    </button>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>
      <p className="capture-pair-note">
        {captures.some((capture) => capture.transient) ? (
          <>صور مُعدّة للعرض، تختفي عند تحديث الصفحة. الصور الحرارية لونية بلا قياسات حرارة رقمية.</>
        ) : captures.some((capture) => capture.asset_pack === "saddle-gallery-v33") ? (
          <>صور مرجعية مُعدّة للعرض؛ الصورة الحرارية لونية بلا قياسات حرارة رقمية.</>
        ) : (
          <>الصورتان من الجولة نفسها؛ لا يفترض العرض تطابق زاوية التصوير. الحرارة الرقمية تظهر عند رفع مصفوفة قياس.</>
        )}
      </p>
    </>
  );
}
