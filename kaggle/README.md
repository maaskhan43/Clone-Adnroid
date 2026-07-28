# CloneCast Kaggle-side setup (Phase 8.1 + Gate 0)

These are the two manual steps that must pass BEFORE trusting the in-app Convert
flow. Nothing here touches the CloneDub dubbing notebooks — everything is under
`clonecast-*` slugs only.

## Prerequisites (PC)

- Kaggle CLI 2.2.4+ (the pip 1.x CLI cannot select the T4):
  `uv tool install "git+https://github.com/Kaggle/kaggle-cli.git" --force`
- `kaggle.json` in `%USERPROFILE%\.kaggle\` (same account the app will use)

## Step 1 — Phase 8.1: one-time training (`clonecast-rvc-train`)

1. Upload 10+ minutes of clean voice audio (the app's Phase-2 genre recordings
   work) as a private dataset named `clonecast-voice-raw`:
   `kaggle datasets create -p <folder-with-audio>` (folder needs
   dataset-metadata.json with slug `clonecast-voice-raw`).
2. Open `clonecast-rvc-train.ipynb` on kaggle.com (create a new notebook, upload
   the file), attach the `clonecast-voice-raw` dataset, set Accelerator = GPU T4,
   Internet = ON, and Run All. (~1-2 hours.)
3. The notebook's last cell packages `/kaggle/working/model-dataset/` containing:
   `model.pth`, `model.index`, `config.json`, `hubert_base/`, `rmvpe.pt`.
4. Create the model dataset from that output:
   Notebook sidebar → Output → "New dataset", slug **clonecast-rvc-model**
   (private). Or download and `kaggle datasets create` locally.
5. Optional (enables account bootstrap later): download `model.pth` +
   `model.index` to the phone via the app (Phase 8.6) or keep a PC copy.

## Step 2 — Gate 0: converter dry-run (before trusting app code)

Use the EXACT script the app ships: `app/src/main/assets/rvc_convert_kernel.py`.

1. Make a working folder, e.g. `gate0/`:
   - Copy `rvc_convert_kernel.py` → `gate0/kernel.py`
   - Fill the placeholders (PowerShell):
     ```powershell
     $runId = "gate0test0001"
     $sha = (Get-FileHash -Algorithm SHA256 test30s.m4a).Hash.ToLower()
     (Get-Content gate0/kernel.py -Raw) `
       -replace '__RUN_ID__', $runId `
       -replace '__INPUT_SHA256__', $sha |
       Set-Content gate0/kernel.py -Encoding utf8
     ```
     Also replace `__RVC_COMMIT__` with the pin from `RvcAssets.RVC_COMMIT`
     (currently `4338f12c3c28c80b3ac015e2d0df66c41592746d`):
     ```powershell
     (Get-Content gate0/kernel.py -Raw) `
       -replace '__RVC_COMMIT__', '4338f12c3c28c80b3ac015e2d0df66c41592746d' |
       Set-Content gate0/kernel.py -Encoding utf8
     ```
2. Upload a 30-60s test clip + job.json as dataset `clonecast-input-audio`:
   `job.json` = `{"run_id":"gate0test0001","input_sha256":"<sha>","duration_ms":30000,"file_name":"test30s.m4a"}`
3. `gate0/kernel-metadata.json`:
   ```json
   {
     "id": "<username>/clonecast-rvc-convert",
     "title": "clonecast-rvc-convert",
     "code_file": "kernel.py",
     "language": "python",
     "kernel_type": "script",
     "is_private": true,
     "enable_internet": true,
     "dataset_sources": [
       "<username>/clonecast-rvc-model",
       "<username>/clonecast-input-audio"
     ]
   }
   ```
4. Push: `kaggle kernels push -p gate0 --accelerator NvidiaTeslaT4`
5. Watch: `kaggle kernels status <username>/clonecast-rvc-convert`
6. Pass criteria (run it TWICE):
   - `output.mp3` exists, duration within 1.0s of input
   - `job_result.json` has `"status": "ok"` and the matching run_id + sha
7. If the RVC API changed and the script needed edits: fix
   `app/src/main/assets/rvc_convert_kernel.py` (the same file), update
   `RvcAssets.RVC_COMMIT` if you moved the pin, and record the result in
   PLAN-VOICE-CONVERT.md section 6.

Only after Gate 0 passes twice should the in-app Convert button be trusted.
