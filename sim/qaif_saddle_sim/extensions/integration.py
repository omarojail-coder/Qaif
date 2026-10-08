"""One clock, numeric sensor observations, independent physical truth.

Crack response is restricted to a pinned target geometry and point gauge.
Gas reuses the reviewed fixed-20-C source/transport/readout components.
No diagnostic or signal-training label is inferred from defect presence.
"""
from __future__ import annotations
import csv, json, math, shutil
from dataclasses import dataclass, fields
from pathlib import Path

from ..config import Config
from ..model import Simulator, Step, pipe_strains
from ..io import read_forcing, load_reference_provenance, _write_csv, _sha256
from .. import __version__ as generator_version
from . import __version__ as extension_version
from .gas import OpenAirConfig, OpenAirTransport, GapConfig, GapTransport, CoupledGasSimulator
from .gas._source.model import GasComposition, SourceConfig, LeakInput, absolute_pressure, discharge, number
from .gas._sensor.model import H2SConfig
from .annotations import unknown_annotation
from .crack_pin import RESPONSE_SHA256


def keys(value, expected, name):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f'{name} must contain exactly {sorted(expected)}')


@dataclass(frozen=True)
class ExtensionStep:
    timestamp_s: float
    crack_present: bool
    leak_opening_area_m2: float
    h2s_force_missing: bool

    def validate(self):
        number('timestamp_s', self.timestamp_s, nonnegative=True)
        number('leak_opening_area_m2', self.leak_opening_area_m2, nonnegative=True)
        if type(self.crack_present) is not bool or type(self.h2s_force_missing) is not bool:
            raise ValueError('crack_present and h2s_force_missing must be booleans')


def read_extension_forcing(path):
    expected=[f.name for f in fields(ExtensionStep)]
    result=[]
    with Path(path).open(encoding='utf-8-sig',newline='') as handle:
        reader=csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames)!=len(expected) or set(reader.fieldnames)!=set(expected):
            raise ValueError(f'extension forcing headers must exactly match {expected}')
        last=-1.0;seen_crack=False
        for n,row in enumerate(reader,2):
            try:
                if None in row or any(v is None or not v.strip() for v in row.values()):
                    raise ValueError('missing/extra extension cell')
                values={}
                for name in expected:
                    value=row[name].strip()
                    if name in ('crack_present','h2s_force_missing'):
                        if value not in ('0','1'):raise ValueError(f'{name} must be 0 or 1')
                        values[name]=value=='1'
                    else:values[name]=float(value)
                item=ExtensionStep(**values);item.validate()
                if item.timestamp_s<=last:raise ValueError('extension timestamps must strictly increase')
                if seen_crack and not item.crack_present:raise ValueError('crack healing/removal is unsupported')
                seen_crack=seen_crack or item.crack_present
                last=item.timestamp_s;result.append(item)
            except (TypeError,ValueError) as exc:raise ValueError(f'extension forcing line {n}: {exc}') from exc
    if not result:raise ValueError('extension forcing is empty')
    return result


class CrackResponse:
    def __init__(self, config, settings):
        keys(settings, ('response_id','evaluation'), 'crack settings')
        if settings['response_id']!='qaif_internal_a0p5_c1' or settings['evaluation']!='outer_centre_point':
            raise ValueError('only the bundled QAIF geometry and centre point gauge are supported')
        self.path=Path(__file__).parent/'data/qaif_crack_response.json'
        if _sha256(self.path)!=RESPONSE_SHA256:raise ValueError('bundled crack response hash differs from its calculation')
        self.table=json.loads(self.path.read_text(encoding='utf-8'))
        for name,value in self.table['cylinder'].items():
            if not math.isclose(getattr(config,name),value,rel_tol=1e-12,abs_tol=1e-12):
                raise ValueError(f'crack response geometry/material mismatch: {name}')
        if config.axial_restraint_fraction!=0 or abs(config.sensor_theta_rad)>1e-12:
            raise ValueError('crack table requires free closed ends and gauge theta=0 above crack centre')
        self.active=False

    def validate_step(self, inputs):
        if inputs.pressure_pa>self.table['maximum_pressure_pa']:
            raise ValueError('pressure exceeds the provisional crack-table load range')
        if self.active and inputs.bending_moment_nm!=0:
            raise ValueError('crack under bending has not been computed')

    def __call__(self, config, inputs, steel_temperature_k):
        # Replace only the original pressure term. Existing uniform free
        # thermal expansion, readout transfer, lag, noise and loss remain active.
        self.validate_step(inputs)
        sh,sa,eh,ea=pipe_strains(config,inputs,steel_temperature_k)
        thin_h=(sh-config.poisson_ratio*sa)/config.young_modulus_pa
        thin_a=(sa-config.poisson_ratio*sh)/config.young_modulus_pa
        scale=inputs.pressure_pa/self.table['reference_pressure_pa']
        point=self.table['cracked'] if self.active else self.table['intact']
        return (point['hoop_stress_pa']*scale,point['axial_stress_pa']*scale,
                eh-thin_h+point['hoop_microstrain']*1e-6*scale,
                ea-thin_a+point['axial_microstrain']*1e-6*scale)


