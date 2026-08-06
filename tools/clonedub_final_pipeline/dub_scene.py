#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CloneDub scene orchestrator — runs the proven FINAL pipeline end-to-end.

Usage (WSL):
  python3 dub_scene.py --config scene.json            # run all remaining stages
  python3 dub_scene.py --config scene.json --status   # show stage status
  python3 dub_scene.py --config scene.json --from actors   # redo from a stage

Design: CLONEDUB_ORCHESTRATOR_DESIGN.md. Each stage runs in its own venv via
subprocess; a .done_<stage> marker in workdir marks completion; markers make
every run resumable. Translation stage is a GATE: it writes translation_todo.json
and exits until translations.json exists.
"""
import argparse, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
STAGES_DIR = os.path.join(HERE, "stages")

VENV = {
    "pyannote":  "/mnt/d/CloneDub/pyannote_venv/bin/python",
    "sonitr":    "/home/moin/SoniTranslate/.venv/bin/python",
    "indicf5":   "/mnt/d/CloneDub/indicf5_py310/bin/python",
    "chatterbox":"/mnt/d/CloneDub/chatterbox_v3_venv/bin/python",
    "seedvc":    "/mnt/d/CloneDub/seedvc_venv/bin/python",
    "system":    sys.executable,
}

# stage name -> (script, venv, expected outputs relative to workdir)
STAGES = [
    ("diarize",    "s01_diarize.py",   "pyannote",  ["diar/turns.json"]),
    ("asr_words",  "s02_asr_words.py", "sonitr",    ["asr_words.json"]),
    ("lines",      "s03_lines.py",     "sonitr",    ["wordlines.json"]),
    ("gender",     "s04_gender.py",    "indicf5",   ["gender.json"]),
    ("actors",     "s05_actors.py",    "chatterbox",["actors.json"]),
    ("translate",  "s06_translate_gate.py", "indicf5", ["lines_final.json"]),
    ("clean_gen",  "s07_clean_gen.py", "indicf5",   ["gen_clean/.written"]),
    ("clean_cer",  "s08_clean_cer.py", "sonitr",    ["clean_best.json"]),
    ("vc",         "s09_vc.py",        "seedvc",    ["gen_vc/.written"]),
    ("direct_gen", "s10_direct_gen.py","indicf5",   ["gen_direct/.written"]),
    ("judge_cer",  "s11a_cer.py",      "sonitr",    ["judge_cer.json"]),
    ("judge_pick", "s11b_pick.py",     "chatterbox",["picks.json"]),
    ("assemble",   "s12_assemble.py",  "indicf5",   ["scene.wav"]),
    ("audit",      "s13_audit.py",     "indicf5",   ["audit.json"]),
    ("mux",        None,               None,        []),  # handled inline
]
GATE_EXIT = 3   # translate gate uses this to pause the run


def preflight(cfg):
    st = os.statvfs(cfg["workdir"])
    free_gb = st.f_bavail * st.f_frsize / 1e9
    if free_gb < 10:
        sys.exit("ABORT: only %.1fG free on workdir disk (<10G). Clean up first." % free_gb)
    for k in ("video", "vocals", "no_vocals", "clean_refs"):
        if not os.path.exists(cfg[k]):
            sys.exit("ABORT: missing %s: %s" % (k, cfg[k]))
    for name, py in VENV.items():
        if name != "system" and not os.path.exists(py):
            sys.exit("ABORT: venv missing: %s" % py)
    # numpy guard on the two fragile venvs
    for v in ("indicf5", "seedvc"):
        out = subprocess.run([VENV[v], "-c", "import numpy;print(numpy.__version__)"],
                             capture_output=True, text=True).stdout.strip()
        if not out.startswith("1.26"):
            sys.exit("ABORT: %s venv numpy=%r (need 1.26.x — IndicF5 breaks on 2.x)" % (v, out))


def marker(cfg, stage):
    return os.path.join(cfg["workdir"], ".done_" + stage)


def stage_done(cfg, stage, outputs):
    if not os.path.exists(marker(cfg, stage)):
        return False
    return all(os.path.exists(os.path.join(cfg["workdir"], o)) for o in outputs)


def run_stage(cfg, cfg_path, name, script, venv, outputs):
    log = os.path.join(cfg["workdir"], "logs", name + ".log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    env = dict(os.environ, DUB_CONFIG=cfg_path)
    print("== stage %-11s (%s) -> %s" % (name, venv, log), flush=True)
    t0 = time.time()
    with open(log, "w") as lf:
        p = subprocess.run([VENV[venv], "-u", os.path.join(STAGES_DIR, script)],
                           env=env, stdout=lf, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    if p.returncode == GATE_EXIT:
        print(open(log).read()[-800:])
        sys.exit("PAUSED at gate '%s' (%.0fs). Fill the requested file and re-run." % (name, dt))
    if p.returncode != 0:
        print(open(log).read()[-1500:])
        sys.exit("STAGE FAILED: %s (exit %d, %.0fs) — log: %s" % (name, p.returncode, dt, log))
    missing = [o for o in outputs if not os.path.exists(os.path.join(cfg["workdir"], o))]
    if missing:
        sys.exit("STAGE %s exited 0 but outputs missing: %s" % (name, missing))
    open(marker(cfg, name), "w").write(str(time.time()))
    print("   done in %.0fs" % dt, flush=True)


def mux(cfg):
    wav = os.path.join(cfg["workdir"], "scene.wav")
    out = os.path.join(cfg["workdir"], cfg["out_name"] + ".mp4")
    dur = cfg["t1"] - cfg["t0"]
    cmd = ["ffmpeg", "-y", "-ss", str(cfg["t0"]), "-t", str(dur), "-i", cfg["video"],
           "-i", wav, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
           "-shortest", out]
    subprocess.run(cmd, check=True, capture_output=True)
    dst = "/mnt/d/CloneDub/" + cfg["out_name"] + ".mp4"
    shutil.copy(out, dst)
    open(marker(cfg, "mux"), "w").write(str(time.time()))
    print("MUXED -> %s" % dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--from", dest="from_stage")
    ap.add_argument("--until", dest="until_stage")
    a = ap.parse_args()
    cfg_path = os.path.abspath(a.config)
    cfg = json.load(open(cfg_path))
    os.makedirs(cfg["workdir"], exist_ok=True)

    if a.status:
        for name, _, _, outputs in STAGES:
            print("%-11s %s" % (name, "DONE" if stage_done(cfg, name, outputs) else "-"))
        return

    if a.from_stage:
        drop = False
        for name, _, _, _ in STAGES:
            if name == a.from_stage:
                drop = True
            if drop and os.path.exists(marker(cfg, name)):
                os.remove(marker(cfg, name))

    preflight(cfg)
    for name, script, venv, outputs in STAGES:
        if name == "mux":
            if not os.path.exists(marker(cfg, "mux")):
                mux(cfg)
            continue
        if stage_done(cfg, name, outputs):
            print("== stage %-11s SKIP (done)" % name)
            continue
        run_stage(cfg, cfg_path, name, script, venv, outputs)
        if a.until_stage == name:
            print("Stopped after %s (--until)." % name)
            return
    # final summary
    audit = json.load(open(os.path.join(cfg["workdir"], "audit.json")))
    print("\nAUDIT: %s" % audit.get("summary"))
    print("ALL DONE -> D:\\CloneDub\\%s.mp4" % cfg["out_name"])


if __name__ == "__main__":
    main()
