export default function MetricIcon({ channel }: { channel: string }) {
  return (
    <svg
      className={`metric-icon ${channel}`}
      width="32"
      height="32"
      viewBox="0 0 32 32"
      fill="none"
      strokeWidth="2.1"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {channel === "temperature" ? (
        <>
          <path
            d="M13 20V7a3 3 0 0 1 6 0v13a6 6 0 1 1-6 0Z"
            stroke="#535DC2"
            fill="#EFF0FE"
          />
          <path d="M16 12v12" stroke="#D57B7D" />
          <circle cx="16" cy="24" r="3" fill="#D57B7D" />
          <path d="M23 8h3M23 13h2M23 18h3" stroke="#A98CF6" />
        </>
      ) : channel === "wetness" ? (
        <>
          <path
            d="M8 17a5 5 0 1 1 2-9 7 7 0 0 1 13 2 4 4 0 0 1 1 8H8Z"
            fill="#E9EBFF"
            stroke="#6772E8"
          />
          <path d="m11 22-2 4m9-4-2 4m9-4-2 4" stroke="#6772E8" />
          <path d="m15 20-1 3" stroke="#A98CF6" />
        </>
      ) : channel === "hoop" ? (
        <>
          <ellipse
            cx="16"
            cy="16"
            rx="9"
            ry="11"
            stroke="#A98CF6"
            fill="#F3EEFF"
          />
          <path
            d="m5 16 4-3m-4 3 4 3m18-3-4-3m4 3-4 3M12 16h8"
            stroke="#6772E8"
          />
        </>
      ) : (
        <>
          <path d="M3 17h7l4-10 5 19 4-9h6" stroke="#6772E8" />
          <path d="m14 7 5 19" stroke="#D57B7D" />
          <circle cx="14" cy="7" r="2" fill="#F280A4" stroke="none" />
        </>
      )}
    </svg>
  );
}
