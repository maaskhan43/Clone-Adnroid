# CloneDub V12 Phase 1 - XTTS Original-Video Voice Scene Success

Status: active first milestone.

This replaces all broader V12 execution for now. Do not continue random provider
tests, long video generation, lip-sync, Kaggle runs, Android work, or full-system
rewrites until this one scene passes.

## Goal

Make one short scene sound acceptably close to a real dub using XTTS and voice
references extracted from the original video itself.

Target scene:

```text
1500.25-1561.13
cake/phone confrontation
```

Success means the user listens and says the scene is meaningfully better than
the previous outputs. It does not need to be final full-episode quality.

## Non-goals

- No Fish samples.
- No ElevenLabs.
- No Azure.
- No Groq rewrite unless explicitly approved later.
- No Rask scraping/copying.
- No LatentSync.
- No full video.
- No Android/CloneCast changes.
- No Kaggle.

## Current evidence

Existing quick tests:

```text
D:\CloneDub\work\v12_xtts_original_voice_1500_1561\
D:\CloneDub\work\v12_xtts_original_voice_1500_1561_hi\
```

The first test used Roman Hinglish with `language=en`; it is not the preferred
XTTS setup.

The second test used Devanagari Hindi/Hinglish with `language=hi`; it is closer
to the correct setup but still not a rigorous XTTS bakeoff.

Official/local XTTS facts checked:

- XTTS-v2 supports Hindi language code `hi`.
- Output sample rate is 24 kHz.
- The local config includes:
  - `temperature: 0.75`
  - `length_penalty: 1.0`
  - `repetition_penalty: 5.0`
  - `top_k: 50`
  - `top_p: 0.85`
  - `gpt_cond_len: 30`
  - `gpt_cond_chunk_len: 4`
  - `max_ref_len: 30`
- Better control should use lower-level XTTS inference with cached speaker
  latents instead of blindly calling `tts_to_file()` for each line.

## Phase 1 implementation target

Build a focused XTTS bakeoff tool:

```text
tools/v12_xtts_original_voice_bakeoff.py
```

Input artifacts:

```text
D:\CloneDub\work\v11_phase6a_performance_plan_1500_1561\performance_script.json
D:\CloneDub\work\v11_phase6b_gen_test_1500_1561\bed.wav
D:\CloneDub\work\video1_meteor_video_clone\ref_SPEAKER_14_0.wav
D:\CloneDub\work\video1_meteor_video_clone\ref_SPEAKER_14_1.wav
D:\CloneDub\work\video1_meteor_video_clone\ref_SPEAKER_14_2.wav
```

Output folder:

```text
D:\CloneDub\work\v12_phase1_xtts_original_voice_bakeoff_1500_1561\
```

## Required variants

Generate controlled variants for the same scene:

```text
A_default_hi
B_low_random_no_stretch
C_faster_tight_dialogue
D_single_ref_vs_multi_ref
```

All variants must:

- use `language=hi`;
- use Devanagari text from `performance_script.json`;
- use only original-video reference audio;
- produce both dialogue-only and scene-mix WAV;
- write per-line WAVs;
- write per-line metadata;
- preserve exact scene duration `60.88s`;
- avoid clipping;
- record all XTTS parameters used.

## Required quality controls

For each generated line:

- record target window duration;
- record generated duration;
- record duration ratio;
- flag if generated duration is too long or too short;
- flag suspected repeated/stretched outputs by duration ratio and RMS activity;
- do not silently time-stretch in this phase.

The user needs honest samples, not hidden correction.

## Required reports

Output:

```text
README_LISTEN_FIRST.md
xtts_bakeoff_report.json
variant_A_default_hi_scene_mix.wav
variant_B_low_random_no_stretch_scene_mix.wav
variant_C_faster_tight_dialogue_scene_mix.wav
variant_D_single_ref_vs_multi_ref_scene_mix.wav
```

Also include dialogue-only WAVs and `line_wavs/<variant>/`.

`README_LISTEN_FIRST.md` must tell the user exactly which files to listen to
and what to judge:

1. Does the voice feel attached to the scene?
2. Are words understandable?
3. Are words stretched or repeated?
4. Is Hindi/Hinglish natural?
5. Which variant is least bad / best?

## Gate

Stop after creating the bakeoff and copying it to the connected Android device.

Do not start Phase 2 until the user chooses the best XTTS variant or rejects
XTTS entirely.
