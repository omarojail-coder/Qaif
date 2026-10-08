"""Single-process cloud entry point; accepts the hosting provider's PORT."""
import os
import sys
from pathlib import Path


def command():
    port = int(os.getenv('PORT') or os.getenv('QAIF_PORT', '8765'))
    if not 1 <= port <= 65535:
        raise ValueError('PORT must be between 1 and 65535')
    return [sys.executable, '-m', 'uvicorn', 'backend.app:app', '--host', '0.0.0.0',
            '--port', str(port), '--workers', '1', '--proxy-headers',
            '--forwarded-allow-ips', os.getenv('FORWARDED_ALLOW_IPS', '127.0.0.1')]


if __name__ == '__main__':
    # A newly mounted persistent disk can be owned by root. Initialize only the
    # configured /data directory, then drop privileges before importing the app.
    if getattr(os, 'geteuid', lambda: -1)() == 0:
        import pwd
        directory = Path(os.getenv('QAIF_DATA_DIR', '/data')).resolve()
        if not directory.is_relative_to(Path('/data')):
            raise RuntimeError('The container data directory must be /data or a subdirectory')
        account = pwd.getpwnam('qaif')
        directory.mkdir(parents=True, exist_ok=True)
        os.chown(directory, account.pw_uid, account.pw_gid)
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    os.execv(sys.executable, command())
