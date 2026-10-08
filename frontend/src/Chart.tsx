import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
echarts.use([
  LineChart,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

export default function Chart({
  episode,
  channel,
  profile = 'pipe',
}: {
  episode: any;
  channel: string;
  profile?: 'pipe' | 'shipment';
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !episode) return;
    const chart = echarts.init(ref.current);
    const keys: { [k: string]: [string, string, string] } = {
      strain: ["strain_axial_microstrain", "الانفعال المحوري", "με"],
      hoop: ["strain_hoop_microstrain", "الانفعال المحيطي", "με"],
      temperature: ["temperature_k", "الحرارة", "°C"],
      wetness: ["wetness_index", "البلل", "مؤشر"],
      gas: ["h2s_ppm", "غاز H₂S", "ppm"],
    };
    const shipmentKeys: { [k: string]: [string, string, string] } = {
      strain: ['mount_strain_a', 'انفعال التثبيت A', 'µε'],
      hoop: ['mount_strain_b', 'انفعال التثبيت B', 'µε'],
      temperature: ['mount_temperature_C', 'حرارة موضع السراج', '°C'],
      gas: ['lpg_ppm', 'قناة LPG', 'ppm'],
      shock: ['acceleration_g', 'تسارع القفص', 'g'],
      latch: ['latch_closed', 'حالة القفل', '0 / 1'],
    };
    const [key, label, unit] = (profile === 'shipment' ? shipmentKeys : keys)[channel];
    const shipment = profile === 'shipment';
    const divisor = shipment ? 60 : 3600;
    const timeUnit = shipment ? 'دقيقة' : 'ساعة';
    const startTime = episode.simulation_clock
      ? 0
      : episode.rows[0]?.timestamp_s || 0;
    const data = episode.rows.map((row: any) => [
      (row.timestamp_s - startTime) / divisor,
      row.packet_valid && row[key] != null && (channel !== "gas" || (shipment ? row.lpg_valid : row.h2s_valid))
        ? key === "temperature_k"
          ? row[key] - 273.15
          : typeof row[key] === 'boolean' ? Number(row[key]) : row[key]
        : null,
    ]);
    const reference = episode.reference_rows?.map((row: any) => [
      (row.timestamp_s - startTime) / 3600,
      row.packet_valid && row[key] != null && (channel !== "gas" || row.h2s_valid)
        ? key === "temperature_k"
          ? row[key] - 273.15
          : row[key]
        : null,
    ]);
    chart.setOption({
      animation: false,
      color: [
        shipment && channel === 'gas' ? '#b96526' : shipment && channel === 'shock' ? '#8062ad' : channel === "temperature"
          ? "#BD6978"
          : channel === "wetness"
            ? "#6772E8"
            : channel === "hoop"
              ? "#9874D4"
              : "#6772E8",
      ],
      textStyle: { fontFamily: "IBM Plex Sans Arabic" },
      tooltip: {
        trigger: "axis",
        formatter: (params: any) =>
          `${Number(params[0].value[0]).toFixed(1)} ${timeUnit}<br/>${label}: ${params[0].value[1] === null ? "حزمة مفقودة" : Number(params[0].value[1]).toFixed(2)} ${unit}`,
      },
      grid: { left: 58, right: 26, top: 32, bottom: 65 },
      legend: {
        show: !!reference,
        top: 0,
        right: 30,
        data: [label, "التشغيل المرجعي المطابق"],
      },
      xAxis: {
        type: "value",
        name: `الزمن المنقضي (${timeUnit})`,
        nameLocation: "middle",
        nameGap: 40,
        nameTextStyle: { color: "#65627A" },
        axisLabel: { color: "#65627A" },
        axisLine: { lineStyle: { color: "#E4E2EE" } },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        name: unit,
        axisLabel: { color: "#65627A" },
        nameTextStyle: { color: "#65627A" },
        splitLine: { lineStyle: { color: "#F0EDF8" } },
      },
      dataZoom: [{ type: "inside" }],
      series: [
        {
          type: "line",
          name: label,
          data,
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 2 },
          areaStyle: { opacity: 0.05 },
        },
        ...(reference
          ? [
              {
                type: "line",
                name: "التشغيل المرجعي المطابق",
                data: reference,
                showSymbol: false,
                connectNulls: false,
                lineStyle: { width: 1.5, type: "dashed", color: "#9D94B6" },
              },
            ]
          : []),
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [episode, channel, profile]);
  return (
    <div
      className="chart"
      ref={ref}
      role="img"
      aria-label={`رسم القراءات مقابل الزمن المنقضي ${profile === 'shipment' ? 'بالدقائق' : 'بالساعات'}؛ الحزم المفقودة تظهر كفجوات`}
    />
  );
}