class IntegratedSimulator:
    def __init__(self, config: Config, settings: dict, seed: int, *, physics_cache=None):
        keys(settings,('schema_version','forcing_pressure_convention','gas','crack'),'extensions')
        if settings['schema_version']!='1' or settings['forcing_pressure_convention']!='gauge':
            raise ValueError('extension v1 requires explicit gauge pressure in the original forcing')
        if settings['gas'] is None and settings['crack'] is None:raise ValueError('enable at least one extension')
        self.config=config;self.settings=settings
        self.crack=CrackResponse(config,settings['crack']) if settings['crack'] is not None else None
        self.base=Simulator(config,seed,physics_cache=physics_cache,mechanical_response=self.crack)
        self.gas=None
        if settings['gas'] is not None:
            g=settings['gas'];keys(g,('source','transport','sensor','internal_step_s'),'gas settings')
            source=dict(g['source']);source['composition']=GasComposition(**source['composition'])
            source=SourceConfig(**source)
            transport=dict(g['transport']);kind=transport.pop('kind',None)
            if kind=='open_air':self.transport=OpenAirTransport(OpenAirConfig(**transport))
            elif kind=='vented_gap':self.transport=GapTransport(GapConfig(**transport))
            else:raise ValueError('transport kind must be open_air or vented_gap')
            sensor=H2SConfig(**g['sensor'])
            self.gas=CoupledGasSimulator(source,self.transport,sensor,seed,internal_step_s=g['internal_step_s'])
        self.seen_crack=False

    def validate_next(self, inputs, extension):
        inputs.validate();extension.validate()
        if inputs.timestamp_s!=extension.timestamp_s:raise ValueError('forcing timestamps do not align exactly')
        if self.base.state.last_timestamp_s is not None and inputs.timestamp_s<=self.base.state.last_timestamp_s:
            raise ValueError('timestamps must strictly increase')
        if extension.crack_present and self.crack is None:raise ValueError('crack forcing supplied without crack extension')
        if self.seen_crack and not extension.crack_present:raise ValueError('crack healing/removal is unsupported')
        if self.crack:
            self.crack.active=extension.crack_present;self.crack.validate_step(inputs)
        if self.gas is None:
            if extension.leak_opening_area_m2 or extension.h2s_force_missing:
                raise ValueError('gas forcing supplied without gas extension')
            return None
        # No environmental correction is available; never silently use the
        # fixed-reference sensor with a weather trajectory at another temperature.
        if inputs.ambient_temperature_k!=self.transport.config.ambient_temperature_k:
            raise ValueError('gas transport/readout currently requires a fixed 20 C ambient environment')
        pressure=absolute_pressure(inputs.pressure_pa,convention='gauge',
            ambient_pressure_pa_abs=self.transport.config.ambient_pressure_pa_abs)
        gas_input=LeakInput(inputs.timestamp_s,pressure,inputs.fluid_temperature_k,
            self.transport.config.ambient_pressure_pa_abs,extension.leak_opening_area_m2)
        self.transport.validate_source(discharge(self.gas.source_config,gas_input))
        return gas_input

    def step(self, inputs: Step, extension: ExtensionStep):
        gas_input=self.validate_next(inputs,extension)
        observed,latent=self.base.step(inputs)
        if self.gas:
            gas_observed,gas_truth=self.gas.step(gas_input,force_missing=extension.h2s_force_missing)
            # Preserve gas physics and its independent stochastic schedule even
            # during a shared saddle packet outage.
            if not observed['packet_valid']:
                gas_observed.update(h2s_ppm=None,h2s_valid=False,h2s_status='missing')
            observed.update({k:v for k,v in gas_observed.items() if k!='timestamp_s'})
            truth=gas_truth
        else:
            observed.update(h2s_ppm=None,h2s_valid=False,h2s_status='disabled')
            truth={'timestamp_s':inputs.timestamp_s,'local_h2s_ppm_true':None,
                   'mixture_mass_flow_kg_s_true':None,'h2s_mass_flow_kg_s_true':None}
        truth.update(crack_present_true=extension.crack_present,
            crack_depth_m_true=self.crack.table['crack']['depth_m'] if extension.crack_present else 0.0,
            crack_surface_length_m_true=self.crack.table['crack']['surface_length_m'] if extension.crack_present else 0.0,
            crack_through_wall_true=False if extension.crack_present else None,
            leak_opening_present_true=extension.leak_opening_area_m2>0,
            leak_opening_area_m2_true=extension.leak_opening_area_m2,
            gas_release_active_true=(truth['mixture_mass_flow_kg_s_true']>0) if self.gas else None,
            pressure_model_true='pinned_target_fea_and_exact_intact' if self.crack else 'legacy_thin_wall')
        self.seen_crack=self.seen_crack or extension.crack_present
        return observed,latent,truth


