# -*- coding: utf-8 -*-
# V7 Stage 1: every TTS line with CLEAN studio Hindi refs (perfect pronunciation),
# 2 candidates each. Texts = the final v6-picked texts. Duration-fit as before.
import os, json, numpy as np, soundfile as sf, torch
from transformers import AutoModel
W="/mnt/d/CloneDub/work/v12_3min_1470_1650"
D=json.load(open(W+"/lines_v5.json",encoding="utf-8"))
J=json.load(open(W+"/v6_judge_final.json"))
rep6=json.load(open(W+"/v6_gen_report.json",encoding="utf-8"))
txt6={(r["vid"],r["cand"]):r["text"] for r in rep6}
CLEAN="/mnt/d/CloneDub/work/v12_indicf5_refs"
GEN=W+"/generated_wavs_v7_clean"; os.makedirs(GEN,exist_ok=True)
T0,T1=D["window"]; SR=24000; SKIP={1,10,14}
def start_trim(a,sr_):
    if len(a)<int(1.2*sr_): return a
    fl=int(0.03*sr_); thr=0.10*(np.max(np.abs(a))+1e-9); run=0
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
rep=[]
for i,L in enumerate(lines):
    vid=L["vid"]
    if vid in SKIP: continue
    pick=J["best"].get(str(vid)) or J["best"].get(vid)
    hi=txt6.get((vid,pick["cand"]),L["hindi"]) if pick else L["hindi"]
    if pick and pick["cand"]==9: hi=L["hindi"]
    g="male" if L["gender"]=="male" else "female"
    rw=CLEAN+"/ref_%s.wav"%g; rt=open(CLEAN+"/ref_%s.txt"%g,encoding="utf-8").read().strip()
    nxt=lines[i+1]["abs_start"] if i+1<len(lines) else T1
    avail=min(nxt,T1)-L["abs_start"]-0.15
    for c in range(2):
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
        rep.append({"vid":vid,"cand":c,"text":hi,"final":round(len(a)/SR,2),"avail":round(avail,2)})
        print("  V%02d_c%d final=%.2f | %s"%(vid,c,len(a)/SR,hi[:24]),flush=True)
json.dump(rep,open(W+"/v7_clean_report.json","w",encoding="utf-8"),indent=1,ensure_ascii=False)
print("V7_CLEAN_DONE n=%d"%len(rep),flush=True)
