# CloneDub Orchestrator Design (`dub_scene.py`)
**Goal:** proven FINAL pipeline ko ek repeatable command banana — zero manual glue, zero guess.
```
python3 tools/clonedub_final_pipeline/dub_scene.py --config scene.json [--status|--from STAGE|--until STAGE]
```

## Config (per scene JSON)
```json
{
  "video": "/mnt/d/CloneDub/videos/video1.mp4",
  "vocals": ".../demucs/htdemucs/full/vocals.wav",
  "no_vocals": ".../demucs/htdemucs/full/no_vocals.wav",
  "t0": 1470.0, "t1": 1650.0,
  "workdir": "/mnt/d/CloneDub/work/scene_video1_1470_1650",
  "diar_margin": 210,
  "clean_refs": "/mnt/d/CloneDub/work/v12_indicf5_refs",
  "actor_registry": "/mnt/d/CloneDub/work/video1_actors",   // optional shared refs
  "out_name": "scene_video1_1470_1650"
}
```

## Stages (order, venv, I/O, done-marker)
| # | Stage | venv | output (workdir/) | marker |
|---|---|---|---|---|
| 1 | diarize | pyannote_venv | diar/turns.json | .done_diarize |
| 2 | asr_words | SoniTranslate | asr_words.json | .done_asr |
| 3 | lines_build (a1+a2 merge) | SoniTranslate (2nd-pass ASR) + system | wordlines.json | .done_lines |
| 4 | gender | indicf5_py310 | gender.json | .done_gender |
| 5 | actors+refs (a3b/b_finalize+v6_refs logic) | chatterbox_v3_venv | actors.json, refs/ref_*.{wav,txt} | .done_actors |
| 6 | **TRANSLATION GATE** | — (LLM/human) | translations.json | .done_translate |
| 7 | clean_gen (candidates+tiers) | indicf5_py310 | gen_clean/V*_c*.wav | .done_cleangen |
| 8 | clean_cer -> best picks | SoniTranslate | clean_cer.json, clean_best.json | .done_cleancer |
| 9 | seedvc pass | seedvc_venv | gen_vc/V*.wav | .done_vc |
| 10 | direct actor-TTS candidates (v6-style, for hybrid pool) | indicf5_py310 | gen_direct/V*_c*.wav | .done_direct |
| 11 | judge_all (CER+UTMOS+sim) + hybrid pick | SoniTranslate + chatterbox | scores.json, picks.json | .done_judge |
| 12 | assemble (+original interjections, bed 0.6x) | indicf5_py310 | scene.wav | .done_assemble |
| 13 | acceptance audit (gender probes, overlap=0, coverage>=95%, CER<=40) | indicf5 | audit.json — **FAIL = STOP** | .done_audit |
| 14 | mux | ffmpeg | {out_name}.mp4 + copy to D:\CloneDub | .done_mux |

## Design rules
- **Checkpoint/resume:** har stage apna marker file likhta hai; dobara run = complete stages skip. `--from X` marker delete karke wahan se.
- **Venv routing:** orchestrator khud sahi venv ke python se stage-script subprocess chalata hai (stage scripts standalone hain, env var `DUB_CONFIG` se config).
- **Launch verification:** har subprocess ke baad `log exists + marker check` (WSL nohup trap ka jawab).
- **Gates:**
  - **Stage 6 (translation):** orchestrator `translation_todo.json` (zh text + slot + word-budget ~2.6w/s + tier suggestion) likh ke EXIT karta hai. Claude/user `translations.json` bhar de (tiers included), phir resume.
  - **Stage 13 (acceptance):** koi test fail → mux NAHI hota, report print hoti hai.
- **Tiny lines rule:** <0.9s non-lexical → original audio; <1.2s → no start-trim, no Seed-VC (direct pool se).
- **Disk guard:** start pe free<10G → abort with message. numpy guard: har venv me 1.26.4 assert.
- **Idempotent filenames:** sab stage outputs workdir-relative, koi absolute hardcode nahi.

## Actor registry (multi-scene consistency)
Pehli scene ke baad `actor_registry` dir me refs+centroids save; agli scenes apne clusters ko registry se ECAPA-match karti hain (sim>0.6 → same actor id + same ref). Nahi mila → naya actor add.

## Test plan
1. `--status` on proven scene (mapped artifacts) → sab stages DONE dikhein
2. Fresh small scene (2 min, video1 ka koi aur hissa) → end-to-end run → acceptance PASS
