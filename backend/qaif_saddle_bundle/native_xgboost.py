"""Small adapter to the OFFICIAL XGBoost 3.0.5 CPU C API.

The boosting, gradients, trees, prediction and model serialization all run in
the official native library. This only marshals NumPy arrays and selects validation rounds.
Avoids a 38.6 MB SciPy download; no SciPy stubs or replacement ML algorithm.
Signatures mirror the installed wheel's official core.py and data.py.
"""
from pathlib import Path
from importlib.metadata import distribution, PackageNotFoundError
import sys
import ctypes as C,json,math,collections,hashlib
import numpy as np

if sys.platform == 'win32':
    DLL=Path(__file__).resolve().parent/'lib/xgboost.dll'
elif sys.platform.startswith('linux'):
    # Locate the official wheel without importing its optional SciPy wrapper.
    try:
        DLL=Path(distribution('xgboost-cpu').locate_file('xgboost/lib/libxgboost.so'))
    except PackageNotFoundError:
        raise RuntimeError('Linux deployment requires the official xgboost-cpu==3.0.5 wheel') from None
else:
    raise RuntimeError('The reviewed native runtime supports Windows and Linux only')
if not DLL.is_file():raise RuntimeError('install the official xgboost-cpu 3.0.5 native library')
LIB=C.CDLL(str(DLL))
U=C.c_uint64;V=C.c_void_p;S=C.c_char_p;I=C.c_int;F=C.c_float
LIB.XGBGetLastError.restype=S
def bind(name,args):
    function=getattr(LIB,name);function.argtypes=args;function.restype=I;return function
create_dense=bind('XGDMatrixCreateFromDense',[S,S,C.POINTER(V)])
set_float=bind('XGDMatrixSetFloatInfo',[V,S,C.POINTER(F),U])
set_dm_names=bind('XGDMatrixSetStrFeatureInfo',[V,S,C.POINTER(S),U])
free_dm=bind('XGDMatrixFree',[V])
create_booster=bind('XGBoosterCreate',[C.POINTER(V),U,C.POINTER(V)])
set_param=bind('XGBoosterSetParam',[V,S,S])
set_b_names=bind('XGBoosterSetStrFeatureInfo',[V,S,C.POINTER(S),U])
update=bind('XGBoosterUpdateOneIter',[V,I,V])
evaluate=bind('XGBoosterEvalOneIter',[V,I,C.POINTER(V),C.POINTER(S),U,C.POINTER(S)])
predict=bind('XGBoosterPredictFromDMatrix',[V,V,S,C.POINTER(C.POINTER(U)),C.POINTER(U),C.POINTER(C.POINTER(F))])
slice_booster=bind('XGBoosterSlice',[V,I,I,I,C.POINTER(V)])
save_model=bind('XGBoosterSaveModel',[V,S]);load_model=bind('XGBoosterLoadModel',[V,S])
save_buffer=bind('XGBoosterSaveModelToBuffer',[V,S,C.POINTER(U),C.POINTER(C.c_char_p)])
free_booster=bind('XGBoosterFree',[V])
version=getattr(LIB,'XGBoostVersion');version.argtypes=[C.POINTER(I)]*3;version.restype=None
major,minor,patch=I(),I(),I();version(C.byref(major),C.byref(minor),C.byref(patch))
__version__=f'{major.value}.{minor.value}.{patch.value}'
if __version__!='3.0.5':raise RuntimeError('unreviewed native engine version')

def check(status):
    if status!=0:raise RuntimeError(LIB.XGBGetLastError().decode('utf-8'))
def strings(names):return (S*len(names))(*(str(n).encode('utf-8') for n in names))

class DMatrix:
    def __init__(self,data,label=None,feature_names=None,nthread=2):
        self.data=np.ascontiguousarray(data,dtype=np.float32)
        if self.data.ndim!=2:raise ValueError('DMatrix needs 2-D dense observations')
        self.feature_names=list(feature_names or [f'f{i}' for i in range(self.data.shape[1])])
        if len(self.feature_names)!=self.data.shape[1] or len(set(self.feature_names))!=len(self.feature_names):raise ValueError('invalid features')
        self.handle=V()
        interface=json.dumps(self.data.__array_interface__).encode()
        config=json.dumps({'missing':float('nan'),'nthread':int(nthread),'data_split_mode':0}).encode()
        check(create_dense(interface,config,C.byref(self.handle)))
        names=strings(self.feature_names);check(set_dm_names(self.handle,b'feature_name',names,U(len(names))))
        self.label=None if label is None else np.ascontiguousarray(label,dtype=np.float32)
        if self.label is not None:
            if len(self.label)!=len(self.data):raise ValueError('label/data lengths differ')
            check(set_float(self.handle,b'label',self.label.ctypes.data_as(C.POINTER(F)),U(len(self.label))))
    def get_label(self):return self.label.copy()
    def __del__(self):
        if getattr(self,'handle',None):
            try:free_dm(self.handle)
            except Exception:pass
            self.handle=None

