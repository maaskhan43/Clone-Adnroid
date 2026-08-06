import json, os, glob, numpy as np, soundfile as sf, torch
W="/mnt/d/CloneDub/work/v12_3min_1470_1650"
VOX="/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/vocals.wav"
D=json.load(open(W+"/lines_v5.json",encoding="utf-8"))
CER={c["vid"]:c for c in json.load(open(W+"/v7_vc_cer.json",encoding="utf-8"))}
REF6=W+"/orig_voice_refs_v6"
T0,T1=D["window"]; SCENE=T1-T0; SR=24000; ORIG={1,10,14}
pred=torch.hub.load("tarepan/SpeechMOS:v1.2.0","utmos22_strong",trust_repo=True)
from speechbrain.inference.speaker import EncoderClassifier
enc=EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",savedir="/mnt/d/CloneDub/hf_cache/ecapa_sb",run_opts={"device":"cpu"})
def emb_wav(a,sr):
    if a.ndim>1: a=a.mean(1)
    a=a.astype(np.float32)
    if sr!=16000:
        n=int(len(a)*16000/sr); a=np.interp(np.linspace(0,len(a),n,endpoint=False),np.arange(len(a)),a).astype(np.float32)
    with torch.no_grad(): e=enc.encode_batch(torch.tensor(a).unsqueeze(0)).squeeze().cpu().numpy()
    return e/(np.linalg.norm(e)+1e-9)
refemb={}
for n in ("F_A","F_B","M"):
    a,sr=sf.read(REF6+"/ref_%s.wav"%n); refemb[n]=emb_wav(a,sr)
lines={L["vid"]:L for L in D["lines"]}
res=[]
for fn in sorted(glob.glob(W+"/generated_wavs_v7_vc/V*.wav")):
    vid=int(os.path.basename(fn)[1:3]); L=lines[vid]
    a,sr=sf.read(fn)
    if a.ndim>1: a=a.mean(1)
    with torch.no_grad(): u=float(pred(torch.from_numpy(a.astype(np.float32)).unsqueeze(0),sr))
    sim=float(np.dot(emb_wav(a,sr),refemb[L["actor"]]))
    cer=CER.get(vid,{}).get("cer",-1)
    res.append({"vid":vid,"cer":cer,"utmos":round(u,2),"sim":round(sim,2)})
    print("V%02d cer=%5.1f utmos=%.2f sim=%.2f"%(vid,cer,u,sim),flush=True)
json.dump(res,open(W+"/v7_final_scores.json","w"),indent=1)
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
        fn=W+"/generated_wavs_v7_vc/V%02d.wav"%vid
        if not os.path.exists(fn): continue
        a,sr=sf.read(fn)
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
sf.write(W+"/scene_3min_v7.wav",mix.astype(np.float32),SR)
print("V7_FINAL_DONE")
