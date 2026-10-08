"""Causal observation-only feature builder and channel availability gate."""
from __future__ import annotations
import math,statistics
from collections import deque
CHANNELS=('strain_hoop_microstrain','strain_axial_microstrain','temperature_k','wetness_index','h2s_ppm')
SIGNALS=('mechanical_anomaly','thermal_anomaly','wetness_anomaly','h2s_anomaly')
GROUPS=((0,1),(2,),(3,),(4,))
SUFFIXES=('last','mean','std','min','max','slope_per_s','delta_baseline','valid_fraction')
FEATURE_NAMES=tuple(f'{c}__{s}' for c in CHANNELS for s in SUFFIXES)+('hoop_minus_axial_delta','hoop_minus_axial_last','packet_valid_fraction')
ALLOWED=set(CHANNELS)|{'timestamp_s','packet_valid','h2s_valid','h2s_status'}

class CausalFeatures:
    def __init__(self,baseline_samples=24,window_samples=12,min_valid=.75):
        self.baseline_samples=baseline_samples;self.window_samples=window_samples;self.min_valid=min_valid
        self.buffer=deque(maxlen=window_samples);self.baseline=[[] for _ in CHANNELS]
        self.count=0;self.last_time=None

    def step(self,row):
        if set(row)!=ALLOWED:raise ValueError('predictor input must contain only the declared observations/quality')
        t=row['timestamp_s']
        if type(t) not in (int,float) or not math.isfinite(t) or (self.last_time is not None and t<=self.last_time):
            raise ValueError('invalid/non-increasing observation timestamp')
        if type(row['packet_valid']) is not bool or type(row['h2s_valid']) is not bool:raise ValueError('validity must be boolean')
        values=[]
        for i,c in enumerate(CHANNELS):
            value=row[c]
            valid=row['packet_valid'] and (i!=4 or row['h2s_valid'])
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value)):
                raise ValueError('observation must be finite numeric or None')
            values.append(float(value) if valid and value is not None else None)
        if self.count<self.baseline_samples:
            for i,v in enumerate(values):
                if v is not None:self.baseline[i].append(v)
        self.buffer.append((float(t),values,row['packet_valid']));self.count+=1;self.last_time=t
        if self.count<=self.baseline_samples or len(self.buffer)<self.window_samples:return None,[False]*4
        result=[];channel_ready=[];deltas=[];lasts=[]
        for i,c in enumerate(CHANNELS):
            selected=[(time,v[i]) for time,v,_ in self.buffer if v[i] is not None]
            fraction=len(selected)/self.window_samples
            base_ready=len(self.baseline[i])>=math.ceil(self.baseline_samples*self.min_valid)
            ready=base_ready and fraction>=self.min_valid and values[i] is not None
            channel_ready.append(ready)
            if selected:
                ts,vs=zip(*selected);mean=statistics.fmean(vs);std=statistics.pstdev(vs)
                tm=statistics.fmean(ts);den=math.fsum((x-tm)**2 for x in ts)
                slope=math.fsum((x-tm)*(y-mean) for x,y in selected)/den if den else 0.
                last=values[i] if values[i] is not None else math.nan
                delta=last-statistics.median(self.baseline[i]) if base_ready else math.nan
                result.extend((last,mean,std,min(vs),max(vs),slope,delta,fraction))
            else:
                last=delta=math.nan;result.extend((math.nan,)*7+(fraction,))
            deltas.append(delta);lasts.append(last)
        result.extend((deltas[0]-deltas[1],lasts[0]-lasts[1],sum(p for _,_,p in self.buffer)/self.window_samples))
        return result,[all(channel_ready[i] for i in group) for group in GROUPS]
