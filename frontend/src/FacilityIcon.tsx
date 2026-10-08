export const FACILITY_PATHS = {
  gas: "M6 21V11a3 3 0 0 1 6 0v10ZM20 21V7a3 3 0 0 1 6 0v14ZM9 21v5M23 21v5M4 26h24M12 16h2M18 16h2M18 16a2 2 0 1 0-4 0 2 2 0 0 0 4 0ZM16 14v-3M14 11h4",
  refinery:
    "M7 25V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v19M5 10h10M5 16h10M5 22h10M19 25v-7a4 4 0 0 1 8 0v7ZM19 21h8M13 25h6M3 28h26",
};
export const FACILITY_COLORS = { gas: "#16805E", refinery: "#356FE0" };

export function facilityIconSvg(type: string) {
  const kind = type === "refinery" ? "refinery" : "gas";
  return `<svg viewBox="0 0 32 32" aria-hidden="true" fill="none" stroke="${FACILITY_COLORS[kind]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${FACILITY_PATHS[kind]}"/></svg>`;
}

// Lucide Layers2 (ISC), matching the icon library already used by the app.
export function facilityGroupSvg() {
  return '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m16.02 12 5.48 3.13a1 1 0 0 1 0 1.74L13 21.74a2 2 0 0 1-2 0l-8.5-4.87a1 1 0 0 1 0-1.74L7.98 12"/><path d="M13 13.74a2 2 0 0 1-2 0L2.5 8.87a1 1 0 0 1 0-1.74L11 2.26a2 2 0 0 1 2 0l8.5 4.87a1 1 0 0 1 0 1.74Z"/></svg>';
}
export default function FacilityIcon({
  type,
  size = 24,
  className = "",
}: {
  type: string;
  size?: number;
  className?: string;
}) {
  const kind = type === "refinery" ? "refinery" : "gas";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      className={className}
      fill="none"
      stroke={FACILITY_COLORS[kind]}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={FACILITY_PATHS[kind]} />
    </svg>
  );
}
