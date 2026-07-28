# CloneCast training kernel — one-time RVC voice-model training on Kaggle T4.
# Pushed by the app (RvcAssets.kt) as kernel clonecast-rvc-train.
# Input:  /kaggle/input/clonecast-voice-raw/  (user's clean voice audio)
# Output: /kaggle/working/model-dataset/      (model.pth, model.index, hubert_base/,
#         rmvpe.pt, config.json, train_result.json)
# The converter kernel mounts THIS kernel's output directly (kernelDataSources),
# so no manual dataset step is needed after training.
#
# All CLI argv/paths were verified against the pinned RVC commit's source.

import json
import os
import shutil
import subprocess
import sys
import time
import traceback

RVC_COMMIT = "__RVC_COMMIT__"
EXP_NAME = "clonecast"
EPOCHS = 300
SAVE_EVERY = 50
BATCH = 8

RVC = "/kaggle/working/rvc"
VOICE_DIR = "/kaggle/input/clonecast-voice-raw"
EXP_DIR = f"{RVC}/logs/{EXP_NAME}"
OUT = "/kaggle/working/model-dataset"
RVC_REPO = "https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI"

result = {"status": "failed", "rvc_commit": RVC_COMMIT, "epochs": EPOCHS}

# train/*.py import repo-root packages; `python train/x.py` puts train/ first on
# sys.path where train/train.py shadows the train package (circular import).
os.environ["PYTHONPATH"] = RVC
os.environ["PYTHONSAFEPATH"] = "1"


def log(msg):
    print("[clonecast-train] %s" % msg, flush=True)


def run(cmd, cwd=None):
    log("run: %s" % cmd)
    subprocess.run(cmd, shell=True, check=True, cwd=cwd)


def write_result():
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "train_result.json"), "w") as f:
        json.dump(result, f, indent=2)


def install():
    t0 = time.time()
    run("pip install -q torch==2.7.1 torchaudio==2.7.1 "
        "--index-url https://download.pytorch.org/whl/cu128")
    # Kaggle's preinstalled torchvision targets a newer torch; with 2.7.1 it
    # breaks transformers' import (torchvision::nms). RVC never uses it.
    run("pip uninstall -q -y torchvision")
    run(f"git clone {RVC_REPO} {RVC}")
    run(f"git -C {RVC} checkout {RVC_COMMIT}")
    req = open(f"{RVC}/requirments_cu128_py312.txt").read().splitlines()
    with open("/kaggle/working/req.txt", "w") as f:
        f.write("\n".join(l for l in req if not l.strip().startswith("--index-url")))
    with open("/kaggle/working/constraints.txt", "w") as f:
        f.write("numpy<2\ntorch==2.7.1\ntorchaudio==2.7.1\n")
    run("pip install -q -r /kaggle/working/req.txt -c /kaggle/working/constraints.txt")
    log("install done in %.0fs" % (time.time() - t0))


def assets():
    # Paths the pinned source hardcodes:
    #   infer/hubert.py             -> assets/hubert_base/ (transformers ContentVec)
    #   train/dataset/extract_f0.py -> assets/rmvpe/rmvpe.pt
    #   train defaults              -> assets/pretrained_v2/f0G40k.pth + f0D40k.pth
    #   train/process_ckpt.py       -> saves model into assets/weights/
    run("pip install -q huggingface_hub")
    from huggingface_hub import snapshot_download, hf_hub_download
    snapshot_download("lengyue233/content-vec-best", local_dir="/kaggle/working/hubert_base")
    os.makedirs(f"{RVC}/assets/rmvpe", exist_ok=True)
    os.makedirs(f"{RVC}/assets/pretrained_v2", exist_ok=True)
    os.makedirs(f"{RVC}/assets/weights", exist_ok=True)
    rmvpe = hf_hub_download("lj1995/VoiceConversionWebUI", "rmvpe.pt", local_dir="/kaggle/working")
    shutil.copy(rmvpe, f"{RVC}/assets/rmvpe/rmvpe.pt")
    for name in ("f0G40k.pth", "f0D40k.pth"):
        p = hf_hub_download("lj1995/VoiceConversionWebUI", f"pretrained_v2/{name}",
                            local_dir="/kaggle/working/pt")
        shutil.copy(p, f"{RVC}/assets/pretrained_v2/{name}")
    if not os.path.exists(f"{RVC}/assets/hubert_base"):
        os.symlink("/kaggle/working/hubert_base", f"{RVC}/assets/hubert_base")
    log("assets ready")


