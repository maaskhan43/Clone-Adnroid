# CloneCast - Phase 8: Direct Audio-to-Audio Voice Convert

> Status: PLAN ONLY. Nothing is built yet. Do not start until the user says
> "start Phase 8".
>
> Parent plan: [PLAN.md](PLAN.md), Phases 0-7.
>
> This is a separate feature plan for RVC-based voice conversion on Kaggle. It
> must not touch the existing CloneDub dubbing pipeline, WSL scripts, LatentSync
> notebooks, Fish TTS flow, or current app generation/export code except through
> clearly named new Phase 8 files.

## 1. Goal

Current text-to-speech generation can change timing: an 18-minute narration may
come back shorter because TTS reads at its own pace. Voice conversion is
speech-to-speech: it keeps the source recording's duration, pauses, delivery,
emotion, and timing, and changes only the voice/timbre.

Target user flow:

1. Record or pick narration audio in the Android app.
2. Tap Convert.
3. App uploads the audio to a dedicated Kaggle dataset.
4. App pushes/runs a dedicated private Kaggle T4 kernel.
5. Kernel runs RVC and writes `output.mp3`.
6. App downloads the MP3 and saves it to `Music/CloneCast/`.
7. User shares the same-duration converted audio to CapCut.

Cost target: Rs. 0 within the user's normal Kaggle GPU quota. This quota is
shared with other Kaggle jobs, so the UI must show queued/waiting states instead
of pretending conversion is instant.

## 2. Hard Guardrails

1. Do not touch CloneDub resources.
   The app must never list, open, modify, delete, or infer from the user's
   existing dubbing notebooks, datasets, WSL workdirs, or LatentSync outputs.

2. Namespace every Kaggle resource.
   The app only addresses exact `clonecast-*` slugs:
   - Dataset: `clonecast-rvc-model`
   - Dataset: `clonecast-input-audio`
   - Kernel: `clonecast-rvc-convert`
   - Optional training kernel: `clonecast-rvc-train`

3. Do not enumerate the Kaggle account.
   No broad "list my kernels/datasets" calls in app runtime. Use exact slugs and
   exact status endpoints only.

4. Single Kaggle account by default.
   Do not automate parallel multi-account runs. Credential switching is allowed
   only as a manual account-change/bootstrap path with an explicit warning that
   Kaggle quota abuse can risk account restrictions.

5. One active conversion per Kaggle account.
   Because `clonecast-input-audio` and `clonecast-rvc-convert` are fixed slugs,
   `ConvertManager` must enforce a single-flight lock. A second conversion may
   be queued locally, but it must not upload a new input dataset version or push
   the converter kernel until the current job reaches COMPLETE, ERROR, or
   CANCELED and output validation is done.

6. Existing app phases stay stable.
   Phase 8 may add screens, stores, managers, and assets. It must not rewrite
   Fish Audio TTS, profiles, recorder internals, or export behavior unless a
   small adapter is required and tested.

## 3. App-Side Additions

New files should live under:

```text
app/src/main/java/com/clonecast/app/
  ui/ConvertScreen.kt
  data/KaggleStore.kt
  convert/KaggleClient.kt
  convert/ConvertManager.kt
  convert/RvcAssets.kt
```

Responsibilities:

- `ConvertScreen.kt`: new Convert tab; pick/record input, Convert button,
  progress, cancel, retry, job history, duration in/out.
- `KaggleStore.kt`: DataStore for Kaggle username, API key, bootstrap state,
  local model file paths, and job records.
- `KaggleClient.kt`: OkHttp wrapper for the exact Kaggle HTTP calls in Section 5.
- `ConvertManager.kt`: resumable state machine:
  `UPLOAD_BLOB -> VERSION_DATASET -> WAIT_DATASET_READY -> PUSH_KERNEL ->
  POLL_KERNEL -> DOWNLOAD_OUTPUT -> SAVE_MEDIASTORE`.
- `RvcAssets.kt`: bundled converter script text and kernel JSON builder.

