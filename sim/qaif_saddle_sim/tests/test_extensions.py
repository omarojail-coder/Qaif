"""Interaction/regression tests for real gas/crack simulator integration."""
from pathlib import Path
from dataclasses import replace
import unittest,json,copy,tempfile,csv,subprocess,sys

from qaif_saddle_sim.config import Config
from qaif_saddle_sim.model import Simulator
from qaif_saddle_sim.io import read_forcing,simulate_to_directory
from qaif_saddle_sim.extensions.integration import (
    IntegratedSimulator,ExtensionStep,read_extension_forcing,simulate_extended_to_directory)
from qaif_saddle_sim.extensions.annotations import load_annotations,encode_annotations

PKG=Path(__file__).resolve().parents[1]
INPUTS=PKG/'examples/extensions'

class ExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=Config.from_json(INPUTS/'combined/config.json')
        cls.settings=json.loads((INPUTS/'combined/extensions.json').read_text())
        cls.base=read_forcing(INPUTS/'combined/forcing.csv')[0]

    def simulator(self,settings=None,config=None):
        return IntegratedSimulator(config or self.config,settings or copy.deepcopy(self.settings),42)

    def trace(self,options=None,settings=None):
        sim=self.simulator(settings);rows=[]
        for t in range(0,121,5):
            values={'timestamp_s':float(t),'crack_present':False,'leak_opening_area_m2':0.,'h2s_force_missing':False}
            if options:values.update(options(t))
            rows.append(sim.step(replace(self.base,timestamp_s=float(t)),ExtensionStep(**values)))
        return rows

    def test_gas_never_changes_existing_noise_or_channels(self):
        settings=copy.deepcopy(self.settings);settings['crack']=None
        sim=self.simulator(settings);base=Simulator(self.config,42)
        for t in range(0,61,5):
            step=replace(self.base,timestamp_s=float(t))
            old,truth=base.step(step)
            new,newtruth,_=sim.step(step,ExtensionStep(float(t),False,1e-10,False))
            self.assertEqual({k:new[k] for k in old},old)
            self.assertEqual(truth,newtruth)

    def test_crack_changes_numeric_strain_without_inventing_leak(self):
        normal=self.trace();crack=self.trace(lambda t:{'crack_present':t>=60})
        self.assertEqual(normal[11][0],crack[11][0])
        self.assertNotEqual(normal[-1][0]['strain_hoop_microstrain'],crack[-1][0]['strain_hoop_microstrain'])
        self.assertLess(crack[-1][1]['strain_axial_microstrain_true'],0)
        self.assertEqual(crack[-1][2]['mixture_mass_flow_kg_s_true'],0)
        self.assertEqual(normal[-1][0]['h2s_ppm'],crack[-1][0]['h2s_ppm'])

    def test_source_start_is_causal_and_readout_lags(self):
        normal=self.trace();leak=self.trace(lambda t:{'leak_opening_area_m2':1e-10 if 60<=t<90 else 0})
        self.assertEqual(normal[12][0]['h2s_ppm'],leak[12][0]['h2s_ppm'])
        self.assertEqual(leak[12][2]['local_h2s_ppm_true'],0)
        self.assertGreater(leak[13][2]['local_h2s_ppm_true'],0)
        self.assertGreater(leak[-1][2]['sensor_response_ppm_true'],0)
        self.assertEqual(leak[-1][2]['mixture_mass_flow_kg_s_true'],0)

    def test_leak_without_h2s_has_real_release_and_baseline_readout(self):
        settings=copy.deepcopy(self.settings);settings['gas']['source']['composition']['h2s_mole_fraction']=0
        normal=self.trace(settings=settings)
        leak=self.trace(lambda t:{'leak_opening_area_m2':1e-10 if t>=60 else 0},settings=settings)
        self.assertGreater(leak[-1][2]['mixture_mass_flow_kg_s_true'],0)
        self.assertEqual(leak[-1][2]['local_h2s_ppm_true'],0)
        self.assertEqual([r[0]['h2s_ppm'] for r in normal],[r[0]['h2s_ppm'] for r in leak])

    def test_gas_pressure_converts_gauge_to_absolute_once(self):
        _,_,truth=self.simulator().step(self.base,ExtensionStep(0,False,1e-10,False))
        self.assertAlmostEqual(truth['backpressure_ratio_true'],101325/1101325)

    def test_shared_and_h2s_outages_preserve_physics_and_later_noise(self):
        a=self.simulator();b=self.simulator()
        for t in range(0,121,5):
            step=replace(self.base,timestamp_s=float(t));extension=ExtensionStep(float(t),t>=60,1e-10,False)
            normal=a.step(step,extension)
            gap=b.step(replace(step,force_missing=50<=t<=60),replace(extension,h2s_force_missing=80<=t<=90))
            self.assertEqual(normal[2],gap[2])
            if 50<=t<=60 or 80<=t<=90:
                self.assertIsNone(gap[0]['h2s_ppm']);self.assertFalse(gap[0]['h2s_valid'])
                if 80<=t<=90:self.assertTrue(gap[0]['packet_valid'])
            else:self.assertEqual(normal[0],gap[0])

    def test_crack_point_matches_table_pressure_and_existing_gain(self):
        config=replace(self.config,
            strain_hoop=replace(self.config.strain_hoop,noise_std=0,lag_s=0),
            strain_axial=replace(self.config.strain_axial,noise_std=0,lag_s=0))
        sim=self.simulator(config=config)
        obs,latent,_=sim.step(self.base,ExtensionStep(0,True,0,False))
        table=sim.crack.table['cracked']
        self.assertAlmostEqual(latent['strain_hoop_microstrain_true'],table['hoop_microstrain'])
        self.assertAlmostEqual(obs['strain_hoop_microstrain'],table['hoop_microstrain']*config.strain_hoop.gain)
        self.assertAlmostEqual(obs['strain_axial_microstrain'],table['axial_microstrain']*config.strain_axial.gain)

    def test_crack_no_load_is_not_a_false_strain_jump(self):
        sim=self.simulator();step=replace(self.base,pressure_pa=0)
        _,latent,truth=sim.step(step,ExtensionStep(0,True,0,False))
        self.assertEqual(latent['strain_hoop_microstrain_true'],0)
        self.assertEqual(latent['strain_axial_microstrain_true'],0)
        self.assertTrue(truth['crack_present_true'])

    def test_crack_linear_pressure_and_normal_intact_limit(self):
        sim=self.simulator();_,a,_=sim.step(replace(self.base,pressure_pa=5e5),ExtensionStep(0,True,0,False))
        _,b,_=self.simulator().step(self.base,ExtensionStep(0,True,0,False))
        self.assertAlmostEqual(b['strain_axial_microstrain_true'],2*a['strain_axial_microstrain_true'])
        _,intact,_=self.simulator().step(self.base,ExtensionStep(0,False,0,False))
        # Independent closed-end Lame identity at zero external pressure.
        ri,t=self.config.inner_radius_m,self.config.wall_thickness_m
        A=self.base.pressure_pa*ri*ri/(t*(2*ri+t))
        self.assertAlmostEqual(intact['strain_hoop_microstrain_true'],(2-self.config.poisson_ratio)*A/self.config.young_modulus_pa*1e6)

    def test_rejects_geometry_and_uncomputed_loads(self):
        for config in (replace(self.config,inner_diameter_m=.5),replace(self.config,sensor_theta_rad=.1),
                       replace(self.config,axial_restraint_fraction=.1)):
            with self.assertRaises(ValueError):self.simulator(config=config)
        for step in (replace(self.base,pressure_pa=2e6),replace(self.base,bending_moment_nm=1),
                     replace(self.base,ambient_temperature_k=294)):
            sim=self.simulator()
            with self.assertRaises(ValueError):sim.step(step,ExtensionStep(0,True,0,False))
            self.assertIsNone(sim.base.state.last_timestamp_s)

    def test_rejects_pressure_convention_and_disabled_paths(self):
        settings=copy.deepcopy(self.settings);settings['forcing_pressure_convention']='absolute'
        with self.assertRaises(ValueError):self.simulator(settings)
        settings=copy.deepcopy(self.settings);settings['crack']=None
        with self.assertRaises(ValueError):self.simulator(settings).step(self.base,ExtensionStep(0,True,0,False))
        settings=copy.deepcopy(self.settings);settings['gas']=None
        with self.assertRaises(ValueError):self.simulator(settings).step(self.base,ExtensionStep(0,False,1e-10,False))

    def test_strict_time_alignment_and_no_healing(self):
        sim=self.simulator()
        with self.assertRaises(ValueError):sim.step(self.base,ExtensionStep(1,False,0,False))
        sim.step(self.base,ExtensionStep(0,True,0,False))
        with self.assertRaises(ValueError):sim.step(replace(self.base,timestamp_s=5),ExtensionStep(5,False,0,False))
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'bad.csv';p.write_text('timestamp_s,crack_present,leak_opening_area_m2,h2s_force_missing\n0,yes,0,0\n')
            with self.assertRaises(ValueError):read_extension_forcing(p)

    def test_export_reproducibility_separation_masks_and_overwrite(self):
        case=INPUTS/'combined'
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/'a',Path(temp)/'b'
            args=[case/'config.json',case/'forcing.csv',case/'extensions.json',case/'extension_forcing.csv']
            manifest=simulate_extended_to_directory(*args,a,42)
            simulate_extended_to_directory(*args,b,42)
            for name in ('observed.csv','physical_truth.csv','latent.csv','annotations.jsonl','manifest.json'):
                self.assertEqual((a/name).read_bytes(),(b/name).read_bytes())
            self.assertFalse(manifest['training_ready'])
            with (a/'observed.csv').open(newline='') as h:headers=csv.DictReader(h).fieldnames
            for forbidden in ('crack_present_true','event_type','leak_opening_area_m2','local_h2s_ppm_true','run_id'):
                self.assertNotIn(forbidden,headers)
            targets=encode_annotations(load_annotations(a/'annotations.jsonl'))
            self.assertTrue(all(not any(mask) for mask in targets.known_mask))
            with self.assertRaises(FileExistsError):simulate_extended_to_directory(*args,a,42)

    def test_original_cli_export_identical_without_extension_options(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/'a',Path(temp)/'b'
            c,f=PKG/'examples/fixture_config.json',PKG/'examples/fixture_forcing.csv'
            simulate_to_directory(c,f,a,42)
            result=subprocess.run([sys.executable,'-m','qaif_saddle_sim.cli','simulate',
                '--config',str(c),'--forcing',str(f),'--out',str(b),'--seed','42'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            for p in a.iterdir():self.assertEqual(p.read_bytes(),(b/p.name).read_bytes())

    def test_extended_cli_uses_real_simulate_entry_point(self):
        case=INPUTS/'leak_only'
        with tempfile.TemporaryDirectory() as temp:
            result=subprocess.run([sys.executable,'-m','qaif_saddle_sim.cli','simulate',
                '--config',str(case/'config.json'),'--forcing',str(case/'forcing.csv'),
                '--extensions',str(case/'extensions.json'),'--extension-forcing',str(case/'extension_forcing.csv'),
                '--out',temp],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            with (Path(temp)/'observed.csv').open() as h:
                self.assertIn('h2s_ppm',csv.DictReader(h).fieldnames)

if __name__=='__main__':unittest.main()