def train():
    os.makedirs(EXP_DIR, exist_ok=True)
    ncpu = os.cpu_count() or 4
    # argv per pinned source: inp_root sr n_p exp_dir noparallel per
    run(f"python train/preprocess.py {VOICE_DIR} 40000 {ncpu} {EXP_DIR} False 3.7", cwd=RVC)
    # cuda mode: cuda n_part i_part i_gpu exp_dir is_half
    run(f"python train/dataset/extract_f0.py cuda 1 0 0 {EXP_DIR} True", cwd=RVC)
    # device n_part i_part i_gpu exp_dir version is_half
    run(f"python train/dataset/extract_hubert_feature.py cuda 1 0 0 {EXP_DIR} v2 True", cwd=RVC)

    # filelist + config (replicates webui.py click_train; no mute assets in repo)
    import random
    gt, feat = f"{EXP_DIR}/0_gt_wavs", f"{EXP_DIR}/3_feature768"
    f0d, f0nsf = f"{EXP_DIR}/2a_f0", f"{EXP_DIR}/2b-f0nsf"
    names = (set(n.split(".")[0] for n in os.listdir(gt))
             & set(n.split(".")[0] for n in os.listdir(feat))
             & set(n.split(".")[0] for n in os.listdir(f0d))
             & set(n.split(".")[0] for n in os.listdir(f0nsf)))
    if not names:
        raise RuntimeError("No training samples survived preprocessing — check the voice audio")
    lines = [f"{gt}/{n}.wav|{feat}/{n}.npy|{f0d}/{n}.wav.npy|{f0nsf}/{n}.wav.npy|0" for n in names]
    random.shuffle(lines)
    with open(f"{EXP_DIR}/filelist.txt", "w") as f:
        f.write("\n".join(lines))
    result["train_segments"] = len(lines)
    log("filelist: %d segments" % len(lines))
    # repo quirk (webui.py): sr=40k uses configs/v1/40k.json even for v2 models
    cfg = json.load(open(f"{RVC}/configs/v1/40k.json"))
    with open(f"{EXP_DIR}/config.json", "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4, sort_keys=True)

    run(f"python train/train.py -e {EXP_NAME} -sr 40k -f0 1 -bs {BATCH} -g 0 "
        f"-te {EPOCHS} -se {SAVE_EVERY} -pg assets/pretrained_v2/f0G40k.pth "
        f"-pd assets/pretrained_v2/f0D40k.pth -l 1 -c 0 -sw 1 -v v2", cwd=RVC)
    run(f'python train/train_index.py {EXP_NAME} v2 "" {ncpu}', cwd=RVC)


def package():
    import glob
    os.makedirs(OUT, exist_ok=True)
    weights = sorted(glob.glob(f"{RVC}/assets/weights/{EXP_NAME}*.pth"))
    indexes = sorted(glob.glob(f"{EXP_DIR}/**/added_*.index", recursive=True))
    if not weights:
        raise RuntimeError("No trained .pth in assets/weights — training step failed")
    if not indexes:
        raise RuntimeError("No added_*.index — index step failed")
    shutil.copy(weights[-1], f"{OUT}/model.pth")
    shutil.copy(indexes[-1], f"{OUT}/model.index")
    shutil.copytree("/kaggle/working/hubert_base", f"{OUT}/hubert_base", dirs_exist_ok=True)
    shutil.copy("/kaggle/working/rmvpe.pt", f"{OUT}/rmvpe.pt")
    with open(f"{OUT}/config.json", "w") as f:
        json.dump({"exp": EXP_NAME, "sr": "40k", "version": "v2",
                   "epochs": EPOCHS, "rvc_commit": RVC_COMMIT}, f, indent=2)
    log("packaged: %s" % os.listdir(OUT))

    # Keep ONLY model-dataset as kernel output — the converter mounts this
    # kernel's output, so a lean output = faster converter startup.
    for entry in os.listdir("/kaggle/working"):
        if entry == "model-dataset":
            continue
        path = os.path.join("/kaggle/working", entry)
        try:
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        except Exception as cleanup_error:
            log("cleanup skipped %s: %s" % (entry, cleanup_error))


try:
    if RVC_COMMIT.startswith("__"):
        raise RuntimeError("RVC_COMMIT placeholder was not filled in")
    install()
    assets()
    train()
    package()
    result["status"] = "ok"
    log("TRAINING COMPLETE")
except Exception:
    result["error"] = traceback.format_exc()
    log("FAILED:\n%s" % result["error"])
    write_result()
    sys.exit(1)
write_result()
