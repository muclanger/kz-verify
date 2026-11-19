"""Free, open verifier for the AI labelling of Tom Langer's local AI pipeline
(EU AI Act Art. 50(2)). Reads both marking layers and reports in plain terms.

Layer 1 - invisible watermark
  pictures: Adobe TrustMark, variant P, ECC schema 0 (BCH_SUPER, 40 bit).
            TrustMark reads the ECC schema from bits in the picture; random
            content often decodes as schema 2/3, so ONLY schema 0 counts.
            If nothing is found, one more try after trimming a flat border
            (a card shared on a story background).
  audio:    Meta AudioSeal 0.2.1, 16-bit model, decided per 16 kHz frame;
            "marked" when >= 50 % of frames score > 0.5 (whole file or best
            4-s window). Detector runs on 2-s chunks (CPU run time).
Layer 2 - signed C2PA manifest (needs c2patool on PATH or --c2patool)
  signer certificate issued by "Tom Langer kz Root CA" (not on the C2PA trust
  list, so stock tools show "issuer not recognized"); this package ships the
  root certificate and checks the chain against it.

The payload of both watermarks is a random id without personal data.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from importlib.resources import files
from math import gcd
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("NO_TORCH_COMPILE", "1")   # AudioSeal 0.2.1 would otherwise need a C++ compiler on Windows

import numpy as np  # noqa: E402

IMAGE = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO = {".wav", ".flac", ".mp3", ".m4a"}
IPTC = "http://cv.iptc.org/newscodes/digitalsourcetype/"
AI_SOURCE_TYPES = {"trainedAlgorithmicMedia", "compositeSynthetic", "compositeWithTrainedAlgorithmicMedia"}
OWN_ASSERTION = "de.tom-langer.kz"
TRUSTMARK_VARIANT = "P"
TRUSTMARK_SCHEMA = 0          # BCH_SUPER
AUDIO_THRESHOLD = 0.5
AUDIO_SR = 16000
CHUNK_S, WINDOW_S = 2.0, 4.0


# ------------------------------------------------------------------ pictures

@lru_cache(maxsize=1)
def _trustmark():
    from trustmark import TrustMark
    return TrustMark(verbose=False, model_type=TRUSTMARK_VARIANT, encoding_type=TrustMark.Encoding.BCH_SUPER,
                     loadRemover=False, device="cpu")


def _trim(img):
    from PIL import Image, ImageChops
    bg = Image.new("RGB", img.size, img.getpixel((0, 0)))
    box = ImageChops.difference(img, bg).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
    if not box:
        return None
    w, h = box[2] - box[0], box[3] - box[1]
    if w * h > 0.9 * img.width * img.height or min(w, h) < 128:
        return None
    return img.crop(box)


def image_watermark(path: Path) -> dict:
    from PIL import Image
    rgb = Image.open(path).convert("RGB")
    for candidate in (rgb, _trim(rgb)):
        if candidate is None:
            continue
        bits, detected, schema = _trustmark().decode(candidate, MODE="binary")
        if detected and schema == TRUSTMARK_SCHEMA:
            return {"method": "TrustMark P (schema 0)", "detected": True, "bits": bits,
                    "id": format(int(bits, 2), f"0{(len(bits) + 3) // 4}x")}
    return {"method": "TrustMark P (schema 0)", "detected": False}


# ------------------------------------------------------------------ audio

def _resample(x: np.ndarray, a: int, b: int) -> np.ndarray:
    if a == b:
        return x.astype(np.float32, copy=False)
    from scipy.signal import resample_poly
    g = gcd(a, b)
    return resample_poly(x, b // g, a // g).astype(np.float32)


def _read_audio(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf
    if path.suffix.lower() in {".wav", ".flac"}:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return data.mean(axis=1), sr
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is needed to read mp3/m4a")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "x.wav"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vn",
                        "-c:a", "pcm_f32le", str(wav)], check=True)
        data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    return data.mean(axis=1), sr


@lru_cache(maxsize=1)
def _audioseal():
    from audioseal import AudioSeal
    return AudioSeal.load_detector("audioseal_detector_16bits").eval()


def audio_watermark(path: Path) -> dict:
    import torch
    mono, sr = _read_audio(path)
    x = _resample(mono, sr, AUDIO_SR)
    n = int(CHUNK_S * AUDIO_SR)
    starts = list(range(0, max(len(x), 1), n))
    if len(starts) > 1 and len(x) - starts[-1] < n // 4:
        starts.pop()
    parts = []
    for i, s in enumerate(starts):
        seg = x[s:(starts[i + 1] if i + 1 < len(starts) else len(x))]
        if len(seg) < AUDIO_SR // 10:
            continue
        with torch.no_grad():
            res, msg = _audioseal()(torch.from_numpy(np.ascontiguousarray(seg))[None, None, :], AUDIO_SR)
        parts.append((res[0, 1].numpy(), msg[0].numpy()))
    if not parts:
        return {"method": "AudioSeal 16 bit", "detected": False, "probability": 0.0}

    def combine(ps):
        frames = np.concatenate([f for f, _ in ps])
        m = np.average(np.stack([q for _, q in ps]), axis=0, weights=[len(f) for f, _ in ps])
        return float(np.mean(frames > 0.5)), "".join("1" if v > 0.5 else "0" for v in m)

    best, bits = combine(parts)
    k = int(WINDOW_S / CHUNK_S)
    if len(parts) > 2 * k:
        for i in range(len(parts) - k + 1):
            p, b = combine(parts[i:i + k])
            if p > best:
                best, bits = p, b
    hit = best >= AUDIO_THRESHOLD
    out = {"method": "AudioSeal 16 bit", "detected": hit, "probability": round(best, 4)}
    if hit:
        out["bits"] = bits
    return out


# ------------------------------------------------------------------ C2PA

def _c2patool(explicit: str | None) -> str | None:
    return explicit or shutil.which("c2patool")


def _report(tool: str, path: Path, anchored: bool) -> dict | None:
    args = [tool, str(path.resolve())]
    cwd = None
    if anchored:   # c2patool reads absolute Windows paths here as URLs, so pass them relative
        anchors = files("kz_verify").joinpath("anchors")
        cwd = str(anchors)
        args += ["trust", "--trust_anchors", "tom-langer-kz-root.pem", "--trust_config", "eku.cfg"]
    r = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", cwd=cwd)
    return json.loads(r.stdout) if r.returncode == 0 else None


def c2pa(path: Path, tool: str | None = None) -> dict:
    tool = _c2patool(tool)
    if not tool:
        return {"checked": False, "note": "c2patool not found - install it to check layer 2"}
    third = _report(tool, path, anchored=False)
    if third is None:
        return {"checked": True, "manifest": False}
    own = _report(tool, path, anchored=True) or {}
    m = third["manifests"][third["active_manifest"]]
    source, kz = None, {}
    for a in m.get("assertions", []):
        if a.get("label", "").startswith("c2pa.actions"):
            for act in a.get("data", {}).get("actions", []):
                if act.get("action") == "c2pa.created" and act.get("digitalSourceType"):
                    source = act["digitalSourceType"].removeprefix(IPTC)
        if a.get("label") == OWN_ASSERTION:
            kz = a.get("data", {}) or {}
    fails = [x["code"] for x in (third.get("validation_results") or {}).get("activeManifest", {}).get("failure", [])
             if x["code"] != "signingCredential.untrusted"]
    sig = m.get("signature_info") or {}
    return {"checked": True, "manifest": True, "state": third.get("validation_state"), "failures": fails,
            "issued_by_tom_langer_kz": own.get("validation_state") == "Trusted",
            "issuer": sig.get("issuer"), "signed_at": sig.get("time"),
            "digital_source_type": source, "kz_id": kz.get("kz_id"), "declared_watermark": kz.get("watermark")}


# ------------------------------------------------------------------ verdict

def verify(path: Path, c2patool: str | None = None) -> dict:
    path = Path(path)
    sfx = path.suffix.lower()
    if sfx in IMAGE:
        wm = image_watermark(path)
    elif sfx in AUDIO:
        wm = audio_watermark(path)
    else:
        wm = {"detected": False, "note": "no watermark check for this file type yet"}
    layer2 = c2pa(path, c2patool)
    manifest_ai = bool(layer2.get("manifest") and layer2.get("digital_source_type") in AI_SOURCE_TYPES
                       and not layer2.get("failures"))
    return {"file": path.name, "ai_marked": bool(wm.get("detected")) or manifest_ai,
            "watermark": wm, "c2pa": layer2}