Reuse existing app pieces where possible:

- Recorder/picker for input audio.
- MediaStore export helper for final MP3.
- Existing Settings screen style for credential fields.
- Existing share-sheet flow.

Credential storage requirement:

- Do not store the Kaggle API key as plain text. Note: the AndroidX
  `security-crypto` library (EncryptedSharedPreferences) is deprecated by Google;
  do not add it as a new dependency. Instead encrypt the key with an Android
  Keystore-backed AES key (Keystore alias + AES/GCM, ~30 lines, no new library)
  and keep the ciphertext in DataStore. The same pattern can later cover the Fish
  Audio key too. App-private storage is already sandboxed; this is
  defense-in-depth, required before the release build (Phase 6-equivalent).

## 4. Kaggle Resources

| Resource | Type | Contents |
|---|---|---|
| `clonecast-rvc-model` | Private dataset | `model.pth`, `model.index`, `config.json`, `hubert_base/`, `rmvpe.pt`, optional offline wheels |
| `clonecast-input-audio` | Private dataset | one current `input.m4a` or `input.wav`, replaced by new dataset versions |
| `clonecast-rvc-convert` | Private GPU kernel/script | RVC converter; inputs are the two datasets above; output is `/kaggle/working/output.mp3` |
| `clonecast-rvc-train` | Optional private GPU kernel/notebook | one-time RVC training workflow |

Dataset overwrite rule:

- Do not assume old input-audio dataset versions are deleted instantly. The app
  must bind every job to a unique `run_id`, include it in version notes, and
  make the converter script verify the input filename/hash from `job.json`
  before conversion.

## 5. Kaggle API Contract

Verified locally against Kaggle CLI 2.2.4's installed `kagglesdk` on
2026-07-28. Re-verify in Phase 8.1b before writing Android code because Kaggle's
private API can drift.

Base URL:

```text
https://www.kaggle.com/api/v1
```

Auth:

```text
HTTP Basic: username:apiKey
```

JSON field names are camelCase.

### 5.1 Test Connection and Quota

```http
GET /kernels/quota
```

Use this for the Settings "Test" button and quota indicator.

Success response includes:

```json
{
  "gpuQuota": {
    "timeUsed": "...",
    "timeReserved": "...",
    "totalTimeAllowed": "..."
  },
  "quotaRefreshTime": "..."
}
```

Handle:

- `200`: credentials accepted.
- `401` or `403`: bad/expired credentials or permission issue.
- Other 5xx/network: retry with backoff and show "Kaggle unavailable".

### 5.2 Blob Upload

Kaggle dataset files use a 3-step blob flow:

```http
POST /blobs/upload
Content-Type: application/json

{
  "type": "DATASET",
  "name": "input.m4a",
  "contentType": "audio/mp4",
  "contentLength": 123456,
  "lastModifiedEpochSeconds": 1780000000
}
```

Response:

```json
{
  "token": "...",
  "createUrl": "https://storage.googleapis.com/..."
}
```

Then:

```http
PUT <createUrl>
<raw bytes>
```

Finally, use the returned token in dataset create/version calls.

Implementation notes:

- For mobile reliability, implement retry. On interrupted Google Storage upload,
  either resume with `Content-Range` if the response supports it, or restart the
  blob flow. Do not mark upload complete until the dataset version reaches
  `READY`.
- Include `job.json` beside the audio with `run_id`, input SHA-256, duration,
  sample rate if known, and original filename.

### 5.3 Create Dataset

First-time create:

```http
POST /datasets/create/new
Content-Type: application/json

{
  "title": "CloneCast RVC Model",
  "slug": "clonecast-rvc-model",
  "ownerSlug": "<username>",
  "licenseName": "other",
  "isPrivate": true,
  "files": [{ "token": "<blob token>" }]
}
```

Use `licenseName: "other"`. Official CLI docs `datasets_metadata.md` list both
`other` and `unknown` as valid literals; either works. `other` is kept because
it is explicit for private generated assets. Confirmed 2026-07-28 from
kaggle-cli docs.

