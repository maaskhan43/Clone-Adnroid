# CloneDub V11 - Professional Dub System Master Plan

Status: planning baseline created 2026-07-29. This plan replaces random TTS experiments with a measured software-first build.

## 0. Objective

Build our own professional dubbing pipeline for Chinese/Korean drama videos into Hindi/Hinglish, where the final video feels like the character is actually speaking, not like external narration placed over video.

This is not a one-night output plan. This is a months-level software plan with required video outputs at every milestone.

Core rule:

```text
No phase is accepted without a playable video sample and objective comparison against our benchmark references.
```

## 1. Current truth

### 1.1 What already works

We already have a working local/Kaggle dubbing foundation:

- source ingest and FFmpeg operations;
- source audio extraction;
- vocal/music separation artifacts;
- Whisper/WhisperX-style transcription artifacts;
- diarization/gender artifacts;
- translation/rewrite artifacts;
- generated Hindi/Hinglish dialogue artifacts;
- final mix/mux logic;
- LatentSync full-video experience;
- QA-style receipts/reports;
- Android/CloneCast side project for narration/voice-conversion experiments.

Important current baseline output:

```text
D:\CloneDub\outputs\v1_indian_cinematic_full\video1_v1_indian_cinematic_latentsync_full.mp4
```

This is useful as a working full-video baseline, but it is not the target quality.

### 1.2 What failed

These paths did not reach the required "real dub" feel:

- Fish voice clone/fixed voices;
- Azure Hindi SSML;
- ElevenLabs TTS;
- ElevenLabs S2S using TTS source audio;
- timing-only / speech-density-only hacks;
- Azure-based V11 forced-density attempts.

Reason:

```text
The missing part is not only timing, lip-sync, or mix.
The missing part is convincing acted voice generation plus rewrite plus timing together.
```

### 1.3 Gold reference

The Rask 1-minute result is a benchmark proving that a real-feeling dub is possible. It is not the product identity and not something to copy blindly.

```text
D:\CloneDub\outputs\rask_success_reference\meteor_rask_900_960_hindi_success.mp4
```

Original 1-minute source used for that benchmark:

```text
D:\CloneDub\outputs\rask_test_input\meteor_original_900_960_for_rask_1min.mp4
```

Analysis workspace:

```text
D:\CloneDub\work\rask_analysis\
```

Important analysis result from 900-960s:

```text
Original active speech: ~48.47s / 60s
Rask active speech:     ~49.69s / 60s
Old V1 active speech:   ~36.27s / 60s
```

But active-speech coverage is only a diagnostic. It is not allowed to be gamed with fake filler, repeated texture, or murmur audio.

## 2. Non-negotiable principles

1. Rask reference is a benchmark, not code to copy and not the final style limit.
2. Do not use `D:\.Clone\Vask` as backend source; it contains frontend/marketing/tracking assets, not the real dubbing engine.
3. No fake filler audio to satisfy metrics.
4. No extreme stretch that makes words sound like `karrrrr`, `nayyyi`, `suruwaaat`.
5. Every experiment must output a playable MP4.
6. Every experiment must be compared to:
   - original source,
   - benchmark reference,
   - previous best CloneDub output.
7. A metric pass without human-perceived improvement is a failure.
8. Full 45-minute processing is forbidden until the 60s and 3-minute gates pass.
9. Keep existing completed outputs untouched.
10. Work in isolated V11 folders only.

## 3. Folder contract

All V11 work must stay under these namespaces:

```text
D:\.Clone\tools\clonedub_v11_*.py
D:\.Clone\CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md
D:\CloneDub\work\v11_*
D:\CloneDub\outputs\v11_*
D:\CloneDub\outputs\rask_success_reference\
```

Do not write V11 experiments into:

```text
D:\CloneDub\outputs\v1_indian_cinematic_full\
D:\CloneDub\work\video1_meteor_video_clone\
D:\CloneDub\outputs\rask_success_reference\
```

except read-only comparison and explicit reference copying.

## 4. Phase gates overview

```text
Phase 0: Asset freeze and reference audit
Phase 1: Evaluator-first system
Phase 2: Dialogue rewrite engine
Phase 3: Voice model bake-off
Phase 4: Timing/regeneration loop
Phase 5: Mix and room integration
Phase 6: Lip-sync region policy
Phase 7: 3-minute integrated pilot
Phase 8: 10-minute pilot
Phase 9: full episode production
```

Each phase has:

- input contract;
- implementation task;
- output artifact;
- objective gate;
- human listening/viewing gate;
- stop condition.

## 5. Phase 0 - Asset freeze and reference audit

Goal: make the current known-good and known-bad assets explicit, immutable, and measurable.

### Inputs

Required:

```text
D:\CloneDub\outputs\rask_success_reference\meteor_rask_900_960_hindi_success.mp4
D:\CloneDub\outputs\rask_test_input\meteor_original_900_960_for_rask_1min.mp4
D:\CloneDub\outputs\v1_indian_cinematic_full\video1_v1_indian_cinematic_latentsync_full.mp4
```

