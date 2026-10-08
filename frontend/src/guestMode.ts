// Visitor mode reads only the public, deterministic LPG display snapshots.
// It never creates an admin session or sends a stored credential to the server.
export const STATIC_GUEST_BUILD = import.meta.env.VITE_QAIF_GUEST_MODE === 'true';
const selection = 'qaif.lpg.visitor';
const selected = () => {
  try { return sessionStorage.getItem(selection) === '1'; }
  catch { return false; }
};
export let GUEST_MODE = STATIC_GUEST_BUILD || selected();

export function enterGuestMode() {
  try { sessionStorage.setItem(selection, '1'); } catch { /* Private browsing can disable storage. */ }
  GUEST_MODE = true;
}

export function leaveGuestMode() {
  try { sessionStorage.removeItem(selection); } catch { /* The in-memory flag still clears. */ }
  GUEST_MODE = STATIC_GUEST_BUILD;
}