### 5.4 Create Dataset Version

Every conversion creates a new version of `clonecast-input-audio`:

```http
POST /datasets/create/version/<username>/clonecast-input-audio
Content-Type: application/json

{
  "versionNotes": "run <run_id>",
  "deleteOldVersions": true,
  "files": [
    { "token": "<audio blob token>" },
    { "token": "<job json blob token>" }
  ]
}
```

### 5.5 Dataset Status

```http
GET /datasets/status/<username>/clonecast-input-audio
```

SDK enum values:

```text
NOT_YET_PERSISTED
BLOBS_RECEIVED
BLOBS_DECOMPRESSED
BLOBS_COPIED_TO_SDS
INDIVIDUAL_BLOBS_COMPRESSED
READY
FAILED
DELETED
REPROCESSING
```

Normalize case when parsing JSON, but the app's success condition is `READY`.
Any `FAILED`, `DELETED`, auth failure, or timeout is a user-visible failure.

### 5.6 Push and Run Converter Kernel

```http
POST /kernels/push
Content-Type: application/json

{
  "slug": "<username>/clonecast-rvc-convert",
  "newTitle": "clonecast-rvc-convert",
  "text": "<full Python script from RvcAssets>",
  "language": "python",
  "kernelType": "script",
  "isPrivate": true,
  "enableInternet": true,
  "machineShape": "NvidiaTeslaT4",
  "datasetDataSources": [
    "<username>/clonecast-rvc-model",
    "<username>/clonecast-input-audio"
  ]
}
```

Important:

- `machineShape` is the verified field name.
- Use `NvidiaTeslaT4`.
- Do not also send deprecated `enableGpu`/`enableTpu`.
- Include a content hash of the script in app logs so a failed job can be traced.

### 5.7 Poll Kernel Status

```http
GET /kernels/status?userName=<username>&kernelSlug=clonecast-rvc-convert
```

SDK enum values:

```text
QUEUED
RUNNING
COMPLETE
ERROR
CANCEL_REQUESTED
CANCEL_ACKNOWLEDGED
NEW_SCRIPT
```

Handle:

- `QUEUED` / `NEW_SCRIPT`: show waiting for Kaggle GPU/startup.
- `RUNNING`: show converting.
- `COMPLETE`: download output.
- `ERROR`: show `failureMessage` and keep job retryable.
- `CANCEL_REQUESTED` / `CANCEL_ACKNOWLEDGED`: show canceled.

### 5.8 Download Output

List output:

```http
GET /kernels/output?userName=<username>&kernelSlug=clonecast-rvc-convert
```

Expected response includes:

```json
{
  "files": [{ "fileName": "output.mp3", "url": "<signed download url>" }],
  "log": "...",
  "nextPageToken": "..."
}
```

The app downloads the signed URL and saves to:

```text
Music/CloneCast/<title>.mp3
```

Fallback direct endpoint:

```http
GET /kernels/output/download/<username>/clonecast-rvc-convert/output.mp3
```

Validation before saving:

- File exists and is non-empty.
- Duration differs from input by no more than 1.0 second.
- `job_result.json` from the kernel matches the `run_id` and input SHA-256.
- If validation fails, do not save as a completed conversion.

## 6. Converter Kernel Script

The converter script is bundled in `RvcAssets.kt` and pushed as a Kaggle script
kernel. Before app implementation, it must be proven manually in Phase 8.1b with
the same script text.

Dependency strategy:

- Pin the RVC repository to a specific commit hash after manual dry-run.
- Do not use floating `main` in shipped app code.
- Install into Kaggle's default Python only after the dry-run proves the stack.
- Do not copy CloneDub/LatentSync pins into this kernel.

Planned RVC stack, to be confirmed in 8.1b:

