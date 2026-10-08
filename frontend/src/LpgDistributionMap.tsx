import { useEffect, useRef, useState } from "react";
import maplibregl, { type Map as GLMap, type GeoJSONSource, type Marker } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { LocateFixed, Pause, Play, Satellite, Truck } from "lucide-react";
import { flightPoint, travelledPath } from "./droneFlight";
import { polygons } from "./geoRoutes";
import { STATIONS, STATION_SVG, TRUCK_SVG, TRIP_STATUS, tripProgress, type ShipmentTrip, type Store } from "./lpgMapData";

const COUNTRY: [[number,number],[number,number]] = [[34.4,16.25],[55.7,32.25]];
const collection = (features: any[] = []) => ({ type: "FeatureCollection", features }) as any;
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const colorExpression: any = ["match", ["get","station_id"], ...STATIONS.flatMap(s=>[s.id,s.color]), "#6772E8"];
type Props = { boundary: any; areas: any; stores: Store[]; trips: ShipmentTrip[]; stationId: string; alertsOnly: boolean; onStation: (id:string)=>void; onTrip: (trip:ShipmentTrip)=>void; onClock?: (seconds:number)=>void };

export default function LpgDistributionMap(props: Props) {
  const host = useRef<HTMLDivElement>(null), map = useRef<GLMap|null>(null), current = useRef(props);
  current.current = props;
  const vehicles = useRef(new Map<string,{ marker: Marker; element: HTMLButtonElement; trip: ShipmentTrip }>());
  const fixedMarkers = useRef<Marker[]>([]), popup = useRef<maplibregl.Popup|null>(null), elapsed = useRef(0);
  const [ready,setReady] = useState(false), [error,setError] = useState(""), [tileError,setTileError] = useState(false);
  const [showAreas,setShowAreas] = useState(true), [showStores,setShowStores] = useState(true), [paused,setPaused] = useState(false);
  const [reduced,setReduced] = useState(reducedMotion), [zoom,setZoom] = useState(4.5);
  const motion = useRef({paused,reduced}); motion.current = {paused,reduced};
  const { boundary,areas,stores,trips,stationId,alertsOnly,onStation } = props;

  const countryPadding = () => ({ top:35, bottom:(host.current?.clientWidth ?? 900)<640?165:35, left:35, right:35 });
  const reset = () => map.current?.fitBounds(COUNTRY,{ padding:countryPadding(), duration:reduced ? 0 : 650 });
  useEffect(()=>{
    const media=matchMedia("(prefers-reduced-motion: reduce)");
    const change=()=>setReduced(media.matches); media.addEventListener("change",change);
    return ()=>media.removeEventListener("change",change);
  },[]);

  useEffect(()=>{
    if(!host.current) return;
    let alive=true, instance: GLMap|undefined, observer: ResizeObserver|undefined;
    setReady(false); setError("");
    try {
      const outside={type:"Feature",properties:{},geometry:{type:"Polygon",coordinates:[[[10,-10],[75,-10],[75,55],[10,55],[10,-10]],...polygons(boundary.geometry).map(p=>[...p[0]].reverse())]}};
      const storeFeatures=stores.map(s=>({type:"Feature",properties:{id:s.id,name:s.name,city:s.city,station_id:s.stationId},geometry:{type:"Point",coordinates:s.position}}));
      instance=new maplibregl.Map({
        container:host.current,center:[44.7,24.3],zoom:4.5,minZoom:3,maxZoom:16,maxBounds:[[20,-5],[70,50]],
        attributionControl:false,renderWorldCopies:false,dragRotate:false,pitchWithRotate:false,
        canvasContextAttributes:{preserveDrawingBuffer:true},
        locale:{"NavigationControl.ZoomIn":"تكبير الخريطة","NavigationControl.ZoomOut":"تصغير الخريطة","AttributionControl.ToggleAttribution":"مصادر الخريطة","Popup.Close":"إغلاق تفاصيل المتجر"},
        style:{version:8,sources:{
          satellite:{type:"raster",tiles:["https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],tileSize:256,maxzoom:19,attribution:"Imagery: Esri, Vantor, Earthstar Geographics · Boundaries: Natural Earth"},
          boundary:{type:"geojson",data:boundary},outside:{type:"geojson",data:outside as any},areas:{type:"geojson",data:areas},
          stores:{type:"geojson",data:collection(storeFeatures)},routes:{type:"geojson",data:collection()},covered:{type:"geojson",data:collection()},
        },layers:[
          {id:"background",type:"background",paint:{"background-color":"#283337"}},
          {id:"satellite",type:"raster",source:"satellite",paint:{"raster-saturation":-0.28,"raster-brightness-max":0.83}},
          {id:"outside",type:"fill",source:"outside",paint:{"fill-color":"#151a2a","fill-opacity":0.64}},
          {id:"service-fill",type:"fill",source:"areas",paint:{"fill-color":colorExpression,"fill-opacity":0.36}},
          {id:"service-borders",type:"line",source:"areas",paint:{"line-color":"#fff","line-opacity":0.5,"line-width":1}},
          {id:"saudi-border",type:"line",source:"boundary",paint:{"line-color":"#ede6f6","line-width":1.2,"line-opacity":0.8}},
          {id:"route-halo",type:"line",source:"routes",layout:{"line-cap":"round","line-join":"round"},paint:{"line-color":"#fff","line-opacity":0.7,"line-width":6}},
          {id:"route-plan",type:"line",source:"routes",layout:{"line-cap":"round","line-join":"round"},paint:{"line-color":"#5d56a4","line-width":2.5,"line-dasharray":[3,2]}},
          {id:"route-covered",type:"line",source:"covered",layout:{"line-cap":"round","line-join":"round"},paint:{"line-color":["case",["==",["get","status"],"alert"],"#b43e58","#535dc2"],"line-width":3.2}},
          {id:"store-halo",type:"circle",source:"stores",paint:{"circle-radius":["interpolate",["linear"],["zoom"],4,3,8,5,12,7],"circle-color":"#fff","circle-opacity":0.9}},
          {id:"store-points",type:"circle",source:"stores",paint:{"circle-radius":["interpolate",["linear"],["zoom"],4,1.6,8,3,12,5],"circle-color":"#403863"}},
        ]},
      });
      map.current=instance;
      instance.addControl(new maplibregl.NavigationControl({showCompass:false}),"top-left");
      instance.addControl(new maplibregl.ScaleControl({maxWidth:85,unit:"metric"}),"bottom-left");
      instance.addControl(new maplibregl.AttributionControl({compact:true}),"bottom-left");
      instance.touchZoomRotate.disableRotation();
      instance.getCanvas().setAttribute("aria-label","خريطة محطات غازكو ومناطق الخدمة والمتاجر ورحلات سراج");
      instance.fitBounds(COUNTRY,{padding:countryPadding(),duration:0});
      instance.on("load",()=>{ if(alive){setReady(true);setZoom(instance!.getZoom());} });
      instance.on("zoomend",()=>{if(alive)setZoom(instance!.getZoom());});
      instance.on("error",event=>{if(alive && (event as any).sourceId==="satellite")setTileError(true);});
      instance.on("sourcedata",event=>{if(alive && event.sourceId==="satellite" && event.isSourceLoaded)setTileError(false);});
      instance.on("click","service-fill",event=>{
        if((event.originalEvent.target as Element)?.closest(".maplibregl-marker,.maplibregl-popup"))return;
        const id=event.features?.[0]?.properties?.station_id;
        if(STATIONS.some(s=>s.id===id))current.current.onStation(id);
      });
      instance.on("click","store-points",event=>{
        const item=event.features?.[0]; if(!item)return;
        event.preventDefault();
        const text=document.createElement("div"); text.className="lpg-store-popup"; text.dir="rtl";
        const name=document.createElement("strong"); name.textContent=item.properties.name;
        const info=document.createElement("p"); info.textContent=`${STATIONS.find(s=>s.id===item.properties.station_id)?.name} · موقع عرض تقريبي`;
        text.append(name,info); popup.current?.remove();
        popup.current=new maplibregl.Popup({offset:12}).setLngLat((item.geometry as any).coordinates).setDOMContent(text).addTo(instance!);
      });
      for(const layer of ["service-fill","store-points"]){
        instance.on("mouseenter",layer,()=>{instance!.getCanvas().style.cursor="pointer";});
        instance.on("mouseleave",layer,()=>{instance!.getCanvas().style.cursor="";});
      }
      observer=new ResizeObserver(()=>instance?.resize()); observer.observe(host.current);
    } catch { setError("تعذر فتح الخريطة الجغرافية. أعد تحميل الصفحة."); }
    return ()=>{alive=false;observer?.disconnect();popup.current?.remove();fixedMarkers.current.forEach(m=>m.remove());fixedMarkers.current=[];vehicles.current.forEach(v=>v.marker.remove());vehicles.current.clear();instance?.remove();map.current=null;};
  },[boundary,areas,stores]);

  useEffect(()=>{
    const m=map.current; if(!m || !ready)return;
    m.setLayoutProperty("service-fill","visibility",showAreas?"visible":"none");
    m.setLayoutProperty("service-borders","visibility",showAreas?"visible":"none");
    for(const layer of ["store-halo","store-points"]){
      m.setLayoutProperty(layer,"visibility",showStores?"visible":"none");
      m.setFilter(layer,stationId?["==",["get","station_id"],stationId]:null);
    }
    m.setPaintProperty("service-fill","fill-opacity",stationId?["case",["==",["get","station_id"],stationId],0.32,0.09]:0.36);
    const visible=trips.filter(t=>t.stationId===stationId && (!alertsOnly || t.status==="alert"));
    (m.getSource("routes") as GeoJSONSource).setData(collection(visible.map(t=>({type:"Feature",properties:{trip_id:t.id},geometry:{type:"LineString",coordinates:t.path}}))));
  },[ready,stationId,alertsOnly,showAreas,showStores,trips]);

  useEffect(()=>{
    const m=map.current;if(!m || !ready)return;
    fixedMarkers.current.forEach(marker=>marker.remove());fixedMarkers.current=[];
    for(const station of STATIONS){
      const button=document.createElement("button");button.className=`lpg-station-marker${stationId===station.id?" selected":""}`;
      button.style.setProperty("--station-color",station.color);button.dataset.stationId=station.id;
      button.setAttribute("aria-label",`تكبير ${station.name}`);button.title=`${station.name} · ${station.region}`;
      button.innerHTML=STATION_SVG;
      if(zoom>6 || stationId===station.id){const label=document.createElement("span");label.className="lpg-station-label";label.textContent=station.name;button.append(label);}
      button.addEventListener("click",event=>{event.stopPropagation();current.current.onStation(station.id);});
      fixedMarkers.current.push(new maplibregl.Marker({element:button}).setLngLat(station.position).addTo(m));
      if(!stationId && showAreas){
        const label=document.createElement("span");label.className="lpg-area-label";label.textContent=station.name.replace("محطة ","");label.setAttribute("aria-hidden","true");
        fixedMarkers.current.push(new maplibregl.Marker({element:label}).setLngLat(station.label).addTo(m));
      }
    }
    vehicles.current.forEach(v=>v.marker.remove());vehicles.current.clear();
    const visible=trips.filter(t=>(stationId?t.stationId===stationId:t.status==="alert") && (!alertsOnly || t.status==="alert"));
    for(const trip of visible){
      const button=document.createElement("button");button.className=`lpg-vehicle-marker ${trip.status}`;button.dataset.tripId=trip.id;
      button.setAttribute("aria-label",`فتح معلومات السرج ${trip.saddleId} · ${trip.destination.city} · ${TRIP_STATUS[trip.status]}`);
      button.title=`${trip.saddleId} · ${trip.truck} · إلى ${trip.destination.city}`;
      const body=document.createElement("span");body.className="lpg-vehicle-body";body.innerHTML=TRUCK_SVG;
      const label=document.createElement("b");label.dir="ltr";label.textContent=trip.saddleId;body.append(label);
      if(trip.status==="alert"){const pulse=document.createElement("span");pulse.className="lpg-alert-pulse";pulse.setAttribute("aria-hidden","true");button.append(pulse);}
      button.append(body);button.addEventListener("click",event=>{event.stopPropagation();current.current.onTrip({...trip,viewProgress:tripProgress(trip,elapsed.current),viewStartedMs:Date.now()});});
      const marker=new maplibregl.Marker({element:button}).setLngLat(flightPoint(trip.path,tripProgress(trip,elapsed.current))).addTo(m);
      vehicles.current.set(trip.id,{marker,element:button,trip});
    }
  },[ready,stationId,alertsOnly,zoom,showAreas,trips]);

  useEffect(()=>{
    const m=map.current;if(!m || !ready)return;
    popup.current?.remove();
    if(!stationId){reset();return;}
    const station=STATIONS.find(s=>s.id===stationId);if(!station)return;
    const bounds=new maplibregl.LngLatBounds(station.position,station.position);
    trips.filter(t=>t.stationId===stationId).forEach(t=>t.path.forEach(p=>bounds.extend(p)));
    m.fitBounds(bounds,{padding:{top:80,bottom:180,left:60,right:60},maxZoom:8.7,duration:reduced?0:750});
  },[ready,stationId,trips,reduced]);

  useEffect(()=>{
    const m=map.current;if(!m || !ready)return;
    let raf=0,previous=performance.now(),paint=0;
    const draw=(time:number)=>{
      if(map.current!==m)return;
      const delta=Math.max(0,(time-previous)/1000);previous=time;
      if(!motion.current.paused)elapsed.current+=delta;
      current.current.onClock?.(elapsed.current);
      // Match the existing drone animation: reduced motion gets infrequent position updates.
      if(time-paint>=(motion.current.reduced?1000:40)){
        const covered:any[]=[];
        vehicles.current.forEach(({marker,element,trip})=>{
          const progress=tripProgress(trip,elapsed.current),position=flightPoint(trip.path,progress);
          marker.setLngLat(position);element.dataset.position=position.join(",");element.dataset.progress=progress.toFixed(6);
          element.dataset.phase=progress>=1?"arrived":"travelling";
          if(trip.stationId===current.current.stationId)covered.push({type:"Feature",properties:{status:trip.status},geometry:{type:"LineString",coordinates:travelledPath(trip.path,progress)}});
        });
        (m.getSource("covered") as GeoJSONSource | undefined)?.setData(collection(covered));paint=time;
      }
      raf=requestAnimationFrame(draw);
    };
    raf=requestAnimationFrame(draw);return()=>cancelAnimationFrame(raf);
  },[ready]);

  return <section className="lpg-map-panel" aria-label="خريطة توزيع الغاز ومراقبة الشحنات">
    <div className="lpg-map-heading"><strong><Satellite size={17}/>شبكة توزيع الغاز · المملكة العربية السعودية</strong><span>Satellite · أقمار صناعية</span></div>
    <div className="lpg-map-frame">
      <div ref={host} className="lpg-map-canvas" role="region" aria-label="خريطة تفاعلية لمحطات غازكو"/>
      {!ready && !error && <p className="lpg-map-message" role="status">جاري فتح الخريطة…</p>}
      {error && <p className="lpg-map-message" role="alert">{error}</p>}
      {tileError && <p className="lpg-tile-error" role="status">تعذر تحميل صور الأقمار؛ مناطق الخدمة والنقاط متاحة.</p>}
      <div className="lpg-map-controls">
        <label><input type="checkbox" checked={showAreas} onChange={e=>setShowAreas(e.target.checked)}/>مناطق الخدمة</label>
        <label><input type="checkbox" checked={showStores} onChange={e=>setShowStores(e.target.checked)}/>المتاجر</label>
      </div>
      <button className="lpg-country-fit" aria-label="عرض المملكة كاملة" title="عرض المملكة كاملة" onClick={()=>{if(stationId)onStation("");else reset();}}><LocateFixed size={18}/></button>
      <aside className="lpg-map-key" aria-label="مفتاح خريطة توزيع الغاز">
        <strong>مفتاح الخريطة</strong>
        <div className="lpg-symbol-key"><span><i className="lpg-symbol-station"/>محطة تعبئة</span><span><i className="lpg-symbol-store"/>متجر غاز</span><span><i className="lpg-symbol-route"/>مسار شاحنة</span></div>
        <div className="lpg-status-key"><span><i className="lpg-state-dot healthy"/>دون تنبيه</span><span><i className="lpg-state-dot alert"/>شذوذ قوي</span><span><i className="lpg-state-dot unknown"/>قراءات ناقصة</span></div>
        <div className="lpg-region-key">{STATIONS.map(s=><button key={s.id} className={stationId===s.id?"active":""} onClick={()=>onStation(s.id)} aria-label={`عرض نطاق ${s.name}`}><i style={{background:s.color}}/>{s.name.replace("محطة ","")}</button>)}</div>
      </aside>
    </div>
    <div className="lpg-motion-bar"><span><Truck size={16}/>{stationId ? "رحلات المحطة المختارة" : "اختر محطة لعرض مسارات سراج والشاحنات"}</span><button onClick={()=>setPaused(v=>!v)} aria-pressed={paused}>{paused?<Play size={14}/>:<Pause size={14}/>} {paused?"تشغيل الحركة":"إيقاف الحركة"}</button></div>
    <p className="lpg-map-footnote">مناطق الخدمة ومواقع المتاجر ومسارات الرحلات تقديرية للعرض، والتنبيهات من بيانات العرض. المواقع لا تمثل عناوين تشغيلية معتمدة.</p>
  </section>;
}
