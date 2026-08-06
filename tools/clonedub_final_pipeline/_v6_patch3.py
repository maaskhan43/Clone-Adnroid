# -*- coding: utf-8 -*-
# final polish: 2 extra candidates (c3,c4) for weak/regressed lines, same text.
import os, json, numpy as np, soundfile as sf, torch
from transformers import AutoModel
W="/mnt/d/CloneDub/work/v12_3min_1470_1650"
D=json.load(open(W+"/lines_v5.json",encoding="utf-8"))
REF6=W+"/orig_voice_refs_v6"; GEN=W+"/generated_wavs_v6"
T0,T1=D["window"]; SR=24000
TARGET={0,6,9,11,12,17}
rep=json.load(open(W+"/v6_gen_report.json",encoding="utf-8"))
txtmap={}
for r in rep:
    if r["vid"] in TARGET: txtmap[r["vid"]]=r["text"]
def start_trim(a,sr_):
    if len(a)<int(1.2*sr_): return a
    fl=int(0.03*sr_); peak=np.max(np.abs(a))+1e-9; thr=0.10*peak; run=0
    for i in range(0,min(len(a),int(0.6*sr_)),fl):
        if np.max(np.abs(a[i:i+fl]))>thr:
            run+=1
            if run>=3:
                on=max(0,i-2*fl)
                return a[on:] if on<int(0.5*sr_) else a
        else: run=0
    return a
def speedup(a,f):
    if f<=1.001: return a
    n=int(len(a)/f)
    return np.interp(np.linspace(0,len(a),n,endpoint=False),np.arange(len(a)),a).astype(np.float32)
dev="cuda" if torch.cuda.is_available() else "cpu"
model=AutoModel.from_pretrained("ai4bharat/IndicF5",trust_remote_code=True).to(dev)
print("model on",dev,flush=True)
lines=sorted(D["lines"],key=lambda L:L["abs_start"])
for i,L in enumerate(lines):
    vid=L["vid"]
    if vid not in TARGET: continue
    nxt=lines[i+1]["abs_start"] if i+1<len(lines) else T1
    avail=min(nxt,T1)-L["abs_start"]-0.15
    hi=txtmap.get(vid,L["hindi"])
    rw=REF6+"/ref_%s.wav"%L["actor"]; rt=open(REF6+"/ref_%s.txt"%L["actor"],encoding="utf-8").read().strip()
    for c in (3,4):
        audio=model(hi,ref_audio_path=rw,ref_text=rt)
        a=np.array(audio,dtype=np.float32)
        if a.size<SR//8: print("  V%02d_c%d empty"%(vid,c),flush=True); continue
        if np.max(np.abs(a))>1.5: a=a/32768.0
        a=a/(np.max(np.abs(a))+1e-9)*0.9
        a=start_trim(a,SR); gen=len(a)/SR
        if avail>0.4 and gen>avail*1.15+0.4: print("  V%02d_c%d long %.1f"%(vid,c,gen),flush=True); continue
        f=max(1.0,min(1.15,gen/avail)) if avail>0.4 else 1.0
        a=speedup(a,f)
        sf.write("%s/V%02d_c%d.wav"%(GEN,vid,c),a,SR)
        rep.append({"vid":vid,"cand":c,"text":hi,"final":round(len(a)/SR,2),"avail":round(avail,2),"speed":round(f,2)})
        print("  V%02d_c%d final=%.2f"%(vid,c,len(a)/SR),flush=True)
json.dump(rep,open(W+"/v6_gen_report.json","w",encoding="utf-8"),indent=1,ensure_ascii=False)
print("V6_PATCH3_DONE",flush=True)