| Component | Planned pin |
|---|---|
| Python | Kaggle default Python 3.12 unless RVC dry-run proves a 3.11 venv is needed |
| NumPy | `>=1.26.4,<2` |
| Torch | `2.7.1+cu128`, from `https://download.pytorch.org/whl/cu128`, if compatible at dry-run time |
| Transformers | RVC requirement-compatible, expected `>=4.49,<4.50` |
| RVC repo | TODO: exact commit hash after 8.1b |

Runtime model assets required in `clonecast-rvc-model`:

- `hubert_base/`
- `rmvpe.pt`
- `model.pth`
- `model.index`
- `config.json`
- optional offline wheelhouse after 8.5

Script steps:

1. Validate Kaggle inputs and read `job.json`.
2. Clone RVC at the pinned commit.
3. Install pinned dependencies.
4. Place or symlink model assets into RVC's expected paths.
5. Convert input audio to 16-bit WAV with ffmpeg.
6. For long audio, split on silence and process chunks to avoid VRAM spikes.
7. Run RVC inference using the tuned f0 method and index rate.
8. Reconstruct on the original timeline, not plain concat: each converted speech
   chunk is placed back at its original sample offset, verified silence gaps are
   padded with silence, and overlaps/gaps are logged. This preserves long pauses
   and keeps the output duration locked to the input.
9. Encode `/kaggle/working/output.mp3` at 44.1 kHz, 192 kbps.
10. Write `/kaggle/working/job_result.json` with run_id, input hash, output hash,
    input duration, output duration, RVC commit, dependency pins, and any warnings.

Expected wall time target:

- First version with online installs: roughly 12-25 minutes for an 18-minute file.
- Offline wheelhouse target: reduce startup materially in Phase 8.5.

## 7. One-Time RVC Training

Recommended first path: manual PC/Kaggle training, not app-triggered.

1. Prepare `clonecast-rvc-train` notebook.
2. Use about 10 minutes of clean target voice audio.
3. Train RVC v2 model on T4.
4. Save `model.pth`, `model.index`, `config.json`, `hubert_base/`, and `rmvpe.pt`.
5. Create `clonecast-rvc-model` private dataset.
6. Download model files to app-private phone storage for backup/bootstrap.

Only after manual training is stable should Phase 8.7 consider app-triggered
training.

## 8. Account Switch and Bootstrap

Default: one Kaggle account.

If the user enters different credentials:

1. Show a clear warning that automated multi-account quota farming is not
   supported.
2. Test `GET /kernels/quota`.
3. Check exact `clonecast-rvc-model` dataset status.
4. If missing and phone model backup exists, upload model files and create the
   dataset on the new account.
5. Push `clonecast-rvc-convert` under the new username.
6. Mark that account bootstrapped in `KaggleStore`.
7. If the phone model backup is missing and old account is inaccessible, show
   "re-training required".

Never run two accounts in parallel.

## 9. Build Phases

Each phase must end runnable and testable.

### Gate 0 / 8.1b - Converter Dry-Run Before App Code

This is the first implementation step. Do it before any Android app code.

Prerequisite: the converter needs `clonecast-rvc-model` to exist, which is
produced by 8.1 training. So the real order is: 8.1 (manual training, also
zero app code) -> Gate 0 dry-run -> app phases 8.0+. Alternatively, run Gate 0
first with any publicly available pretrained RVC voice model to validate the
environment/deps, then redo one confirmation run after 8.1 with the real model.

- Push the exact converter script from PC using Kaggle CLI 2.2.4.
- Use a 30-60 second input.
- Fix RVC dependency, commit, ffmpeg, asset path, and Kaggle API issues here.
- Record the working RVC commit hash and exact pip pins in this plan.

Done when:

- Two consecutive test runs produce valid `output.mp3`.
- Duration delta is <= 1.0 second.
- `job_result.json` matches the input hash and run_id.

### 8.0 - Kaggle Credentials in Settings

- Add username/API key fields or paste-`kaggle.json` parser.
- Save with encrypted storage.
- Test using `GET /kernels/quota`.

Done when:

- Real credentials show green.
- Wrong credentials show red.
- Key is not stored in plain text.

### 8.1 - Manual Training and Model Dataset

