"""Stop only the launcher-owned QAIF process and its verified Python child."""
import json
import os
from pathlib import Path
import psutil

root=Path(__file__).resolve().parents[1]
pid_file=root/'data'/'server.pid'
if not pid_file.exists():
    print('No launcher-managed server found.'); raise SystemExit(0)
try: process=psutil.Process(int(pid_file.read_text().strip()))
except psutil.NoSuchProcess:
    print('Server is already stopped.'); raise SystemExit(0)
expected=(root/'.venv'/'Scripts'/'python.exe').resolve()
if Path(process.exe()).resolve()!=expected or 'backend.app:app' not in process.cmdline() or '8765' not in process.cmdline():
    raise SystemExit('PID is not the expected QAIF launcher. Nothing was stopped.')
children=[]
for child in process.children(recursive=True):
    if Path(child.exe()).resolve()==(Path(os.environ.get('WINDIR','C:/Windows'))/'System32'/'conhost.exe').resolve():
        continue
    if 'backend.app:app' not in child.cmdline() or '8765' not in child.cmdline():
        raise SystemExit('Unexpected child process. Nothing was stopped.')
    children.append(child)
for child in reversed(children): child.terminate()
process.terminate()
psutil.wait_procs([*children,process],timeout=5)
print('QAIF stopped. Stored evidence is preserved.')
