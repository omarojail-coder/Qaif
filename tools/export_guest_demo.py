"""Export only deterministic LPG display scenarios for the static visitor site.

No Store is opened: operator records, credentials and local database contents
never enter these files. Run from the repository root with the project Python.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.lpg_cylinders import cylinder_catalog, cylinder_passport
from backend.lpg_demo import shipment_demo
from backend.lpg_inspections import ensure_demo_inspections, inspection_evidence
from backend.lpg_reports import customer_report


class DemoSeeds:
    def __init__(self):
        self.tasks = {}

    def get(self, kind, identifier):
        return self.tasks.get(identifier)

    def put(self, kind, value, **kwargs):
        self.tasks[value['id']] = value


def export():
    folder = ROOT / 'frontend' / 'public' / 'guest-data'
    folder.mkdir(parents=True, exist_ok=True)

    def write(name, value):
        (folder / name).write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n', encoding='utf-8')

    seeds = DemoSeeds()
    ensure_demo_inspections(seeds)
    tasks = list(seeds.tasks.values())
    write('catalog.json', cylinder_catalog())
    write('inspections.json', {'tasks': tasks, 'evidence': {t['id']: inspection_evidence(t) for t in tasks}})
    for number in range(1, 22):
        serials = [f'CYL-{number:03d}-{position:02d}' for position in range(1, 10)]
        reports = {serial: customer_report(serial, tasks) for serial in serials}
        for report in reports.values():
            # A saved scenario snapshot, not a freshly observed field result.
            report['generated_at'] = '2026-10-08T09:00:00+03:00'
        write(f'seraj-{number}.json', {
            'demo': shipment_demo(number),
            'passports': {serial: cylinder_passport(serial) for serial in serials},
            'reports': reports,
        })
    print(f'Exported 21 display scenarios, 189 passports and 6 inspection seeds ({sum(p.stat().st_size for p in folder.glob("*.json")) / 1024 / 1024:.2f} MiB).')


if __name__ == '__main__':
    export()