def simulate_extended_to_directory(config_path,forcing_path,settings_path,extension_forcing_path,output_dir,seed,*,physics_cache=None):
    paths=list(map(Path,(config_path,forcing_path,settings_path,extension_forcing_path)))
    config=Config.from_json(paths[0]);steps=read_forcing(paths[1])
    settings=json.loads(paths[2].read_text(encoding='utf-8'));extension_steps=read_extension_forcing(paths[3])
    if len(steps)!=len(extension_steps) or any(s.timestamp_s!=e.timestamp_s for s,e in zip(steps,extension_steps)):
        raise ValueError('base and extension forcing must have identical timestamp grids')
    reference=load_reference_provenance(paths[0],paths[1])
    sim=IntegratedSimulator(config,settings,seed,physics_cache=physics_cache)
    # Preflight all forcing before creating any output. No state is advanced.
    for s,e in zip(steps,extension_steps):sim.validate_next(s,e)
    if sim.crack:sim.crack.active=False
    output_dir=Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):raise FileExistsError(f'output directory is not empty: {output_dir}')
    observed_rows=[];latent_rows=[];truth_rows=[];context_rows=[];annotations=[]
    for i,(step,extension) in enumerate(zip(steps,extension_steps)):
        observed,latent,truth=sim.step(step,extension)
        observed_rows.append(observed);latent_rows.append(latent);truth_rows.append(truth)
        context_rows.append({'timestamp_s':step.timestamp_s,**{k:getattr(step,k) for k in config.observable_context}})
        good=observed['packet_valid'] and observed['h2s_status'] not in ('missing','readout_limit')
        annotations.append(unknown_annotation(f'{config.run_id}:{i}',step.timestamp_s,source_role='research_annotation',
            label_policy_id='integration_preview_pending_signal_policy',quality_status='degraded' if good else 'insufficient',
            reason='Research physics/transfer are uncalibrated; signal label policy is pending. Physical truth is separate.'))
    output_dir.mkdir(parents=True,exist_ok=True)
    for name,rows in (('observed.csv',observed_rows),('latent.csv',latent_rows),('physical_truth.csv',truth_rows),('context.csv',context_rows)):
        _write_csv(output_dir/name,rows)
    snapshots=('config_snapshot.json','forcing_snapshot.csv','extensions_snapshot.json','extension_forcing_snapshot.csv')
    for source,name in zip(paths,snapshots):shutil.copyfile(source,output_dir/name)
    (output_dir/'annotations.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in annotations),encoding='utf-8')
    if sim.crack:shutil.copyfile(sim.crack.path,output_dir/'crack_response_snapshot.json')
    if reference:
        (output_dir/'reference_manifest_snapshot.json').write_text(json.dumps(reference,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    pkg=Path(__file__).parents[1]
    manifest={'schema_version':'3','generator_version':generator_version,'extension_version':extension_version,
        'asset_id':config.asset_id,'run_id':config.run_id,'source_episode_id':config.source_episode_id,
        'parameter_basis':config.parameter_basis,'seed':seed,'sample_count':len(steps),
        'forcing_pressure_convention':'gauge','gas_upstream_pressure':'gauge pressure + configured absolute ambient pressure',
        'training_ready':False,'field_validated':False,'models_trained':[],
        'signal_annotations':'all unknown; tri-state format only; no training policy approved',
        'extensions_enabled':{'gas':sim.gas is not None,'crack':sim.crack is not None},
        'source_sha256':{p.relative_to(pkg).as_posix():_sha256(p) for p in sorted(pkg.rglob('*.py'))},
        'output_files':{p.name:_sha256(p) for p in output_dir.iterdir() if p.is_file()},
        'limits':['Pinned internal longitudinal non-through-wall crack geometry; point gauge, no growth/contact/plasticity',
                  'Gas uses prescribed local air flow and uncalibrated dispersion at fixed 20 C',
                  'No calibrated coating/saddle transfer or inferred detection radius',
                  'Crack presence and gas release are independent; non-through-wall crack does not create a gas hole',
                  'physical_truth.csv, latent.csv, forcing and annotations are excluded from model features',
                  'Prior reference axial discrepancy remains recorded; integration is provisional']}
    (output_dir/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return manifest
