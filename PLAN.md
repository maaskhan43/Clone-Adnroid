# CloneCast — One-Shot Build Plan

> **Status (2026-07-14):** Phases 0–5 CODE COMPLETE and compiling. Debug APK at
> `app\build\outputs\apk\debug\app-debug.apk`. Waiting on: phone with USB debugging
> for install; Fish Audio API key + small credit for on-device testing of clone/generate.
> Gradle lives at `D:\gradle\gradle-8.9` (JAVA_HOME fixed to `C:\Program Files\Java\jdk-20`).
> Build command: `D:\gradle\gradle-8.9\bin\gradle.bat -p D:\.Clone assembleDebug`
> Remaining: on-device testing (Phases 2–5 verify), Phase 6 signed release APK, optional Phase 7.

**Goal:** An Android app (APK) that lets you clone your own voice from your phone, keep separate genre-styled voice profiles (Comedy / Horror / Drama / Romance / Action), paste a recap script, generate narration audio with your cloned voice, and export MP3s ready to drop into CapCut for your YouTube movie/K-drama explanation videos.

---

## 0. Current machine status (verified 2026-07-14)

| Tool | Status |
|---|---|
| Android SDK | ✅ `D:\Android\Sdk` — platforms android-34 & android-35, build-tools 34/35 |
| adb | ✅ On PATH (`D:\Android\Sdk\platform-tools`) |
| Java | ✅ JDK 20 (works with Gradle 8.5+ / AGP 8.x; if a build error mentions Java version, install Temurin JDK 17 as fallback) |
| Node.js | ✅ Installed (not needed for this build) |
| Flutter / Android Studio | ❌ Not installed — **not needed**, we build with Gradle CLI |

**Decision: Native Kotlin + Jetpack Compose, built via Gradle wrapper from the terminal.** Zero new heavy installs. APK gets installed to your phone over USB with `adb install`.

---

## 1. What the app does (scope)

### In scope (v1)
1. **Settings** — enter/save the TTS provider API key (stored on-device only).
2. **Voice Profiles** — create profiles by genre (Comedy, Horror, Drama, Romance, Action, Custom). Each profile = one recorded voice sample + one cloned voice ID.
3. **Record** — record a 1–3 min voice sample with the phone mic (pause/resume, playback, re-record).
4. **Clone** — upload the sample to the provider's API → get back a voice ID, saved to the profile.
5. **Generate** — paste a script, pick a profile, app splits the script into chunks at sentence boundaries, generates each chunk, shows progress, lets you re-generate any bad chunk.
6. **Export** — merge chunks into one MP3, save to `Music/CloneCast/`, plus Android share sheet (send straight to CapCut).

### Out of scope (v1) — do later if wanted
- Video editing inside the app (CapCut does this better)
- In-app script writing/AI assistance
- Self-hosted local TTS server option (Phase 7, optional)

---

## 2. TTS provider decision & cost reality

**Primary: Fish Audio API** (`api.fish.audio`) with a provider abstraction so ElevenLabs can be swapped in later.

⚠️ **Honest cost note:** Fish Audio's *website* has a free playground tier, but their *API* (which an app must use) is **pay-as-you-go** — roughly **$10–15 per 1 million characters** (verify current price at fish.audio/pricing during Phase 3). That means:
- A 2-hour video script (~110,000 chars) ≈ **$1–2** — vs ~$22/month on ElevenLabs
- A small one-time top-up (e.g. $5–10) lasts many videos
- ElevenLabs API needs Starter/Creator subscription — kept as a swap-in adapter, not the default

**Genre voices trick (core feature):** zero-shot cloning copies the *mood* of the sample. So each genre profile is created from a differently-acted recording of your voice — energetic sample → Comedy profile, low whisper → Horror profile, etc. Same person, five narration styles.

---

## 3. Architecture

```
d:\.Clone\
├── PLAN.md                  ← this file
├── app\                     ← Android app module
│   └── src\main\
│       ├── java\com\clonecast\app\
│       │   ├── MainActivity.kt
│       │   ├── ui\           (Compose screens + nav)
│       │   │   ├── ProfilesScreen.kt
│       │   │   ├── RecordScreen.kt
│       │   │   ├── GenerateScreen.kt
│       │   │   └── SettingsScreen.kt
│       │   ├── data\
│       │   │   ├── ProfileStore.kt      (DataStore JSON: profiles, voice IDs)
│       │   │   ├── SettingsStore.kt     (API key, provider choice)
│       │   │   └── AudioFiles.kt        (MediaStore save/merge helpers)
│       │   ├── audio\
│       │   │   ├── Recorder.kt          (MediaRecorder → .m4a; WAV fallback)
│       │   │   └── Mp3Merger.kt         (frame-level MP3 concat)
│       │   └── tts\
│       │       ├── TtsProvider.kt       (interface: cloneVoice(), generate())
│       │       ├── FishAudioProvider.kt
│       │       └── ElevenLabsProvider.kt (stub in v1, filled in later)
│       ├── res\ ...
│       └── AndroidManifest.xml
├── build.gradle.kts, settings.gradle.kts, gradle\wrapper\...
└── keystore\clonecast.jks   ← release signing key (generated once, KEEP SAFE)
```