- Author or prepare `clonecast-rvc-train`.
- User runs it once.
- `clonecast-rvc-model` dataset exists with all required assets.
- Phone has a private backup copy.

Done when:

- Dataset status is `READY`.
- `filesDir/rvc/` has the model backup.

### 8.2 - KaggleClient Upload Path

- Implement blob upload, dataset create/version, and status polling.
- Add retry/backoff and resumable job state.
- Enforce the single-flight account lock before uploading or versioning
  `clonecast-input-audio`.

Done when:

- A phone-recorded `.m4a` appears in `clonecast-input-audio`.
- Dataset reaches `READY`.
- Failed upload resumes or fails cleanly without corrupting job state.

### 8.3 - KaggleClient Run Path

- Implement kernel push, status poll, output listing, download, and validation.

Done when:

- Debug button converts a 1-minute clip end-to-end.
- MP3 lands in `Music/CloneCast/`.
- Duration and run_id validation pass.

### 8.4 - Convert Screen and Manager

- New Convert tab.
- Pick/record audio.
- Convert button.
- Stage indicator: Uploading, Waiting, Converting, Downloading, Saving.
- Cancel/retry.
- Persistent job history.
- Duration in/out display.
- Quota/queued message when Kaggle is busy.
- Local queue for additional conversions while one Kaggle job is active.

Done when:

- A full 18-minute narration converts with screen off/on.
- Output duration equals input within 1.0 second.
- App kill/network drop resumes from the correct stage.
- Starting a second conversion while one is active queues it and does not
  overwrite the active input dataset/kernel run.

### 8.5 - Startup Speed and Polish

- Add optional offline wheelhouse to `clonecast-rvc-model`.
- Reuse share sheet.
- Remove any TTS wording/coupling from Convert path.

Done when:

- Typical warm run target is <= 12 minutes after offline wheels are in use.

### 8.6 - Account Bootstrap

- Fresh account detection.
- Auto-upload model backup.
- Push converter kernel.
- Run a test conversion.

Done when:

- A second test account can convert without retraining.
- The app never runs two accounts in parallel.

### 8.7 - Optional In-App Training

- Only build this after manual training and conversion are stable.

## 10. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Kaggle API drift | Re-run Phase 8.1b API dry-run before Android code; isolate HTTP wrapper behind `KaggleClient`. |
| Wrong GPU | Use `machineShape: "NvidiaTeslaT4"` and surface quota/status in UI. |
| RVC repo changes | Pin exact commit; never ship floating `main`. |
| NumPy/Torch mismatch | Keep RVC kernel independent; do not copy CloneDub pins. |
| Missing HuBERT/RMVPE assets | Store all required assets in `clonecast-rvc-model`; no surprise downloads. |
| Mobile upload failure | Upload with retry and job state; verify dataset `READY`. |
| Wrong input converted | Bind `job.json` run_id and SHA-256 through dataset, kernel, and output validation. |
| Concurrent conversion overwrite | Enforce one active Kaggle conversion per account; queue extra jobs locally. |
| Kernel queued for long time | Show queued/waiting UI and allow cancel. |
| Quota shared with dubbing | Show quota indicator; do not start hidden jobs. |
| Credential exposure | Encrypted local storage; never log API key; redact crash logs. |
| RVC quality poor | Tune f0 method/index rate on dry-runs; add input recording tips. |
| Duration drift | Reconstruct chunks on the original timeline and validate final duration before saving. |

## 11. Cost Summary

- Kaggle GPU: Rs. 0 inside available quota.
- Extra APIs: none for conversion.
- Phone storage: roughly 100-300 MB, depending on model assets and optional wheels.
- Fish Audio TTS remains the script-based narration path.
- Convert path is for performance-based, duration-locked narration.

## 12. Start Condition

Do not implement until the user says:

```text
start Phase 8
```

Before Android implementation, first task is Gate 0 / Phase 8.1b: manually prove
one RVC converter script on Kaggle and fill in the exact commit/pins in Section 6.
