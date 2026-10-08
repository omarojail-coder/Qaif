import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, Factory, MapPin, Search, Store as StoreIcon, TriangleAlert, Truck } from "lucide-react";
import LpgDistributionMap from "./LpgDistributionMap";
import { NETWORK_STORE_ESTIMATE, STATIONS, TRIP_STATUS, makeStores, makeTrips, tripProgress, type ShipmentTrip } from "./lpgMapData";
import { DISPLAY_LOCALE } from "./locale";
import "./lpg-map.css";

const n=(value:number)=>value.toLocaleString(DISPLAY_LOCALE);
export default function LpgMapPage({onTrip}:{onTrip:(trip:ShipmentTrip)=>void}) {
  const mapElapsed = useRef(0);
  const openTrip = (trip:ShipmentTrip) => onTrip({...trip,viewProgress:trip.viewProgress ?? tripProgress(trip,mapElapsed.current),viewStartedMs:trip.viewStartedMs ?? Date.now()});
  const [geography,setGeography]=useState<{boundary:any;areas:any}|null>(null),[error,setError]=useState("");
  const [retry,setRetry]=useState(0),[stationId,setStationId]=useState(""),[alertsOnly,setAlertsOnly]=useState(false),[search,setSearch]=useState("");
  useEffect(()=>{
    let alive=true;setError("");
    const read=async(url:string)=>{const response=await fetch(url);if(!response.ok)throw Error("geography");return response.json();};
    Promise.all([read("/saudi-boundary.geojson"),read("/gasco-service-areas.geojson")]).then(([boundary,areas])=>{
      if(areas.features.length<7 || !boundary.geometry)throw Error("geography");
      if(alive)setGeography({boundary,areas});
    }).catch(()=>{if(alive)setError("تعذر تحميل بيانات الخريطة. أعد المحاولة.");});
    return()=>{alive=false;};
  },[retry]);
  const stores=useMemo(()=>geography?makeStores(geography.boundary.geometry,geography.areas):[],[geography]);
  const trips=useMemo(()=>geography?makeTrips(stores,geography.boundary.geometry):[],[stores,geography]);
  const alertCount=trips.filter(t=>t.status==="alert").length;
  const station=STATIONS.find(s=>s.id===stationId);
  const visibleTrips=trips.filter(t=>t.stationId===stationId && (!alertsOnly || t.status==="alert"));
  const selectStation=(id:string)=>{setStationId(id);};

  return <div className="workspace lpg-workspace" data-testid="lpg-map-workspace">
    <div className="stage">
      <div className="summary-strip lpg-summary" aria-label="إحصائيات شبكة التوزيع">
        <div><TriangleAlert className="red-text"/><span>أسرجة بشذوذ قوي<small>تحتاج فحصًا عند الوصول</small></span><strong className="lpg-alert-number">{geography?n(alertCount):"—"}</strong></div>
        <div><StoreIcon/><span>متاجر توزيع الغاز<small>حوالي {n(NETWORK_STORE_ESTIMATE)} · {n(stores.length)} موقعًا معروضًا</small></span><strong>{n(NETWORK_STORE_ESTIMATE)}</strong></div>
      </div>
      <div className="lpg-filters">
        <label>المحطة<select value={stationId} onChange={e=>selectStation(e.target.value)} aria-label="تصفية حسب محطة غازكو"><option value="">كل المحطات</option>{STATIONS.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>حالة السرج<select value={alertsOnly?"alerts":"all"} onChange={e=>setAlertsOnly(e.target.value==="alerts")} aria-label="تصفية حسب حالة السرج"><option value="all">جميع الحالات</option><option value="alerts">الشذوذ القوي فقط</option></select></label>
        <span className="lpg-scenario-label">بيانات العرض</span>
      </div>
      {geography?<LpgDistributionMap boundary={geography.boundary} areas={geography.areas} stores={stores} trips={trips} stationId={stationId} alertsOnly={alertsOnly} onStation={selectStation} onTrip={openTrip} onClock={seconds=>{mapElapsed.current=seconds;}}/>:<div className="panel lpg-loading" role={error?"alert":"status"}>{error || "جاري تجهيز مناطق المحطات…"}{error && <button onClick={()=>setRetry(v=>v+1)}>إعادة المحاولة</button>}</div>}
      {station?<section className="panel lpg-station-detail" aria-label="رحلات المحطة المختارة">
        <div className="panel-heading"><div><h3><Factory size={19}/>{station.name}</h3><p>{station.service}</p></div><button onClick={()=>selectStation("")}><MapPin size={15}/>كل المحطات</button></div>
        <div className="lpg-trip-list" aria-label="قائمة رحلات سراج">{visibleTrips.map(trip=><button key={trip.id} onClick={()=>openTrip(trip)} className={`lpg-trip-row ${trip.status}`} aria-label={`تفاصيل رحلة ${trip.saddleId}`}><Truck size={22}/><div><strong><b dir="ltr">{trip.saddleId}</b><span>إلى {trip.destination.city}</span></strong><small><b dir="ltr">{trip.truck}</b> · {TRIP_STATUS[trip.status]}</small></div><ChevronLeft size={17}/></button>)}</div>
        {!visibleTrips.length && <p className="lpg-empty">لا توجد رحلة بشذوذ قوي ضمن هذه المحطة في بيانات العرض.</p>}
      </section>:<div className="lpg-selection-hint"><MapPin size={18}/><p>اضغط على محطة أو نطاق خدمة لعرض رحلاتها. اضغط على الشاحنة لفتح معلومات سراج الشحنة.</p></div>}
    </div>
    <aside className="list-rail lpg-station-rail" aria-label="دليل المحطات">
      <div className="list-heading"><h2>دليل المحطات</h2><span className="lpg-count" dir="ltr">7</span></div>
      <p className="lpg-rail-subtitle">محطات تعبئة وتوزيع الغاز · غازكو</p>
      <label className="search-box lpg-station-search"><Search size={17}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="ابحث عن محطة…" aria-label="البحث في دليل المحطات"/></label>
      <div className="lpg-station-list">{STATIONS.filter(s=>`${s.name} ${s.region} ${s.service}`.includes(search.trim())).map(s=>{
        const assigned=trips.filter(t=>t.stationId===s.id),alerted=assigned.filter(t=>t.status==="alert").length;
        return <button key={s.id} className={`lpg-station-row${stationId===s.id?" active":""}`} onClick={()=>selectStation(s.id)} aria-label={`اختيار ${s.name}`} aria-pressed={stationId===s.id}>
          <span className="lpg-station-row-icon" style={{color:s.color}}><Factory size={23}/></span>
          <div><strong>{s.name}</strong><small>{s.id==="abha"?"خميس مشيط · المنطقة الجنوبية":s.region}</small><span className="lpg-rail-trip-count">{n(assigned.length)} رحلات{alerted>0 && <b className="lpg-rail-alert">{n(alerted)} شذوذ</b>}</span></div><ChevronLeft size={16}/>
        </button>;
      })}</div>
      <div className="lpg-rail-note"><strong>مراقبة الشحنة حتى الوصول</strong><p>عند ظهور شذوذ قوي، تُعلّم منطقة الحمولة للفحص عند الاستلام.</p><small>أبها: محطة الجنوب في خميس مشيط. نطاقات الخدمة المعروضة تقديرية.</small></div>
    </aside>
  </div>;
}