### Implementation

Create:

```text
D:\CloneDub\work\v11_reference_audit\
```

Generate:

- `reference_manifest.json`
- `original_900_960.wav`
- `rask_900_960.wav`
- `v1_900_960.wav`
- `metrics.json`
- `envelope_comparison.png`
- `stream_report.json`

### Required measurements

For each video/audio:

- duration;
- video resolution/FPS;
- audio codec, channels, sample rate;
- RMS;
- peak;
- active speech seconds;
- active windows;
- median speech-window length;
- median gap length;
- rough ASR transcript if model available.

### Gate

Phase 0 passes only if:

```text
Rask reference exists
Original source exists
Old V1 baseline exists
All three extract to WAV
metrics.json exists
No current output is modified
```

### Stop condition

Stop if the benchmark reference file is missing or is not exactly a playable 60s MP4.

## 6. Phase 1 - Evaluator-first system

Goal: build a reliable evaluator before generating new dub output.

This is the first real implementation phase. It must happen before more TTS/model tests.

### Tool to create

```text
D:\.Clone\tools\clonedub_v11_evaluate.py
```

### CLI contract

```powershell
wsl -e bash -lc '
cd /mnt/d/.Clone
/home/moin/SoniTranslate/.venv/bin/python tools/clonedub_v11_evaluate.py \
  --original /mnt/d/CloneDub/outputs/rask_test_input/meteor_original_900_960_for_rask_1min.mp4 \
  --reference /mnt/d/CloneDub/outputs/rask_success_reference/meteor_rask_900_960_hindi_success.mp4 \
  --candidate /mnt/d/CloneDub/outputs/v1_indian_cinematic_full/video1_v1_indian_cinematic_latentsync_full.mp4 \
  --candidate-start 900 \
  --duration 60 \
  --outdir /mnt/d/CloneDub/work/v11_eval_v1_vs_rask
'
```

### Required output

```text
D:\CloneDub\work\v11_eval_v1_vs_rask\eval.json
D:\CloneDub\work\v11_eval_v1_vs_rask\scorecard.md
D:\CloneDub\work\v11_eval_v1_vs_rask\envelope.png
D:\CloneDub\work\v11_eval_v1_vs_rask\activity_windows.json
D:\CloneDub\work\v11_eval_v1_vs_rask\audio_extracts\
```

### Evaluator dimensions

The evaluator must report, not hide:

1. Duration match.
2. Stream contract.
3. Active speech coverage.
4. Speech window alignment to original.
5. Gap/silence mismatch.
6. Candidate RMS vs benchmark RMS.
7. Candidate peak vs benchmark peak.
8. Candidate speech density vs benchmark and original source.
9. Candidate ASR readability/transcript confidence if available.
10. Obvious red flags:
    - too much silence while original is speaking;
    - dialogue too hot;
    - dialogue too low;
    - repeated/filler audio suspicion;
    - very long continuous narration block.

### Gate

Phase 1 passes only if evaluator correctly marks current V1 as below professional benchmark. Expected:

```text
V1 must fail one or more professional-dub checks such as speech coverage, alignment, mix, acting feel, or voice integration.
```

If evaluator says V1 is good, evaluator is wrong and must be fixed.

## 7. Phase 2 - Dialogue rewrite engine

Goal: stop literal/explanatory translations and generate short, acted Hindi/Hinglish lines.

### Tool to create

```text
D:\.Clone\tools\clonedub_v11_rewrite.py
```

### Input

- original transcript segments;
- benchmark transcript/rough ASR if available;
- original speech windows;
- target duration per line/block;
- speaker identity/gender when available.

### Output

```text
D:\CloneDub\work\v11_rewrite_900_960\script_blocks.json
D:\CloneDub\work\v11_rewrite_900_960\script_blocks.srt
D:\CloneDub\work\v11_rewrite_900_960\rewrite_report.md
```

### Script block schema

Each block must include:

```json
{
  "id": "b000",
  "start": 900.03,
  "end": 906.65,
  "speaker": "SPEAKER_04",
  "gender": "female",
  "source_text": "...",
  "target_text_hi": "...",
  "style": "curious, conversational",
  "target_seconds": 6.62,
  "max_words": 18,
  "must_not": ["literal textbook explanation", "fake filler", "word stretching"]
}
```

### Gate

Phase 2 passes only if:

- script reads like spoken movie dialogue;
- no line is explanatory paragraph unless source is narration;
- target words/seconds is realistic;
- user approves the text style for the 60s sample.

No TTS generation before this gate.

## 8. Phase 3 - Voice model bake-off

Goal: choose a voice generation path based on measured and human-perceived quality, not guessing.

### Candidates

Initial candidates:

