# -*- coding: utf-8 -*-
# FINAL best-of assembly: per line pick v6-best or v7-VC by composite (-CER + 15*sim).
import json, os, numpy as np, soundfile as sf
W="/mnt/d/CloneDub/work/v12_3min_1470_1650"
VOX="/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/vocals.wav"
D=json.load(open(W+"/lines_v5.json",encoding="utf-8"))
J6=json.load(open(W+"/v6_judge_final.json"))
S7={s["vid"]:s for s in json.load(open(W+"/v7_final_scores.json"))}
T0,T1=D["window"]; SCENE=T1-T0; SR=24000; ORIG={1,10,14}
pick={}
for vid,s6 in J6["best"].items():
    vid=int(vid); s7=S7.get(vid)
    c6=-s6["cer"]+15*s6["sim"]
    c7=(-s7["cer"]+15*s7["sim"]) if s7 else -999
    if s7 and c7>=c6:
        pick[vid]=("v7",W+"/generated_wavs_v7_vc/V%02d.wav"%vid,s7["cer"],s7["sim"])
    else:
        pick[vid]=("v6",W+"/generated_wavs_v6/V%02d_c%d.wav"%(vid,s6["cand"]),s6["cer"],s6["sim"])
cers=[p[2] for p in pick.values()]; sims=[p[3] for p in pick.values()]
for vid,p in sorted(pick.items()):
    print("V%02d <- %s cer=%.1f sim=%.2f"%(vid,p[0],p[2],p[3]))
print("HYBRID MEAN CER=%.1f SIM=%.2f"%(np.mean(cers),np.mean(sims)))
info=sf.info(VOX); vsr=info.samplerate
tl=np.zeros(int(SCENE*SR)+SR)
for L in sorted(D["lines"],key=lambda x:x["abs_start"]):
    vid=L["vid"]
    if vid in ORIG:
        x,_=sf.read(VOX,start=int(L["abs_start"]*vsr),stop=int(L["abs_end"]*vsr))
        if x.ndim>1: x=x.mean(1)
        x=x.astype(np.float32); x=x/(np.max(np.abs(x))+1e-9)*0.75
        n=int(len(x)*SR/vsr); a=np.interp(np.linspace(0,len(x),n,endpoint=False),np.arange(len(x)),x)
    else:
        if vid not in pick: continue
        a,sr=sf.read(pick[vid][1])
        if a.ndim>1: a=a.mean(1)
        if sr!=SR:
            n=int(len(a)*SR/sr); a=np.interp(np.linspace(0,len(a),n,endpoint=False),np.arange(len(a)),a)
    s=int(round((L["abs_start"]-T0)*SR)); e=s+len(a)
    if e>len(tl): a=a[:len(tl)-s]; e=len(tl)
    tl[s:e]+=a
tl=tl[:int(SCENE*SR)]; voice=tl*(0.75/(np.abs(tl).max()+1e-9))
NOVOX="/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/no_vocals.wav"
bi=sf.info(NOVOX); bsr=bi.samplerate
bed,_=sf.read(NOVOX,start=int(T0*bsr),stop=int(T1*bsr))
if bed.ndim>1: bed=bed.mean(1)
if bsr!=SR:
    n=int(len(bed)*SR/bsr); bed=np.interp(np.linspace(0,len(bed),n,endpoint=False),np.arange(len(bed)),bed)
n=min(len(bed),len(voice)); mix=voice[:n]+bed[:n]*0.6
mix=mix*(0.99/max(np.abs(mix).max(),0.99))
sf.write(W+"/scene_3min_final.wav",mix.astype(np.float32),SR)
json.dump({str(k):{"src":v[0],"cer":v[2],"sim":v[3]} for k,v in pick.items()},open(W+"/v8_hybrid_picks.json","w"))
print("V8_HYBRID_DONE")
