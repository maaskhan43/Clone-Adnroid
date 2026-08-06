# CloneDub FINAL Pipeline (v13) — PROVEN RECIPE
**Status: USER-APPROVED on 3-min testbed (video1 @1470-1650s) — 2026-08-05**
**Result: `D:\CloneDub\scene_3min_FINAL.mp4` — mean CER 20.2%, UTMOS beats original on 18/21 slots, 9/9 end-to-end audit PASS**

Ye document isliye hai taaki agle video/scene pe **kuchh bhi guess na karna pade**. Har step, har venv, har threshold yahan hai. Scripts: `tools/clonedub_final_pipeline/`.

---

## Architecture (kyun ye kaam karta hai)

**2-stage split — pronunciation aur voice identity ALAG:**
1. **Clean TTS**: IndicF5 + studio-clean Hindi refs → perfect pronunciation (CER 21%)
2. **Seed-VC**: zero-shot voice conversion (4-9s actor ref kaafi) → actor ki awaaz ka timbre
3. **Machine judge**: har line ke saare candidates (clean-TTS, VC, purane) → best-of pick by composite `(-CER + 15*sim)`
4. **Non-lexical interjections** (हुँह/अरे/जी हाँ jaisi <1s cheezein): **ORIGINAL actor audio hi rakho** — TTS/VC dono <1s pe fail

## Venvs (D:\CloneDub\) — MAT CHHEDNA
| venv | kya | key pins |
|---|---|---|
| `indicf5_py310` | IndicF5 TTS | **numpy 1.26.4** (2.x = _ARRAY_API crash!) |
| `pyannote_venv` | diarization 3.1 | torch 2.2 (speechbrain yahan NAHI chalta) |
| `chatterbox_v3_venv` | judges: UTMOS(torch.hub) + ECAPA + speechbrain | torch 2.6 |
| `seedvc_venv` | Seed-VC | torch 2.4 pin (unki requirements), numpy 1.26.4 |
| SoniTranslate `.venv` | faster-whisper (ASR/CER) | — |

## Per-scene steps (naya video/scene)

```
0. demucs (full video ek baar): vocals.wav + no_vocals.wav
1. DIARIZE window+margin (pyannote_venv, scene±3.5min): _inv script pattern
2. WORD-ASR (SoniTranslate): faster-whisper small, word_timestamps=True, vad_filter=True
   -> asr_words.json (ground truth)                            [_inv_asr_words.py]
3. LINE BUILD (a1_wordlines.py): words × turns, pad ±0.25s, majority-smooth w3,
   split at speaker change / gap>0.8s / cap 12s
4. 2ND-PASS ASR (a2_secondpass.py): empty turns -> slice+boost+no-VAD -> recover
   quiet lines (dheeme male lines yahi milti hain!)
5. GENDER per line (JaesungHuh, indicf5 venv): pad to 0.9s min      [a4 pattern]
6. ACTORS (a3b_actors.py + b_finalize.py): ECAPA cluster within-gender
   (avg-linkage 0.5), K=2 female force, <1.2s lines -> nearest-in-time same-gender,
   merge adjacent same-actor, fold <0.5s zero-gap sentence tails
7. ACTOR REFS (v6_refs.py + patch): SINGLE CONTINUOUS 6-11s clip (score=2*dur+SNR),
   KABHI concat nahi, transcript EXACT from word-ASR, +0.35s end-silence.
   Male material kam ho to purana proven ref rakho.
8. TRANSLATE lines: Urdu+Eng Devanagari, ~2.6 words/sec of slot, text TIERS
   (normal/short/shorter) for tight slots
9. CLEAN GEN (_v7_clean_gen.py): IndicF5 + work/v12_indicf5_refs/ref_{male,female}
   2 candidates/line, energy start-trim (>1.2s only), speed cap 1.15, no trim
10. CER JUDGE clean (whisper-hi) -> best clean pick               [_v7_vc_cer.py pattern]
11. SEED-VC pass (_v7_vc_pass.sh): diffusion 30, length-adjust 1.0, f0-condition False
    RTF~21 on GTX1650 (~35min/18 lines)
12. FINAL JUDGE + HYBRID (_v7_final.py + _v8_hybrid.py): pick best of
    {clean-VC, direct-actor-TTS} per line by (-CER + 15*sim)
13. ASSEMBLE: onsets pe place, interjections original se, bed no_vocals*0.6
14. ACCEPTANCE AUDIT (har scene, mux se pehle — FAIL to wapas):
    - har missed-male moment audible? gender-probe PASS?
    - overlap count = 0?
    - word coverage >= 95%?
    - koi line CER > 40%?
    - UTMOS-vs-original slots
15. MUX: ffmpeg -ss START -t DUR video + wav -> mp4
```

## GOTCHAS (yahan pehle fuck-up hua tha — repeat mat karna)
1. **ASR segments multi-speaker merge karta hai** (median 19.7s segments) — kabhi segment-level speaker assignment mat karo, hamesha word-level
2. **IndicF5 kabhi EMPTY audio deta hai** — retry chain (main ref -> short ref -> skip+log)
3. **F5 ka 200-400ms onset garble** documented hai — start-trim zaroori (par <1.2s lines pe NAHI)
4. **Refs 8-12s continuous** — 15s+ = sped-up garble; concat = boundary artifacts; noisy(SNR<25) = "pachka" (noise copy hota hai output mein)
5. **Seed-VC <1s clips ko bigaad deta hai** (V15: 100% CER) — chhoti lines direct-TTS ya original
6. **numpy 2.x install = IndicF5 crash** — koi bhi pip install se pehle numpy pin check
7. **WSL nohup kabhi silently fail hota hai** — launch ke baad `log exists + ps alive` verify
8. **Disk 90%+ pe Bus error aata hai** — pehle space check (pip cache 5.6G clearable)
9. **whisper-small ka CER <1s clips pe bharosemand nahi** — unverifiable treat karo, kaan se judge
10. **Kaggle kernel via API hi run karo** (kaggle.com editor kills runs), T4 = `NvidiaTeslaT4`
11. pip `speechmos` = Microsoft DNSMOS; UTMOS = torch.hub `tarepan/SpeechMOS` (repo pip package ko shadow karta hai — alag process mein chalao)

## Machine judges (quality gate — har run pe)
- **CER**: whisper-hi transcribe vs target (Devanagari-normalized Levenshtein). Pass < 40%, target < 25%
- **UTMOS**: relative use karo (original drama slots ~1.3-1.5 baseline)
- **ECAPA sim**: line vs actor ref. Female >0.45 achha; male 0.3+ chalega (ref chhota hai)
- **End-to-end audit**: gender-probe key moments, overlaps=0, coverage>=95%

## Scale-up ke liye baaki kaam (agla phase)
- Ek orchestrator script jo steps 1-15 ko ek scene-config se chalaye
- Scene boundaries: video ko 3-5 min windows mein kaato (silence/music pe cut)
- Actor registry: ek baar per-video actors+refs banao, saare scenes share karein
- Lip-sync (LatentSync/Kaggle) FINAL ke upar — proven flow already hai
- Translation: abhi lines maine likhi thin — scale pe LLM-assisted + length-fit loop
