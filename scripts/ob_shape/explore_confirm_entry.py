import sys; sys.path.insert(0,'../strategy_research')  # run from scripts/ob_shape; TRAIN-only check of a 'wait for touch-bar rejection' entry
import numpy as np, pandas as pd, common as C
d=pd.read_parquet('results/hist_zones.parquet')
DUR={'M5':5,'M15':15,'M30':30,'H1':60,'H4':240}
# touch bar close vs zone (need c[touch]): recompute from resampled bars
rule={'M5':'5min','M15':'15min','M30':'30min','H1':'1h','H4':'4h'}
cl=[]
for (s,tf),g in d.groupby(['sym','tf']):
    b=C.resample(s,rule[tf]); b=b[b.high>=b.low]
    cl.append(pd.Series(b.close.to_numpy()[g.touch_i.to_numpy()],index=g.index))
d['c_touch']=pd.concat(cl)
bull=d.direction=='bull'
d['rej_prox']=np.where(bull,d.c_touch>d.top,d.c_touch<d.bot).astype(int)
d['rej_entry']=np.where(bull,d.c_touch>d.entry,d.c_touch<d.entry).astype(int)
d['t_arm']=d.ts_touch+pd.to_timedelta(d.tf.map(DUR),unit='min')
req=pd.DataFrame(dict(sym=d.sym,t_active=d.t_arm,side=np.where(bull,1,-1),etype='limit',level=d.entry,sl=d.sl,tp_r=2.0,expiry_min=25*60,hold_min=60,zid=d.index))
for m,c in ((1,'net'),(0,'gross')):
    r=C.simulate(req.copy(),cost_mult=m).set_index('zid'); d['a_r_'+c]=r.r_net
d.to_parquet('results/hist_r3.parquet')
tr=d[d.ts_touch<pd.Timestamp('2025-07-01',tz='UTC')]
for tf in ['H1','M15','M30','M5','H4','ALL']:
    g=tr if tf=='ALL' else tr[tr.tf==tf]
    base=g.dropna(subset=['r_gross'])
    out=[tf,'base n=%d g=%.3f n=%.3f'%(len(base),base.r_gross.mean(),base.r_net.mean())]
    for k in ['rej_prox','rej_entry']:
        x=g[(g[k]==1)].dropna(subset=['a_r_gross'])
        out.append('%s n=%d g=%.3f n=%.3f'%(k,len(x),x.a_r_gross.mean(),x.a_r_net.mean()))
    print(' | '.join(out))
