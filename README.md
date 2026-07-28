# CloneCast (Android)

Android app for a K-drama recap YouTube workflow: clone your own voice, keep
genre-styled voice profiles, paste a recap script and generate narration MP3s
(Fish Audio API), plus a free audio-to-audio voice convert path (RVC on a
Kaggle T4 GPU) that keeps the original recording's exact timing.

## Features

- **Profiles / Record / Clone** — record voice samples per genre, clone via Fish Audio
- **Generate** — script → chunked TTS narration → merged MP3 export to `Music/CloneCast/`
- **Convert (RVC)** — record narration yourself, convert the *voice only* on a free
  Kaggle T4; same duration in = same duration out (see `PLAN-VOICE-CONVERT.md`)
- **Dub / Reels / Colab** — helper tabs for the video workflow

## Build

No Gradle wrapper checked in — use a local Gradle 8.9+ with JDK 17+:

```
gradle -p . assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

- minSdk 26, targetSdk 35, Kotlin + Jetpack Compose (Material 3)

## Kaggle-side setup for Convert

One-time manual steps (training + Gate 0 dry-run): see `kaggle/README.md`.
API contract and design: `PLAN-VOICE-CONVERT.md`.

## Keys

All keys (Fish Audio, Groq, Kaggle) are entered in the app's Settings screen and
stored on-device only (Kaggle key encrypted via Android Keystore). Nothing in
this repo contains credentials.
