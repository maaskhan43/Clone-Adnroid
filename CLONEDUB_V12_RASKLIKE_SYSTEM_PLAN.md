# CloneDub V12 - Rask-like Dubbing System Plan

Status: master plan started 2026-07-30 after V11 listening failures.

This plan is for building our own best-version dubbing system over months. It is not a plan to copy Rask, scrape Rask, or depend on a single provider. "Rask-like" means the output feels like a finished video dub: character speech belongs inside the scene, timing feels motivated by the actor, and the final mix feels like one coherent video.

## 0. Hard decision from V11

V11 proved that the current architecture cannot be fixed by tuning one knob.

Tested and rejected by human listening:

- voice/provider bakeoff: Old V1 vs Eleven vs Fish;
- clean-text 3-minute Eleven/Fish preview;
- Rask-style mix/bed/forwardness variants;
- actor-beat rewrite with distinct per-character Fish voices.

Conclusion:

```text
The failure is architectural, not one bad TTS provider or one bad mix setting.
```

The old pipeline is useful as an artifact factory, but not as the final product architecture.

## 1. New objective

Build CloneDub V12: a video-first dubbing system for Chinese/Korean drama to Hindi/Hinglish that produces actor-like, scene-aware dub output.

Target output:

- not narration over video;
- not literal segment translation;
- not one TTS voice per diarization label blindly;
- not just louder/softer/remixed speech;
- character-specific acted lines that match the scene, speaker, emotion, pause, interruption, and shot context.

Acceptance rule:

```text
No phase is accepted unless a human listening gate says the sample is closer to real dub than the previous baseline.
```

## 2. Current assets we keep

These remain valuable:

- source video and extracted audio handling;
- FFmpeg operations;
- Whisper/WhisperX timing artifacts;
- diarization/gender artifacts, but not blindly trusted;
- vocal/music stems;
- full V1 baseline output;
- Rask 900-960 reference;
- LatentSync experience for selected regions;
- evaluation tools created in V11:
  - `clonedub_v11_evaluate.py`
  - `clonedub_v11_style_profile.py`
  - `clonedub_v11_textguard.py`
  - `clonedub_v11_understandability.py`
  - `clonedub_v11_gen_scene.py`

Important known files:

```text
D:\CloneDub\outputs\v1_indian_cinematic_full\video1_v1_indian_cinematic_latentsync_full.mp4
D:\CloneDub\outputs\rask_success_reference\meteor_rask_900_960_hindi_success.mp4
D:\CloneDub\outputs\rask_test_input\meteor_original_900_960_for_rask_1min.mp4
D:\CloneDub\work\v11_phase6a_performance_plan_1500_1561\
D:\CloneDub\work\v11_phase6b_gen_test_1500_1561\
```

## 3. What we stop doing

Stop these loops unless a later phase has a precise reason:

- random TTS provider swapping;
- generating long video before a small scene passes;
- using diarization speaker IDs as voice identity without visual role confirmation;
- literal segment-by-segment translation;
- trying to fix acting with only EQ/compression/ducking;
- assuming high metric scores mean good dub feel;
- full-video LatentSync before audio/performance passes.

## 4. V12 architecture

V12 is not one script. It is a set of cooperating modules.

### 4.1 Scene understanding layer

Purpose: decide what is happening in the scene before writing or generating speech.

Inputs:

- source video clip;
- original audio;
- subtitles/transcript if available;
- ASR/diarization artifacts;
- optional frame contact sheets.

Outputs:

- scene type: narration, dialogue, argument, romance, comedy, action, silence, song;
- speaker/face role candidates;
- visible speaker confidence;
- emotional beats;
- interruption/overlap points;
- non-dialogue regions.

Rule:

```text
If role identity is uncertain, mark it explicitly. Do not collapse multiple visible actors into one voice.
```

### 4.2 Actor-lane tracker

Purpose: maintain stable character lanes across scenes.

Actor lane is not the same as diarization speaker.

Actor lane fields:

- `actor_lane_id`
- screen identity evidence
- gender guess
- voice assignment
- confidence
- needs human review
- linked diarization labels
- linked face tracks

Acceptance:

- no generation can use only `SPEAKER_XX`;
- every generated line must map to an `actor_lane_id`;
- uncertain lanes must either be human-approved or best-effort distinct.

### 4.3 Performance script writer

Purpose: transform source meaning into acted Hindi/Hinglish lines.

This module writes scene-level performance scripts, not literal translation.

Line fields:

- timestamps;
- actor lane;
- intent;
- energy;
- delivery note;
- pause after;
- overlap allowed;
- target text;
- literal source meaning;
- why it is not literal translation.

Rules:

- short actor lines;
- natural Hindi/Hinglish;
- no explanatory recap in dialogue scenes;
- allow interruptions;
- preserve emotional beat order;
- merge fragments when needed for TTS;
- textguard before generation.

### 4.4 Performance audio generator

Purpose: generate acted speech, not plain TTS.

Provider-agnostic design:

- can use Fish, Eleven, Azure, local model, S2S, or future expressive model;
- provider is a backend, not the architecture;
- generation request must include performance metadata:
  - intent
  - energy
  - pace
  - delivery note
  - emotional context
  - line relationship to previous/next line

Acceptance:

- generated clip must match role lane;
- no wrong gender/character voice;
- no stretched words;
- no flat narration;
- no huge silence tail;
- duration within scene budget.

### 4.5 Timing and interaction layer

Purpose: place speech like conversation.

Not just align each segment start/end. It must model:

- reaction delay;
- interruption;
- overlap;
- breath/pause;
- line continuation;
- who speaks before/after;
- whether mouth is visible.

Acceptance:

- no line starts before the character reacts unless intentionally overlapping;
- no line continues while lips clearly stopped unless justified;
- no visible speaking mouth with missing dub unless it is a skip-lipsync/no-dialogue region.

### 4.6 Scene mix layer

Purpose: blend dialogue into the scene.

Uses stems:

- dialogue;
- music/FX/room bed;
- source vocal leak if any;
- final generated speech.

Rules:

- preserve room and bed;
- avoid over-isolated dialogue;
- avoid original-language leak;
- use compression/ducking based on scene style;
- do not claim mix solves bad acting.

### 4.7 Lip-sync layer

Purpose: only modify visible speaking-face regions.

Rules:

- no-face/wide/back-shot frames remain original;
- close-up speaking frames can use LatentSync or equivalent;
- audio is always replaced with final approved mix after lip-sync;
- no embedded original audio in final mux.

### 4.8 Evaluation layer

Purpose: catch technical failures and guide iteration, not replace human taste.

Metrics:

- duration/stream contract;
- speech windows;
- timing drift;
- line density;
- silence while original speaks;
- role/voice consistency;
- mix loudness/forwardness;
- subtitle/line readability;
- human listening gate.

Rule:

```text
Metrics can reject. Metrics cannot approve final feel alone.
```

## 5. Phased build roadmap

### Phase 0 - freeze V11 findings

Deliverable:

- this V12 plan;
- V11 failure summary;
- list of artifacts to keep.

Acceptance:

- no more random provider/mix loops.

### Phase 1 - scene pack builder

Build a tool that creates a review pack for one scene:

- source clip;
- old V1 clip;
- contact sheet;
- source transcript excerpt;
- actor-lane draft;
- speech/shot timeline;
- current dialogue/mix artifacts.

Output root pattern:

```text
D:\CloneDub\work\v12_scene_packs\<video>_<start>_<end>\
```

Acceptance:

- human can understand the scene before any generation.

### Phase 2 - actor-lane system

Build actor-lane manifests across a 3-5 minute section.

Outputs:

- `actor_lanes.json`
- `lane_evidence.md`
- `needs_review.json`

Acceptance:

- no line generation without actor lane;
- at least role-stable lanes for all visible speakers in the test section.

### Phase 3 - performance script system

Build repeatable performance-script authoring.

Inputs:

- scene pack;
- source meaning;
- actor lanes;
- style rules.

Outputs:

- `performance_script.json`
- `performance_script.md`
- `script_quality_gate.md`

Acceptance:

- script sounds like scene dialogue when read aloud;
- no monolithic paragraph segments;
- human approves before generation.

### Phase 4 - generation backend abstraction

Build a provider adapter interface:

```text
generate_line(actor_lane, text, intent, energy, delivery, duration_hint, context) -> wav + metadata
```

Backends can include:

- Fish;
- Eleven;
- Azure;
- local model;
- future S2S model.

Acceptance:

- same script can run on multiple backends without rewriting pipeline;
- per-lane voice mapping enforced.

### Phase 5 - micro-scene generation loop

Generate only 30-90 second scenes.

Each run outputs:

- preview MP4;
- per-line WAVs;
- timing report;
- role/voice report;
- listening README.

Acceptance:

- human says the scene is closer to real dub than V11.

### Phase 6 - 3-minute section

Only after multiple micro-scenes pass.

Acceptance:

- consistent actor lanes;
- no role mismatch;
- audio feel acceptable without lip-sync;
- no original-language leak.

### Phase 7 - lip-sync integration

Only after audio is accepted.

Acceptance:

- visible speaking regions improve;
- wide/no-face shots untouched;
- final mux has one approved dubbed audio stream.

### Phase 8 - 15-minute section

Only after 3-minute section passes.

Acceptance:

- no manual crisis fixes;
- batch artifacts reproducible;
- human listening gate passes.

### Phase 9 - full episode

Only after 15-minute section passes.

Acceptance:

- full episode final output;
- QA report;
- human review notes;
- reproducible run manifest.

## 6. First implementation target

Do not start with another generator.

Start with Phase 1:

```text
Build v12_scene_pack_builder.py
```

Target scene:

```text
1500.25-1561.13 cake/phone confrontation
```

Why:

- already used in V11 Phase 6;
- dialogue-heavy;
- multiple actors;
- current script artifacts exist;
- failure mode is clearly visible.

Required outputs:

- source scene clip;
- V1 scene clip;
- contact sheet;
- actor lanes draft;
- performance script draft;
- current generation attempt;
- report summarizing why it failed.

## 7. Engineering rules

- Keep code under `D:\.Clone\tools`.
- Keep generated artifacts under `D:\CloneDub\work`.
- Never overwrite previous experiment folders.
- No paid API without explicit gate.
- No full video until a 60s scene passes.
- No Android/Kaggle mixing into V12 commits.
- Every tool must have deterministic CLI.
- Every output folder must contain a README/report.
- Every generation must preserve provider metadata and voice mapping.

## 8. Human gate questions

For every sample, ask only these:

```text
1. Does it feel like characters are speaking inside the scene?
2. Which part breaks the illusion first?
3. Is the issue voice, acting, line wording, timing, wrong character voice, or mix?
4. Is it better than previous baseline?
5. Should we iterate this scene or abandon this approach?
```

If the user cannot explain the difference, that is a valid result. The system must provide simpler A/B tests, not ask for technical audio vocabulary.

## 9. Success definition

V12 succeeds when:

- a 60s dialogue scene feels closer to real dub than V11;
- then a 3-minute section feels coherent;
- then a 15-minute section can be produced without role/mix/timing collapse.

Full episode is not the first milestone. A believable 60s scene is.

