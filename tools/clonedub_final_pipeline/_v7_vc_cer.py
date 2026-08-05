import json, os, re, glob, unicodedata
from faster_whisper import WhisperModel
W="/mnt/d/CloneDub/work/v12_3min_1470_1650"
best=json.load(open(W+"/v7_clean_best.json"))
rep=json.load(open(W+"/v7_clean_report.json",encoding="utf-8"))
txt={(r["vid"],r["cand"]):r["text"] for r in rep}
def norm(s):
    s=unicodedata.normalize("NFC",s); s=re.sub(r"[^ऀ-ॿ ]","",s); return re.sub(r"\s+","",s)
def lev(a,b):
    if not a: return len(b)
    if not b: return len(a)
    prev=list(range(len(b)+1))
    for i,ca in enumerate(a):
        cur=[i+1]
        for j,cb in enumerate(b):
            cur.append(min(prev[j+1]+1,cur[j]+1,prev[j]+(ca!=cb)))
        prev=cur
    return prev[-1]
m=WhisperModel("small",device="cpu",compute_type="int8")
out=[]
for fn in sorted(glob.glob(W+"/generated_wavs_v7_vc/V*.wav")):
    vid=int(os.path.basename(fn)[1:3])
    c=best.get(str(vid))
    target=txt.get((vid,c["cand"])) if c else None
    if not target: continue
    segs,_=m.transcribe(fn,task="transcribe",beam_size=5,language="hi")
    hyp=" ".join(s.text.strip() for s in segs).strip()
    cer=100.0*lev(norm(target),norm(hyp))/max(len(norm(target)),1)
    out.append({"vid":vid,"cer":round(cer,1),"heard":hyp})
    print("V%02d CER=%5.1f | %s"%(vid,cer,hyp[:40]),flush=True)
json.dump(out,open(W+"/v7_vc_cer.json","w",encoding="utf-8"),indent=1,ensure_ascii=False)
print("V7VC_CER_DONE")
