import pandas as pd, numpy as np, os, time
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
ctx=pd.read_parquet(H+"/out_context.parquet")
print("out_context seasons:", int(ctx.season.min()), "-", int(ctx.season.max()), "rows", len(ctx))
w1=ctx[(ctx.season==2018)&(ctx.week==1)]
print("2018 wk1: mean r_prior_games_home=%.2f  r_ok=%s  r_form_z sd=%.3f"%(
    w1.r_prior_games_home.mean(), w1.r_ok.mean(), w1.r_form_z.std()))
w1b=ctx[(ctx.season==2011)&(ctx.week==1)]
print("2011 wk1: mean r_prior_games_home=%.2f  r_ok=%s"%(w1b.r_prior_games_home.mean(), w1b.r_ok.mean()))
print("rows with r_ok True by season:")
print(ctx.groupby("season").r_ok.mean().round(3).to_string())
for f in sorted(os.listdir(H)):
    if f.endswith(".parquet"):
        print("%-30s mtime %s"%(f,time.strftime("%Y-%m-%d %H:%M",time.localtime(os.path.getmtime(H+"/"+f)))))
for f in sorted(os.listdir("/Users/cmanlongat/Projects/pick-six/data/nflverse")):
    if f.endswith("2019.parquet") or f=="games.csv":
        print("%-30s mtime %s"%(f,time.strftime("%Y-%m-%d %H:%M",time.localtime(os.path.getmtime("/Users/cmanlongat/Projects/pick-six/data/nflverse/"+f)))))
