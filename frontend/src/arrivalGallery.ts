export type GalleryImage = { url: string; note: string };
export type ArrivalGallery = { rgb: GalleryImage[]; thermal: GalleryImage[] };

const image = (id: string, variant: string, mode: "rgb" | "thermal", note: string): GalleryImage => ({
  url: `/drone-gallery-v37/${id.toLowerCase().replace("-", "")}-${variant}-${mode}.png`, note,
});
const gallery = (id: string, rgbNote: string, thermalNote: string): ArrivalGallery => ({
  rgb: ["a", "b"].map(variant => image(id, variant, "rgb", rgbNote)),
  thermal: ["a", "b"].map(variant => image(id, variant, "thermal", thermalNote)),
});

// Only metadata is loaded here. The concealed library renders no thumbnails and loads no images until arrival.
export const ARRIVAL_GALLERIES: Record<string, ArrivalGallery> = {
  "S-1": gallery("S-1", "صورة مُعدّة للعرض: تضرر موضعي في طلاء أنبوب بقيق.", "صورة حرارية توضيحية: توزيع حراري غير منتظم قرب الوصلة؛ بلا قياسات رقمية."),
  "S-12": gallery("S-12", "صورة مُعدّة للعرض: تغير لون وتآكل سطحي قرب فلنجة أنبوب الجبيل.", "صورة حرارية توضيحية: بقعة أكثر سخونة قرب الفلنجة؛ بلا قياسات رقمية."),
  "S-8": gallery("S-8", "صورة مُعدّة للعرض: أثر شق محتمل وتقشر طلاء قرب لحام أنبوب حرض–الحوية.", "صورة حرارية توضيحية: توزيع متجانس نسبيًا، دون إثبات سلامة ميكانيكية أو درجات حرارة مقاسة."),
  "S-4": gallery("S-4", "صورة مُعدّة للعرض: أنبوب القطاع الأوسط دون عيب سطحي ظاهر.", "صورة حرارية توضيحية: توزيع حراري متجانس نسبيًا؛ بلا قياسات رقمية."),
  "S-3": gallery("S-3", "صورة مُعدّة للعرض: أنبوب رأس تنورة دون عيب سطحي ظاهر.", "صورة حرارية توضيحية: توزيع متجانس نسبيًا؛ بلا قياسات رقمية."),
  "S-5": gallery("S-5", "صورة مُعدّة للعرض: أنبوب شرق بترولاين دون عيب سطحي ظاهر.", "صورة حرارية توضيحية: توزيع متجانس نسبيًا؛ بلا قياسات رقمية."),
  "S-6": gallery("S-6", "صورة مُعدّة للعرض: أنبوب مسار الشيبة دون عيب سطحي ظاهر.", "صورة حرارية توضيحية: توزيع متجانس نسبيًا؛ بلا قياسات رقمية."),
  "S-7": gallery("S-7", "صورة مُعدّة للعرض: أنبوب ينبع دون عيب سطحي ظاهر.", "صورة حرارية توضيحية: توزيع متجانس نسبيًا؛ بلا قياسات رقمية."),
};
