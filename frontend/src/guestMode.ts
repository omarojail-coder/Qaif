// Vercel builds select a public, read-only scenario viewer. Server builds keep
// their existing authentication and API; this flag never changes backend access.
export const GUEST_MODE = import.meta.env.VITE_QAIF_GUEST_MODE === 'true';
