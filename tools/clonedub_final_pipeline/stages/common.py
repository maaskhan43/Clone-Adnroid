# -*- coding: utf-8 -*-
"""Shared helpers for dub_scene stages. Config comes via env DUB_CONFIG."""
import json, os
import numpy as np
import soundfile as sf

CFG = json.load(open(os.environ["DUB_CONFIG"]))
WD = CFG["workdir"]


def wpath(*p):
    return os.path.join(WD, *p)


def read_slice(path, a0, a1, mono=True):
    info = sf.info(path)
    sr = info.samplerate
    x, _ = sf.read(path, start=int(a0 * sr), stop=int(a1 * sr))
    if mono and x.ndim > 1:
        x = x.mean(1)
    return x.astype(np.float32), sr


def to_sr(a, sr, target):
    if sr == target:
        return a
    n = int(len(a) * target / sr)
    return np.interp(np.linspace(0, len(a), n, endpoint=False),
                     np.arange(len(a)), a).astype(np.float32)


def snr_db(a, sr):
    x = to_sr(a, sr, 16000)
    fl = 1600
    fe = np.array([np.sqrt(np.mean(x[i:i+fl]**2)) for i in range(0, max(len(x)-fl, 1), fl)])
    if len(fe) < 3:
        return 0.0
    return float(20 * np.log10((np.percentile(fe, 90) + 1e-9) / (np.percentile(fe, 10) + 1e-9)))


def norm_deva(s):
    import re, unicodedata
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[^ऀ-ॿ ]", "", s)
    return re.sub(r"\s+", "", s)


def cer(ref, hyp):
    a, b = norm_deva(ref), norm_deva(hyp)
    if not a:
        return 0.0 if not b else 100.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca != cb)))
        prev = cur
    return 100.0 * prev[-1] / len(a)


def start_trim(a, sr):
    """Energy-based leading-garble trim (F5 onset artifact). Skip for <1.2s clips."""
    if len(a) < int(1.2 * sr):
        return a
    fl = int(0.03 * sr)
    thr = 0.10 * (np.max(np.abs(a)) + 1e-9)
    run = 0
    for i in range(0, min(len(a), int(0.6 * sr)), fl):
        if np.max(np.abs(a[i:i+fl])) > thr:
            run += 1
            if run >= 3:
                on = max(0, i - 2 * fl)
                return a[on:] if on < int(0.5 * sr) else a
        else:
            run = 0
    return a


def speedup(a, f):
    if f <= 1.001:
        return a
    n = int(len(a) / f)
    return np.interp(np.linspace(0, len(a), n, endpoint=False),
                     np.arange(len(a)), a).astype(np.float32)