**Key libraries:** Compose BOM, Navigation-Compose, OkHttp (multipart upload + streaming download), kotlinx-serialization, DataStore, Media3 ExoPlayer (playback). Min SDK 26, target SDK 35.

**API contracts** (verify against docs.fish.audio in Phase 3):
- Clone: `POST https://api.fish.audio/model` — multipart: `voices` (audio file), `title`, `type=tts`, `train_mode=fast`, header `Authorization: Bearer <key>` → returns model `_id` (the voice ID)
- Generate: `POST https://api.fish.audio/v1/tts` — JSON `{ "text": ..., "reference_id": <voice ID>, "format": "mp3" }` → MP3 bytes

---

## 4. Build phases (each ends with something you can run)

### Phase 0 — Project skeleton + first APK on your phone
- Scaffold Gradle project (wrapper, AGP 8.x, Kotlin 2.x, Compose)
- "Hello CloneCast" single screen
- `gradlew assembleDebug` → `adb install` to your phone over USB (enable **USB debugging** in Developer Options)
- ✅ *Done when: app icon opens on your phone*

### Phase 1 — Navigation + Settings
- Bottom nav: Profiles / Generate / Settings
- Settings: API key field (saved in DataStore), provider dropdown (Fish Audio / ElevenLabs), "Test connection" button hitting the provider's auth-check endpoint
- ✅ *Done when: key persists across app restarts and Test shows green*

### Phase 2 — Voice profiles + recorder
- Profile list: create profile → pick genre chip (🎭 Comedy / 👻 Horror / 💔 Drama / ❤️ Romance / 💥 Action / ⚙️ Custom)
- Record screen: mic permission, live timer, min-60s indicator, stop/playback/re-record, sample saved per profile
- Recording tips shown on screen ("quiet room, 30cm from mic, act the genre")
- ✅ *Done when: you can record + replay a 1-min sample inside a profile*

### Phase 3 — Cloning
- "Clone voice" button on a profile with a recorded sample → uploads to Fish Audio, saves returned voice ID, profile shows **CLONED** badge
- Error surfaces: bad key, no credit, file rejected (auto-retry once; if format rejected, fall back to WAV recording path)
- ✅ *Done when: profile shows a real voice ID and a test sentence plays back in your cloned voice*

### Phase 4 — Script → narration generation
- Generate screen: big script paste box, live character count + **estimated cost**, profile picker
- Chunker: split at sentence boundaries, ~1,500 chars/chunk
- Sequential generation queue with per-chunk status (⏳/✅/❌), tap ❌ to retry, tap ✅ to preview + regenerate if it sounds off
- Pronunciation fixes: simple find→replace list (e.g. `Ji-hoon → Jee-hoon`) applied before sending — fixes Korean name mangling
- ✅ *Done when: a 3-paragraph script becomes playable chunk audio*

### Phase 5 — Export
- "Merge & Export" → single MP3 into `Music/CloneCast/<title>.mp3` via MediaStore + share sheet button
- ✅ *Done when: exported file appears in your phone's Files app and imports into CapCut*

### Phase 6 — Release APK
- Generate signing keystore (once), configure `signingConfigs`, `gradlew assembleRelease`
- Final APK at `app/build/outputs/apk/release/` — installable/shareable, survives reinstalls
- ✅ *Done when: signed `CloneCast-v1.0.apk` runs on your phone without USB*

### Phase 7 (optional, later) — Free unlimited mode
- Tiny FastAPI server on your PC running F5-TTS/Chatterbox; app gets a "Self-hosted" provider pointing at your PC's LAN IP → $0 generation forever

---

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Fish Audio API pricing/endpoints changed | Phase 3 starts by checking live docs; provider interface makes swapping cheap |
| Java 20 vs Gradle friction | Use Gradle 8.7+; fallback = install Temurin JDK 17 |
| Long scripts fail mid-generation | Chunk queue is resumable; chunks cached on disk until exported |
| Korean names mispronounced | Pronunciation find→replace list (Phase 4) |
| MP3 concat glitches at seams | Frame-aligned merge; fallback = export chunks separately (CapCut handles multi-file fine) |
| Voice cloning misuse policy | Only your own voice — providers require consent confirmation; app shows a consent checkbox before upload |
| Phone not detected by adb | Enable Developer Options → USB debugging; `adb devices` must list it |

---

## 6. What YOU need to do (the human steps)

1. **Phone:** enable Developer Options (tap Build Number 7×) → turn on USB debugging → connect USB when we install
2. **Fish Audio account:** sign up at fish.audio → create an API key → top up a small credit (~$5) when we reach Phase 3
3. **Voice samples:** when Phase 2 lands, record 1–3 min per genre in a quiet room, acting the mood
4. **Say "start phase 0"** — each phase ends with an APK you can actually try

---

*Plan created 2026-07-14 · Machine: Windows 11, SDK @ D:\Android\Sdk, JDK 20 · Target: min SDK 26 (Android 8+), package `com.clonecast.app`*
