"""Observation-only online predictor; no simulator/truth/files needed per step."""
from pathlib import Path
import json,hashlib,math
import numpy as np
from . import native_xgboost as xgb
from .features import CausalFeatures,SIGNALS,FEATURE_NAMES

class SaddlePredictor:
    def __init__(self,artifact_dir):
        self.root=Path(artifact_dir)
        self.recipe=json.loads((self.root/'training_recipe.json').read_text())
        manifest=json.loads((self.root/'model_manifest.json').read_text())
        self.columns=manifest['feature_columns'];self.models={}
        for head in SIGNALS:
            p=self.root/'models'/f'{head}.json'
            if hashlib.sha256(p.read_bytes()).hexdigest()!=manifest['model_files_sha256'][p.name]:
                raise ValueError('saved model hash mismatch')
            model=xgb.Booster();model.load_model(p);self.models[head]=model
        self.features=CausalFeatures(self.recipe['baseline_samples'],self.recipe['window_samples'],
                                    self.recipe['minimum_window_valid_fraction'])
        self.streak={h:0 for h in SIGNALS}

    def step(self,observations):
        vector,ready=self.features.step(observations)
        outputs={}
        for i,head in enumerate(SIGNALS):
            if vector is None or not ready[i]:
                self.streak[head]=0
                outputs[head]={'state':'unknown','score':None,'alarm':None};continue
            cols=self.columns[head]
            X=np.asarray([[vector[c] for c in cols]],dtype=np.float32)
            dm=xgb.DMatrix(X,feature_names=[FEATURE_NAMES[c] for c in cols],nthread=2)
            score=float(self.models[head].predict(dm)[0]);present=score>=self.recipe['prediction_threshold']
            self.streak[head]=self.streak[head]+1 if present else 0
            outputs[head]={'state':'present' if present else 'absent','score':score,
                'alarm':self.streak[head]>=self.recipe['alarm_persistence_samples']}
        return {'signals':outputs,'available_heads':sum(ready) if vector is not None else 0,
                'quality':'insufficient' if vector is None or not any(ready) else 'partial' if not all(ready) else 'available',
                'score_is_calibrated_probability':False,'field_validated':False}
