import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
from fit import glm_fit, logit, VECTORS, VECTOR_COL
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(H+"/out_full_fit_table.parquet")
cols=[VECTOR_COL[v] for v in VECTORS]
old=d[d.season<=2018]; new=d[d.season>=2019]
for s,lab in ((old,"2006-2018 (the NEW rows the second run added)"),(new,"2019-2025 (the rows the FIRST run already had)")):
    r=glm_fit(s,cols,intercept=False,label="x")
    print("%-46s n=%4d B_P=%+.5f SE %.5f p=%.5f"%(lab,len(s),r.params["p_qb_z"],r.bse["p_qb_z"],r.pvalues["p_qb_z"]))
print("\noverlap: %d of %d full-run rows (%.0f%%) were already in the 2019-2025 run"%(len(new),len(d),100*len(new)/len(d)))
