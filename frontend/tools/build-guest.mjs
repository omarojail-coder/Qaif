import { spawnSync } from 'node:child_process';

// Explicitly select visitor mode even if Vercel system environment variables
// were disabled in the project's dashboard. No secrets or env setup required.
const checked = spawnSync(process.execPath, ['node_modules/typescript/bin/tsc', '-b'], { stdio: 'inherit' });
if (checked.status !== 0) process.exit(checked.status ?? 1);
const built = spawnSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build', '--configLoader', 'runner', ...process.argv.slice(2)], {
  stdio: 'inherit', env: { ...process.env, VITE_QAIF_GUEST_MODE: 'true' },
});
process.exit(built.status ?? 1);