class Booster:
    def __init__(self,cache=None,handle=None,feature_names=None):
        self.cache=cache or [];self.feature_names=feature_names or (self.cache[0].feature_names if self.cache else None)
        self.handle=handle or V()
        if handle is None:
            matrices=(V*len(self.cache))(*(d.handle for d in self.cache))
            check(create_booster(matrices,U(len(self.cache)),C.byref(self.handle)))
        self.set_param('nthread',2);self.set_param('verbosity',0)
        if self.feature_names:
            names=strings(self.feature_names);check(set_b_names(self.handle,b'feature_name',names,U(len(names))))
    def set_param(self,name,value):check(set_param(self.handle,str(name).encode(),str(value).encode()))
    def predict(self,data):
        if self.feature_names and self.feature_names!=data.feature_names:raise ValueError('feature order/name mismatch')
        shape=C.POINTER(U)();dims=U();values=C.POINTER(F)()
        config=json.dumps({'type':0,'training':False,'iteration_begin':0,'iteration_end':0,'strict_shape':False}).encode()
        check(predict(self.handle,data.handle,config,C.byref(shape),C.byref(dims),C.byref(values)))
        count=math.prod(shape[i] for i in range(dims.value))
        return np.ctypeslib.as_array(values,shape=(count,)).copy()
    def save_model(self,path):check(save_model(self.handle,str(path).encode('utf-8')))
    def load_model(self,path):
        check(load_model(self.handle,str(path).encode('utf-8')))
        self.feature_names=json.loads(Path(path).read_text())['learner']['feature_names']
    def __getitem__(self,value):
        if not isinstance(value,slice) or value.stop is None:raise ValueError('bounded model slice required')
        handle=V();check(slice_booster(self.handle,I(value.start or 0),I(value.stop),I(value.step or 1),C.byref(handle)))
        return Booster(handle=handle,feature_names=self.feature_names)
    def get_score(self,importance_type='gain'):
        if importance_type!='gain':raise ValueError('adapter supports gain importance only')
        length=U();buffer=S()
        check(save_buffer(self.handle,b'{"format":"json"}',C.byref(length),C.byref(buffer)))
        model=json.loads(C.string_at(buffer,length.value))
        trees=model['learner']['gradient_booster']['model']['trees'];sums=collections.defaultdict(float);counts=collections.Counter()
        for tree in trees:
            for node,left in enumerate(tree['left_children']):
                if left<0:continue
                feature=tree['split_indices'][node];sums[feature]+=tree['loss_changes'][node];counts[feature]+=1
        return {self.feature_names[i]:v/counts[i] for i,v in sums.items()}
    def __del__(self):
        if getattr(self,'handle',None):
            try:free_booster(self.handle)
            except Exception:pass
            self.handle=None

def train(params,dtrain,*,num_boost_round,evals,early_stopping_rounds,evals_result,verbose_eval=False):
    model=Booster(cache=[dtrain]+[d for d,n in evals]);model.best_score=math.inf;model.best_iteration=0
    for name,value in params.items():model.set_param(name,value)
    matrices=(V*len(evals))(*(d.handle for d,n in evals));names=strings([n for d,n in evals])
    for iteration in range(num_boost_round):
        check(update(model.handle,I(iteration),dtrain.handle));message=S()
        check(evaluate(model.handle,I(iteration),matrices,names,U(len(evals)),C.byref(message)))
        for part in message.value.decode().split('\t')[1:]:
            label,score=part.rsplit(':',1);dataset,metric=label.split('-',1)
            evals_result.setdefault(dataset,{}).setdefault(metric,[]).append(float(score))
        score=evals_result[evals[-1][1]][params['eval_metric']][-1]
        if score<model.best_score:model.best_score=score;model.best_iteration=iteration
        if iteration-model.best_iteration>=early_stopping_rounds:break
    return model

def runtime_manifest():
    return {'engine':'official XGBoost CPU native library','version':__version__,'dll_path':str(DLL),
            'dll_sha256':hashlib.sha256(DLL.read_bytes()).hexdigest(),'adapter':'ctypes dense C API; no ML algorithm reimplementation',
            'scipy_required_for_this_adapter':False}