1. Rask output as benchmark reference only.
2. Azure Hindi Neural with Phase 2 script.
3. Fish voice clone with Phase 2 script.
4. ElevenLabs only if Hindi-capable voice/API access is available.
5. Open-source model candidates only after evaluator exists.

### Output per candidate

```text
D:\CloneDub\outputs\v11_voice_bakeoff\candidate_<name>_900_960.mp4
D:\CloneDub\work\v11_voice_bakeoff\candidate_<name>\eval.json
D:\CloneDub\work\v11_voice_bakeoff\candidate_<name>\scorecard.md
```

### Required constraints

- No S2S from robotic source as final candidate.
- No generated candidate is accepted if user says it feels like external audio.
- No candidate is promoted solely due to numeric score.

### Gate

Phase 3 passes only if one candidate is clearly better than current V1 by:

- evaluator score;
- user listening/viewing approval;
- no severe robotic/accent/stretch issue.

If no candidate passes, Phase 3 outcome is:

```text
voice model bottleneck confirmed
```

Then we research/train better model before moving forward.

## 9. Phase 4 - Timing and regeneration loop

Goal: generate natural audio that fits the actor speech window without fake filler or extreme stretching.

### Rules

For each block:

1. Generate audio.
2. Trim leading/trailing silence.
3. Measure actual speech duration.
4. If too long, rewrite shorter and regenerate.
5. If too short, rewrite fuller and regenerate.
6. Only mild time-stretch allowed.
7. Reject if still bad after bounded attempts.

### Hard limits

```text
Allowed time-stretch: 0.92x to 1.08x preferred
Emergency max:        0.88x to 1.12x
Never use fake filler to satisfy mouth movement
```

### Gate

For 900-960s:

- no obvious early-end while mouth still moving;
- no stretched words;
- no overlaid narration feel;
- evaluator improves over V1;
- user approves playback.

## 10. Phase 5 - Mix and room integration

Goal: make the generated voice sit inside the scene.

### Required work

- match professional source/benchmark RMS range;
- preserve music/ambience;
- duck M&E only during dialogue;
- avoid hot voiceover;
- optional room tone/reverb matching;
- no original Chinese leakage in final dialogue area.

### Gate

Candidate mix must not sound like:

```text
video is running and audio is separately playing
```

If it does, Phase 5 fails.

## 11. Phase 6 - Lip-sync region policy

Goal: only use lip-sync where it improves the shot.

### Rules

- close-up speaking face: process;
- wide/distant/no-face/back-shot: preserve original video;
- no processing if face detection is weak;
- no full-frame hallucination damage for low-quality shots.

### Gate

60s candidate must have:

- no damaged face;
- no processed wide-shot artifacts;
- muxed final audio only;
- one video stream and one audio stream.

## 12. Phase 7 - 3-minute integrated pilot

Goal: prove the system generalizes beyond one 60s section.

### Input

Select a 3-minute section containing:

- at least two speakers;
- one narration-heavy stretch;
- one emotional/dialogue stretch;
- one wide-shot region.

### Output

```text
D:\CloneDub\outputs\v11_pilot_3min\meteor_v11_pilot_3min.mp4
D:\CloneDub\work\v11_pilot_3min\eval.json
D:\CloneDub\work\v11_pilot_3min\scorecard.md
```

### Gate

User must approve that it feels materially more like a real professional dub than V1.

## 13. Phase 8 - 10-minute pilot

Goal: test scale, cache, regeneration, and scene variety.

### Gate

Pass only if:

- no catastrophic TTS/voice drift;
- no repeated voices across wrong gender/speaker unless intentionally mapped;
- no major sync detachment;
- no accidental original Chinese dialogue in final mix;
- output is watchable without constant debugging notes.

## 14. Phase 9 - full episode

Only after Phases 1-8 pass.

Output:

```text
D:\CloneDub\outputs\v11_full_episode\meteor_v11_full.mp4
```

Full episode must be generated in resumable chunks:

```text
0-10 min
10-20 min
20-30 min
30-40 min
40-end
```

Each chunk must have its own eval report before final merge.

## 15. What not to do next

Do not:

- run full 45-minute video now;
- do another random Fish/Azure/Eleven test;
- optimize only active speech seconds;
- use fake voiced filler;
- copy frontend service scripts as if they are backend;
- edit production V1 workdirs;
- spend Kaggle hours before the 60s evaluator and script gates pass.

## 16. Immediate next implementation task

The next task is Phase 1 only:

```text
Build tools/clonedub_v11_evaluate.py
Run it on original vs benchmark vs V1
Prove it correctly identifies why V1 fails
```

No TTS, no dubbing generation, no full-video work before Phase 1 passes.

## 17. Definition of success

The project is successful only when:

```text
Our generated video is judged professional and character-attached by both objective evaluator and user viewing,
without relying on Rask service for generation,
and can scale from 60s -> 3min -> 10min -> full episode.
```

Until then, Rask remains one benchmark and current best external production option.



