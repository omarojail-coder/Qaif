import tempfile
import unittest
from pathlib import Path
from backend.store import Store
from backend.seed import seed
from backend.pipeline_catalog import ensure_catalog


class CatalogTests(unittest.TestCase):
    def test_enrichment_keeps_existing_monitoring_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            seed(store)
            before = store.all('saddles')
            ensure_catalog(store)
            self.assertEqual(store.all('saddles'), before)
            self.assertEqual(len(store.all('pipelines')), 8)
            self.assertEqual(store.get('pipelines', 'P-2')['length_km'], 1200)
            self.assertEqual(store.get('pipelines', 'P-6')['length_km'], 42)
            self.assertEqual(store.get('pipelines', 'P-8')['lifecycle'], 'decommissioned')
            self.assertEqual(store.get('pipelines', 'P-8')['length_km'], None)
            for pipeline in store.all('pipelines'):
                self.assertTrue(pipeline['schematic'])
                self.assertTrue(pipeline['stations'])
                self.assertEqual(pipeline['planning_spacing_m'], 31)
                if pipeline['source'] != 'illustrative_route':
                    self.assertTrue(pipeline['source_url'].startswith('https://'))
                for station in pipeline['stations']:
                    x, y = station['x'], station['y']
                    on_route = any(
                        abs((x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0])) < 1e-8
                        and min(a[0],b[0]) <= x <= max(a[0],b[0])
                        and min(a[1],b[1]) <= y <= max(a[1],b[1])
                        for a,b in zip(pipeline['metro_points'],pipeline['metro_points'][1:])
                    )
                    self.assertTrue(on_route, (pipeline['id'], station['id']))
            audit_count = sum(len(store.history(p['id'])) for p in store.all('pipelines'))
            ensure_catalog(store)
            self.assertEqual(audit_count, sum(len(store.history(p['id'])) for p in store.all('pipelines')))
            self.assertEqual(store.all('saddles'), before)
