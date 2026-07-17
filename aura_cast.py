"""
aura_cast.py
"Discord call"-style render engine.

Each person = one image (cropped to a circle) + one audio track.
For every person, driven by THEIR OWN audio envelope, we render:
  - a tile border that lights up while they speak,
  - an aura of concentric rings that pulses outward,
  - a bar waveform under the avatar,
  - a name in a semi-transparent black box.

Active optimizations:
  1) cached static base per person (background + name),
  2) a single blur per aura (layer cropped to the aura size),
  3) silent frames are skipped (an idle frame is reused),
  4) multiprocess render (one Pool, Participants built once per worker).

Requires: pillow, numpy.  Optional: soundfile (better audio reading),
ffmpeg on the PATH (to export video and to read mp3/m4a).

Author: Diego Fischer.
License: CC BY 4.0.
"""

from __future__ import annotations

import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from copy import deepcopy

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import multiprocessing as mp
from collections import deque
import colorsys
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = HERE

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
PRESETS_DIR = os.path.join(APP_DIR, "presets")
PEOPLE_PATH = os.path.join(APP_DIR, "people_library.json")


# ************************************** CONFIG **************************************
DEFAULTS = {
    "canvas": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "transparent": False,           # False => background_color is painted
        "background_color": "#000000",  # black background
        "margin": 40,                   # outer canvas margin (px)
        "gap_x": 24,                    # horizontal gap between tiles (px)
        "gap_y": 24,                    # vertical gap between rows (px)
        "safe_bottom": 0.07,            # bottom safe zone (fraction of height),
                                        # reserved for the YouTube control bar, etc.
    },
    "tile": {
        "corner_radius": 28,
        "tile_height_scale": 1.0,       # each tile height as a fraction of its cell
        "background_color": "#000000",  # used when color_mode == "manual"
        "color_mode": "edge",           # edge | dominant | average | manual
        "color_darken": 0.0,            # 0..1 toward black
        "color_sat": 1.0,               # saturation multiplier
        "avatar_scale": 0.30,           # avatar diameter = fraction of the tile shorter side
        "avatar_offset_y": -0.06,       # avatar vertical offset (fraction of height)
        "avatar_pop": False,            # avatar grows progressively while speaking
        "avatar_pop_max": 0.15,         # max growth (0.15 => up to +15% of the diameter)
        "avatar_pop_mode": "reactive",  # reactive = size tracks volume | speaking = grow once while speaking
        "border_width": 0,              # base tile border (0 = no border)
        "border_color": "#FFFFFF22",
        "border_glow": True,            # the border lights up while speaking
        "border_glow_color": "#23A55A",
        "border_glow_width": 6,
        "border_glow_blur": 10,
    },
    "aura": {
        "enabled": True,
        "color": "#23A55A",
        "rings": 3,
        "thresholds": [0.05, 0.18, 0.35],
        "sensitivity": 1.0,             # >1 = rings more sensitive (lower threshold)
        "gains": [1.0, 0.55, 0.28],
        "widths": [5, 3, 2],
        "blur": 7,                      # one medium blur for the whole aura
        "delays": [0, 2, 4],            # delay (frames) => outward wave
        "spacing": 14,
        "radius_offset": 8,
        "expand": 10,
        "knee": 0.08,
        "attack": 0.6,
        "release": 0.90,
    },
    "wave": {
        "enabled": True,
        "style": "bars",               # bars, line, mirror, relleno, puntos, radial
        "color": "#23A55A",
        "offset_y": 0.20,               # position below the avatar center (fraction of height)
        "width_frac": 0.62,
        "height": 46,
        "bars": 48,
        "points": 128,                  # resolution for the line based styles
        "bar_width": 4,
        "line_width": 3,                # stroke width for line, mirror, relleno, puntos, radial
        "min_height": 3,
        "opacity": 0.9,
        "idle_opacity": 0.35,
        "idle_motion": 0.15,            # gentle wave motion while nobody talks (0 = flat and static)
        "glow": True,                   # halo behind the line (line and radial)
        "radial_gap": 12,               # distance from the avatar edge (radial)
    },
    "name": {
        "enabled": True,
        # position: {top,bottom}-{left,center,right}
        "position": "bottom-left",
        "offset_x": 0,                  # fine horizontal nudge (px, +right / -left)
        "offset_y": 0,                  # fine vertical nudge (px, +down / -up)
        "margin": 16,
        "font_size": 22,
        "font_path": "",
        "text_color": "#FFFFFF",
        "pill": True,
        "pill_color": "#000000",
        "pill_opacity": 0.6,            # 0..1  (opacity of the BOX, not the text)
        "pill_padding": [12, 6],        # [horizontal, vertical]
        "pill_radius": 8,               # 0 = square box
    },
    "audio": {
        "window_ms": 50,
        "normalize": "p99",             # p99 | peak | none
        "gate": 0.02,
    },
    "output": {
        "dir": "./render",
        "format": "mp4",                # png_sequence | mov | webm | mp4
        "prefix": "frame",
        "ffmpeg": "ffmpeg",
        "mux_audio": True,              # mix the tracks and embed them (mp4/mov)
        "cleanup_frames": True,         # delete intermediate PNGs after building the video
        "workers": "auto",              # "auto" (cores-1) | "all" | exact number (int or str)
    },
    # participants: {"name","image","audio","crop","color","aura_color"}
    "participants": [],
    "ui_language": "en",                # "en" | "es"  (interface language)
}


def _merge(base, over):
    out = deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def load_config(path=CONFIG_PATH):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return _merge(DEFAULTS, json.load(f))
        except Exception as e:  # noqa: BLE001
            print(f"[config] Could not read {path}: {e}. Using defaults.")
    return deepcopy(DEFAULTS)


def save_config(cfg, path=CONFIG_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ****************************** PRESETS (look/settings) ******************************

SETTINGS_KEYS = ["canvas", "tile", "aura", "wave", "name", "audio", "output"]


def extract_settings(cfg):
    s = {k: deepcopy(cfg[k]) for k in SETTINGS_KEYS if k in cfg}
    if "output" in s:
        s["output"].pop("dir", None)
    return s


def apply_settings(cfg, settings):
    for k, v in settings.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k] = _merge(cfg[k], v)
        else:
            cfg[k] = deepcopy(v)
    return cfg


def list_presets():
    if not os.path.isdir(PRESETS_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(PRESETS_DIR) if f.endswith(".json"))


def save_preset(name, cfg):
    os.makedirs(PRESETS_DIR, exist_ok=True)
    path = os.path.join(PRESETS_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(extract_settings(cfg), f, indent=2, ensure_ascii=False)
    return path


def load_preset(name):
    with open(os.path.join(PRESETS_DIR, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def delete_preset(name):
    path = os.path.join(PRESETS_DIR, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)

# *********************** BASE PEOPLE LIBRARY ***********************
def load_base_people():
    if not os.path.exists(PEOPLE_PATH):
        return []
    try:
        with open(PEOPLE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def save_base_people(people):
    with open(PEOPLE_PATH, "w", encoding="utf-8") as f:
        json.dump(people, f, indent=2, ensure_ascii=False)


def add_base_person(person):
    """Add (or replace by name) a base person in the library."""
    keep = {"name", "image", "crop", "color", "aura_color"}
    person = {k: v for k, v in person.items() if k in keep}
    people = [p for p in load_base_people() if p.get("name") != person.get("name")]
    people.append(person)
    save_base_people(people)
    return people


def delete_base_person(name):
    people = [p for p in load_base_people() if p.get("name") != name]
    save_base_people(people)
    return people


# ************************************** UTILS **************************************
def hex_rgba(s, alpha=None):
    """'#RRGGBB' or '#RRGGBBAA' -> (r,g,b,a). alpha (0..1) multiplies the alpha."""
    s = s.lstrip("#")
    r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    a = int(s[6:8], 16) if len(s) >= 8 else 255
    if alpha is not None:
        a = int(max(0.0, min(1.0, alpha)) * a)
    return (r, g, b, a)


def get_font(cfg):
    fp, size = cfg["name"]["font_path"], int(cfg["name"]["font_size"])
    candidates = [
        fp,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:  # noqa: BLE001
                pass
    return ImageFont.load_default()


# ************************************** COLOR **************************************
def tile_color_from_image(path, mode="edge", darken=0.0, sat=1.0):
    """
    Derive a background color from the image.
      edge     -> border mode color (ideal for flat-background illustrations)
      dominant -> most frequent color after quantizing
      average  -> simple average
    """

    im = Image.open(path).convert("RGB")
    im.thumbnail((160, 160))
    a = np.asarray(im)

    if mode == "average":
        rgb = a.reshape(-1, 3).mean(axis=0)
    elif mode == "dominant":
        q = im.quantize(colors=8, method=Image.MEDIANCUT)
        pal = np.array(q.getpalette()[:24]).reshape(8, 3)
        counts = np.bincount(np.asarray(q).ravel(), minlength=8)
        rgb = pal[int(counts.argmax())]
    else:  # edge
        k = max(2, min(a.shape[:2]) // 12)
        border = np.concatenate([
            a[:k].reshape(-1, 3), a[-k:].reshape(-1, 3),
            a[:, :k].reshape(-1, 3), a[:, -k:].reshape(-1, 3),
        ])
        q = (border // 16).astype(np.int32)
        keys = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
        mode_key = np.bincount(keys).argmax()
        sel = border[keys == mode_key]
        rgb = sel.mean(axis=0)

    r, g, b = [float(c) / 255 for c in rgb]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l *= (1.0 - max(0.0, min(1.0, darken)))
    s = max(0.0, min(1.0, s * sat))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255))


# ************************************** AUDIO **************************************
def load_audio(path):
    """(float32 mono samples, sr). Tries soundfile -> wave -> ffmpeg."""
    try:
        y, sr = sf.read(path, dtype="float32", always_2d=True)
        return y.mean(axis=1), sr
    except Exception:  # noqa: BLE001
        pass
    try:
        with wave.open(path, "rb") as w:
            sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
            raw = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
            return raw.reshape(-1, ch).mean(axis=1), sr
    except Exception:  # noqa: BLE001
        pass
    tmp = os.path.join(tempfile.gettempdir(), f"_ac_{abs(hash(path))}.wav")
    subprocess.run(["ffmpeg", "-y", "-i", path, "-ac", "1", "-ar", "48000", tmp],
                   check=True, capture_output=True)
    y, sr = load_audio(tmp)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return y, sr

_ENV_VECTOR_MAX_SAMPLES = 60_000_000


def envelope(path, fps, acfg, aura):
    """Per-frame RMS, normalized and smoothed with attack/release (inertia)."""
    y, sr = load_audio(path)
    return compute_envelope(y, sr, fps, acfg, aura)


def compute_envelope(y, sr, fps, acfg, aura):
    hop = sr / fps
    win = max(1, int(sr * acfg["window_ms"] / 1000))
    L = len(y)
    n = max(1, int(math.ceil(L / hop)))
    half = win // 2

    if L <= _ENV_VECTOR_MAX_SAMPLES:
        yf = y.astype(np.float64)
        yf *= yf
        csum = np.empty(L + 1, dtype=np.float64)
        csum[0] = 0.0
        np.cumsum(yf, out=csum[1:])
        del yf
        centers = (np.arange(n) * hop).astype(np.int64)
        a = np.clip(centers - half, 0, L)
        b = np.clip(centers + half, 0, L)
        counts = np.maximum(b - a, 1)
        rms = np.sqrt((csum[b] - csum[a]) / counts).astype(np.float32)
        rms[b <= a] = 0.0                          # empty window => silence
        del csum
    else:
        # Memory-light fallback for very long audio (same result, old speed).
        rms = np.zeros(n, dtype=np.float32)
        for i in range(n):
            c = int(i * hop)
            a0, b0 = max(0, c - half), min(L, c + half)
            seg = y[a0:b0]
            rms[i] = float(np.sqrt(np.mean(seg ** 2))) if seg.size else 0.0

    if acfg["normalize"] == "p99":
        ref = float(np.percentile(rms, 99)) or 1.0
    elif acfg["normalize"] == "peak":
        ref = float(rms.max()) or 1.0
    else:
        ref = 1.0
    rms = np.clip(rms / ref, 0, 1)
    rms[rms < acfg["gate"]] = 0.0

    env = np.zeros(n, dtype=np.float32)
    e = 0.0
    atk, rel = aura["attack"], aura["release"]
    for i, r in enumerate(rms):
        e = e + (r - e) * atk if r > e else e * rel + r * (1 - rel)
        env[i] = e
    return env


def wave_matrix(y, sr, fps, points):
    """Per-frame slice of the real waveform, shape (frames, points), in [-1, 1].
    Consecutive frames advance by one hop so the trace scrolls with the audio."""
    hop = sr / fps
    n = max(1, int(math.ceil(len(y) / hop)))
    win = max(points, int(2 * hop))
    half = win // 2
    rel = (np.linspace(0, win - 1, points) - half).astype(np.int64)
    L = len(y)
    out = np.zeros((n, points), dtype=np.float32)
    for i in range(n):
        gi = int(i * hop) + rel
        valid = (gi >= 0) & (gi < L)
        out[i] = np.where(valid, y[np.clip(gi, 0, L - 1)], 0.0)
    if points >= 3:
        out[:, 1:-1] = (out[:, :-2] + out[:, 1:-1] + out[:, 2:]) / 3.0
    peak = float(np.percentile(np.abs(out), 99)) or 1.0
    return np.clip(out / peak, -1, 1).astype(np.float32)


def ring_gain(v, thr, knee):
    return max(0.0, min(1.0, (v - thr) / max(1e-6, knee)))


def eff_threshold(A, i):
    """Threshold of ring i adjusted by sensitivity (>1 => more sensitive)."""
    return A["thresholds"][i] / max(0.05, A.get("sensitivity", 1.0))


def mix_audio(cfg, out_wav):
    """Sum all participants' tracks (with a simple limiter)."""
    tracks, sr_ref, maxlen = [], None, 0
    for s in cfg["participants"]:
        if not s.get("audio"):
            continue
        y, sr = load_audio(s["audio"])
        if sr_ref is None:
            sr_ref = sr
        elif sr != sr_ref:
            t_old = np.linspace(0, 1, len(y), endpoint=False)
            t_new = np.linspace(0, 1, int(len(y) * sr_ref / sr), endpoint=False)
            y = np.interp(t_new, t_old, y).astype(np.float32)
        tracks.append(y)
        maxlen = max(maxlen, len(y))
    if not tracks:
        return None
    mix = np.zeros(maxlen, dtype=np.float32)
    for y in tracks:
        mix[:len(y)] += y
    peak = float(np.max(np.abs(mix))) or 1.0
    if peak > 1.0:
        mix /= peak
    try:
        sf.write(out_wav, mix, sr_ref)
    except Exception:
        with wave.open(out_wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr_ref)
            w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    return out_wav


# ************************************** AVATAR **************************************
def circular_avatar(path, d, crop=None):
    """Circular crop using normalized zoom/offset; returns a d×d RGBA image."""
    crop = crop or {"zoom": 1.0, "ox": 0.0, "oy": 0.0}
    img = Image.open(path).convert("RGBA")
    W, H = img.size
    side = min(W, H) / max(0.1, float(crop["zoom"]))
    cx = W / 2 + float(crop["ox"]) * W
    cy = H / 2 + float(crop["oy"]) * H
    cx = min(max(cx, side / 2), W - side / 2)
    cy = min(max(cy, side / 2), H - side / 2)
    box = (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
    img = img.resize((d, d), Image.LANCZOS, box=box)

    ss = 4  # supersampled mask => clean edge
    mask = Image.new("L", (d * ss, d * ss), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d * ss - 1, d * ss - 1), fill=255)
    img.putalpha(mask.resize((d, d), Image.LANCZOS))
    return img


# ************************************** LAYOUT **************************************
def rows_for(n):
    """Discord-style rows: 3 -> [2,1]; 5 -> [3,2]; 7 -> [3,2,2]..."""
    presets = {1: [1], 2: [2], 3: [2, 1], 4: [2, 2], 5: [3, 2], 6: [3, 3],
               7: [2, 3, 2], 8: [3, 3, 2], 9: [3, 3, 3]}
    if n in presets:
        return presets[n]
    cols = int(math.ceil(math.sqrt(n)))
    nrows = int(math.ceil(n / cols))
    base, extra = divmod(n, nrows)
    return [base + (1 if i < extra else 0) for i in range(nrows)]


def layout(n, cfg):
    C = cfg["canvas"]
    W, H = C["width"], C["height"]
    m = C["margin"]
    gx = C.get("gap_x", C.get("gap", 24))
    gy = C.get("gap_y", C.get("gap", 24))
    safe = int(H * C.get("safe_bottom", 0.0))       # bottom safe zone, mostly for youtube
    hscale = cfg["tile"].get("tile_height_scale", 1.0)
    MIN_SIDE = 8

    rows = rows_for(n)
    # usable region: between the top margin and (margin + safe zone) at the bottom
    avail_h = H - 2 * m - safe - gy * (len(rows) - 1)
    cell_h = max(float(MIN_SIDE), avail_h / len(rows))
    boxes = []
    for ri, count in enumerate(rows):
        tw = max(float(MIN_SIDE), (W - 2 * m - gx * (count - 1)) / count)
        cell_y = m + ri * (cell_h + gy)
        tile_h = max(float(MIN_SIDE), cell_h * hscale)
        y = cell_y + (cell_h - tile_h) / 2
        row_w = count * tw + (count - 1) * gx
        x0 = (W - row_w) / 2
        for ci in range(count):
            boxes.append((int(x0 + ci * (tw + gx)), int(y),
                          max(MIN_SIDE, int(tw)), max(MIN_SIDE, int(tile_h))))
    return boxes[:n]


# ************************************** NOMBRE **************************************
def _draw_name(tile, name, w, h, N, font):
    """Draw the name on a separate layer and composite it onto the tile."""
    if not N["enabled"]:
        return
    pad_x, pad_y = N["pill_padding"]
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(layer)

    try:
        asc, desc = font.getmetrics()
        text_h = asc + desc
        text_w = int(dr.textlength(name, font=font))
        baseline = asc
    except AttributeError:
        bb = dr.textbbox((0, 0), name, font=font)
        text_w, text_h, baseline = bb[2] - bb[0], bb[3] - bb[1], 0

    box_w = text_w + 2 * pad_x
    box_h = text_h + 2 * pad_y
    m = N["margin"]
    pos = N.get("position", "bottom-left")

    # horizontal
    if "right" in pos:
        bx = w - box_w - m
    elif "center" in pos:
        bx = (w - box_w) // 2
    else:  # left
        bx = m
    # vertical
    by = m if "top" in pos else h - box_h - m

    bx += int(N.get("offset_x", 0))
    by += int(N.get("offset_y", 0))

    if N["pill"]:
        fill = hex_rgba(N["pill_color"], N.get("pill_opacity", 0.6))
        r_pill = N["pill_radius"]
        if r_pill > 0:
            dr.rounded_rectangle((bx, by, bx + box_w, by + box_h), r_pill, fill=fill)
        else:
            dr.rectangle((bx, by, bx + box_w, by + box_h), fill=fill)

    dr.text((bx + pad_x, by + pad_y + baseline), name,
            font=font, fill=hex_rgba(N["text_color"]), anchor="ls")

    tile.alpha_composite(layer)


# ************************************** PARTICIPANTE **************************************
class Participant:
    # Cap on cached blurred aura layers per participant. Each is a small RGBA
    # image; this bounds worst-case memory while covering the states that recur.
    _AURA_CACHE_MAX = 192

    def __init__(self, spec, cfg, env=None, color=None, wave=None):
        self.name = spec.get("name", "?")
        self.image = spec["image"]
        self.audio = spec.get("audio")
        self.crop = spec.get("crop", {"zoom": 1.0, "ox": 0.0, "oy": 0.0})

        mode = cfg["tile"]["color_mode"]
        if color is not None:
            self.color = color
        elif spec.get("color"):
            self.color = spec["color"]
        elif mode == "manual":
            self.color = cfg["tile"]["background_color"]
        else:
            self.color = tile_color_from_image(
                self.image, mode, cfg["tile"]["color_darken"], cfg["tile"]["color_sat"])

        self.aura_color = spec.get("aura_color") or cfg["aura"]["color"]
        fps = cfg["canvas"]["fps"]
        points = cfg["wave"].get("points", 128)
        if env is not None:
            self.env = env
            self.wave = wave
        elif self.audio:
            y, sr = load_audio(self.audio)
            self.env = compute_envelope(y, sr, fps, cfg["audio"], cfg["aura"])
            self.wave = wave_matrix(y, sr, fps, points)
            del y
        else:
            self.env = np.zeros(1, dtype=np.float32)
            self.wave = None
        self._avatar_cache = {}
        self._base = (None, None)
        self._aura_cache = {}
        self._aura_sig = None
        self._glow_cache = {}
        self._glow_sig = None

    def avatar(self, d):
        key = (d, tuple(sorted(self.crop.items())))
        if key not in self._avatar_cache:
            self._avatar_cache[key] = circular_avatar(self.image, d, self.crop)
        return self._avatar_cache[key]

    def e(self, i):
        if len(self.env) == 0:
            return 0.0
        return float(self.env[min(max(i, 0), len(self.env) - 1)])

    def wrow(self, i):
        if self.wave is None:
            return None
        if i < 0:
            return np.zeros(self.wave.shape[1], dtype=np.float32)
        return self.wave[min(i, len(self.wave) - 1)]

    def base_ref(self, w, h, cfg, font):
        """Cached static base (background + border + name)."""
        key = (w, h)
        if self._base[0] != key:
            self._base = (key, self._build_base(w, h, cfg, font))
        return self._base[1]

    def glow_layer(self, w, h, cfg):
        """Blurred border-glow at full intensity, cached per tile size. Its alpha
        is scaled per frame by the current gain, so we blur once, not every frame."""
        T = cfg["tile"]
        sig = (T["border_glow_color"], T["border_glow_width"],
               T["border_glow_blur"], T["corner_radius"])
        if self._glow_sig != sig:           
            self._glow_cache.clear()
            self._glow_sig = sig
        key = (w, h)
        layer = self._glow_cache.get(key)
        if layer is None:
            layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(layer).rounded_rectangle(
                (2, 2, w - 3, h - 3), T["corner_radius"],
                outline=hex_rgba(T["border_glow_color"]), width=T["border_glow_width"])
            layer = layer.filter(ImageFilter.GaussianBlur(T["border_glow_blur"]))
            self._glow_cache[key] = layer
        return layer

    def _build_base(self, w, h, cfg, font):
        """Background + border + name (constant). The avatar is drawn per frame."""
        T = cfg["tile"]
        tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        r = T["corner_radius"]
        d.rounded_rectangle((0, 0, w - 1, h - 1), r, fill=hex_rgba(self.color))
        if T["border_width"]:
            d.rounded_rectangle((0, 0, w - 1, h - 1), r,
                                outline=hex_rgba(T["border_color"]), width=T["border_width"])
        _draw_name(tile, self.name, w, h, cfg["name"], font)
        return tile

# ************************************************************************
# ******************************** RENDER ********************************
# ************************************************************************

_AURA_GAIN_STEPS = 24


def _aura_layer(p, frame, dia, A):
    """Blurred aura layer, cached. Returns (img, center) or (None, 0)."""
    sig = (A["rings"], A["radius_offset"], A["spacing"], A["expand"],
           tuple(A["widths"]), A["blur"], tuple(A["gains"]), p.aura_color)
    if p._aura_sig != sig:
        p._aura_cache.clear()
        p._aura_sig = sig

    gq = []
    active = False
    for i in range(A["rings"]):
        ev = p.e(frame - A["delays"][i])
        g = ring_gain(ev, eff_threshold(A, i), A["knee"])
        q = int(round(g * _AURA_GAIN_STEPS))
        if q > 0:
            active = True
        gq.append(q)
    if not active:
        return None, 0

    key = (dia, tuple(gq))
    cached = p._aura_cache.get(key)
    if cached is not None:
        return cached

    rmax = (dia / 2 + A["radius_offset"] + A["spacing"] * (A["rings"] - 1)
            + A["expand"] + max(A["widths"]))
    S = int(rmax * 2) + 4
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(layer)
    c = S // 2
    for i in range(A["rings"]):
        g = gq[i] / _AURA_GAIN_STEPS
        if g <= 0:
            continue
        rad = dia / 2 + A["radius_offset"] + A["spacing"] * i + A["expand"] * g
        dr.ellipse((c - rad, c - rad, c + rad, c + rad),
                   outline=hex_rgba(p.aura_color, g * A["gains"][i]), width=A["widths"][i])
    result = (layer.filter(ImageFilter.GaussianBlur(A["blur"])), c)

    if len(p._aura_cache) < Participant._AURA_CACHE_MAX:
        p._aura_cache[key] = result
    return result


def _scaled_alpha(img, factor):
    """Return a copy of img with its alpha channel multiplied by factor (0..1)."""
    r, g, b, a = img.split()
    a = a.point(lambda v: int(v * factor))
    return Image.merge("RGBA", (r, g, b, a))


def _idle_blend(wf, frame, idle):
    """Blend a slow traveling wave into wf where the signal is near silence, so
    the wave keeps drifting when nobody talks instead of going flat."""
    if idle <= 0 or wf is None:
        return wf
    P = len(wf)
    idlewave = idle * np.sin(np.arange(P) * 0.35 + frame * 0.5)
    quiet = np.clip(1.0 - np.abs(wf) / idle, 0.0, 1.0)
    return wf + idlewave * quiet


def _wave_bars(d, p, frame, wx, wy, ww, Wv, col, vis):
    bars, bw = Wv["bars"], Wv["bar_width"]
    idle = Wv.get("idle_motion", 0.0)
    step = ww / bars
    for b in range(bars):
        ev = p.e(frame - (bars - 1 - b))
        if idle > 0:
            ev = max(ev, idle * (0.5 + 0.5 * math.sin((b + frame) * 0.5)))
        bh = max(Wv["min_height"], ev * Wv["height"])
        bx = wx + b * step + (step - bw) / 2
        d.rounded_rectangle((bx, wy - bh, bx + bw, wy + bh), bw / 2, fill=hex_rgba(col, vis))


def _wave_line(d, pts, col, vis, bw, glow):
    if glow:
        for mult, a in ((6.0, 0.10), (3.5, 0.18)):
            d.line(pts, fill=hex_rgba(col, vis * a), width=max(1, int(bw * mult)), joint="curve")
    d.line(pts, fill=hex_rgba(col, vis), width=max(1, bw), joint="curve")


def _wave_mirror(d, xs, wy, env, col, vis, bw):
    top = list(zip(xs.tolist(), (wy - env).tolist()))
    bot = list(zip(xs.tolist(), (wy + env).tolist()))
    d.polygon(top + bot[::-1], fill=hex_rgba(col, vis * 0.45))
    d.line(top, fill=hex_rgba(col, vis), width=max(1, bw), joint="curve")
    d.line(bot, fill=hex_rgba(col, vis), width=max(1, bw), joint="curve")


def _wave_puntos(d, xs, ys, wf, col, vis, bw):
    step = max(1, len(xs) // 40)
    for i in range(0, len(xs), step):
        r = max(1.0, bw * (0.4 + abs(float(wf[i]))))
        x, y = float(xs[i]), float(ys[i])
        d.ellipse((x - r, y - r, x + r, y + r), fill=hex_rgba(col, vis))


def _wave_relleno(canvas, d, xs, wy, env, col, vis, bw, height):
    P = len(xs)
    top = [(float(xs[i]), float(wy - env[i])) for i in range(P)]
    bx0, bx1 = int(xs[0]), int(xs[-1]) + 1
    by0, by1 = int(wy - height) - 1, int(wy)
    Wc, Hc = bx1 - bx0, by1 - by0
    if Wc > 0 and Hc > 0:
        mask = Image.new("L", (Wc, Hc), 0)
        poly = ([(x - bx0, y - by0) for (x, y) in top]
                + [(float(xs[-1]) - bx0, wy - by0), (float(xs[0]) - bx0, wy - by0)])
        ImageDraw.Draw(mask).polygon(poly, fill=255)
        r, g, b = hex_rgba(col)[:3]
        alpha = (np.linspace(vis, 0.0, Hc)[:, None]
                 * (np.asarray(mask, np.float32) / 255.0) * 255).astype(np.uint8)
        grad = np.zeros((Hc, Wc, 4), np.uint8)
        grad[..., 0], grad[..., 1], grad[..., 2] = r, g, b
        grad[..., 3] = alpha
        canvas.alpha_composite(Image.fromarray(grad, "RGBA"), (bx0, by0))
    d.line(top, fill=hex_rgba(col, vis), width=max(1, bw), joint="curve")


def _wave_radial(d, p, frame, cx, cy, base_dia, Wv, col, vis):
    R0 = base_dia / 2 + Wv.get("radial_gap", 12)
    bw = Wv.get("line_width", 3)
    wf = p.wrow(frame)
    if wf is None:
        d.ellipse((cx - R0, cy - R0, cx + R0, cy + R0),
                  outline=hex_rgba(col, vis), width=max(1, bw))
        return
    P = len(wf)
    ang = 2 * np.pi * np.arange(P) / P
    rr = R0 + _idle_blend(wf, frame, Wv.get("idle_motion", 0.0)) * Wv["height"]
    px, py = cx + rr * np.cos(ang), cy + rr * np.sin(ang)
    pts = list(zip(px.tolist(), py.tolist()))
    pts.append(pts[0])
    if Wv.get("glow", True):
        for mult, a in ((5.0, 0.12), (3.0, 0.18)):
            d.line(pts, fill=hex_rgba(col, vis * a), width=max(1, int(bw * mult)), joint="curve")
    d.line(pts, fill=hex_rgba(col, vis), width=max(1, bw), joint="curve")


def draw_wave(canvas, d, p, geom, frame, cfg, g0):
    x0, y0, w, h, cx, cy, base_dia = geom
    Wv = cfg["wave"]
    style = Wv.get("style", "bars")
    col = Wv["color"]
    vis = Wv["idle_opacity"] + (Wv["opacity"] - Wv["idle_opacity"]) * g0
    height = Wv["height"]
    bw = Wv["bar_width"]
    lw = Wv.get("line_width", 3)
    ww = int(w * Wv["width_frac"])
    wx = x0 + (w - ww) / 2
    wy = int(cy + base_dia / 2 + h * Wv["offset_y"])

    if style == "radial":
        _wave_radial(d, p, frame, cx, cy, base_dia, Wv, col, vis)
        return
    if style == "bars":
        _wave_bars(d, p, frame, wx, wy, ww, Wv, col, vis)
        return

    wf = p.wrow(frame)
    if wf is None:
        _wave_bars(d, p, frame, wx, wy, ww, Wv, col, vis)
        return
    wf = _idle_blend(wf, frame, Wv.get("idle_motion", 0.0))
    P = len(wf)
    xs = wx + (np.arange(P) / max(1, P - 1)) * ww
    ys = wy - wf * height
    if style == "line":
        _wave_line(d, list(zip(xs.tolist(), ys.tolist())), col, vis, lw, Wv.get("glow", True))
    elif style == "mirror":
        _wave_mirror(d, xs, wy, np.abs(wf) * height, col, vis, lw)
    elif style == "relleno":
        _wave_relleno(canvas, d, xs, wy, np.abs(wf) * height, col, vis, lw, height)
    elif style == "puntos":
        _wave_puntos(d, xs, ys, wf, col, vis, lw)
    else:
        _wave_bars(d, p, frame, wx, wy, ww, Wv, col, vis)


def compose_tile(canvas, p, box, frame, cfg, font):
    """Draw participant p's tile straight onto the shared canvas at box origin."""
    x0, y0, w, h = box
    A, T, Wv = cfg["aura"], cfg["tile"], cfg["wave"]

    # static base (background + border + name): composited, never mutated
    canvas.alpha_composite(p.base_ref(w, h, cfg, font), (x0, y0))
    d = ImageDraw.Draw(canvas)

    env_now = p.e(frame)
    g0 = ring_gain(env_now, eff_threshold(A, 0), A["knee"])

    # avatar size: base, or growing while speaking if avatar_pop is on.
    base_dia = max(2, int(min(w, h) * T["avatar_scale"]))
    if T.get("avatar_pop"):
        # reactive : diameter tracks loudness continuously (pulses with volume).
        # speaking : diameter steps up to the full pop while the person speaks and
        #            eases back when they stop.
        if T.get("avatar_pop_mode", "reactive") == "speaking":
            gp = g0
        else:
            gp = min(1.0, env_now)
        dia = int(base_dia * (1.0 + T.get("avatar_pop_max", 0.15) * gp))
        dia -= dia % 2
    else:
        dia = base_dia
    cx, cy = x0 + w // 2, y0 + int(h // 2 + h * T["avatar_offset_y"])

    if T["border_glow"] and g0 > 0:
        canvas.alpha_composite(_scaled_alpha(p.glow_layer(w, h, cfg), g0), (x0, y0))
        d.rounded_rectangle((x0 + 2, y0 + 2, x0 + w - 3, y0 + h - 3), T["corner_radius"],
                            outline=hex_rgba(T["border_glow_color"], g0 * 0.9), width=2)

    # aura (cached, one blur)
    if A["enabled"]:
        aura_img, c = _aura_layer(p, frame, dia, A)
        if aura_img is not None:
            canvas.alpha_composite(aura_img, (cx - c, cy - c))

    canvas.alpha_composite(p.avatar(dia), (cx - dia // 2, cy - dia // 2))

    if Wv["enabled"]:
        draw_wave(canvas, d, p, (x0, y0, w, h, cx, cy, base_dia), frame, cfg, g0)


def render_frame(frame, parts, cfg, font=None):
    C = cfg["canvas"]
    bg = (0, 0, 0, 0) if C["transparent"] else hex_rgba(C["background_color"])
    canvas = Image.new("RGBA", (C["width"], C["height"]), bg)
    font = font or get_font(cfg)
    for p, box in zip(parts, layout(len(parts), cfg)):
        compose_tile(canvas, p, box, frame, cfg, font)
    return canvas


def frame_is_idle(parts, i, thr):
    return all(p.e(i) < thr for p in parts)


def wave_animates_idle(cfg):
    """True when the wave keeps moving during silence, so silent frames are not
    identical and cannot be deduplicated."""
    w = cfg.get("wave", {})
    return bool(w.get("enabled", True)) and w.get("idle_motion", 0) > 0

# **************************
# **** multiprocessing *****
# **************************

_W = {}


def _init_worker(cfg, envs, colors, waves):
    _W["cfg"] = cfg
    _W["font"] = get_font(cfg)
    _W["thr"] = eff_threshold(cfg["aura"], 0)
    _W["animate_idle"] = wave_animates_idle(cfg)
    _W["parts"] = [Participant(s, cfg, env=envs[k], color=colors[k], wave=waves[k])
                   for k, s in enumerate(cfg["participants"])]


def _png_bytes(img):
    """Encode a frame to PNG in memory. compress_level=1 favors speed over size
    since the bytes go straight down a pipe and are never stored."""
    buf = io.BytesIO()
    img.save(buf, "png", compress_level=1)
    return buf.getvalue()


def _render_png_bytes(i):
    """Worker task: PNG bytes for frame i, or None if the frame is idle (so the
    parent substitutes the single cached idle frame instead of shipping it)."""
    parts, cfg, font, thr = _W["parts"], _W["cfg"], _W["font"], _W["thr"]
    if not _W["animate_idle"] and frame_is_idle(parts, i, thr):
        return None
    return _png_bytes(render_frame(i, parts, cfg, font))


def _render_one_to_disk(i):
    """Worker task used only for png_sequence output (frames are the deliverable)."""
    cfg, parts, font = _W["cfg"], _W["parts"], _W["font"]
    path = os.path.join(_W["frames_dir"], f"{cfg['output']['prefix']}_{i:06d}.png")
    render_frame(i, parts, cfg, font).save(path)
    return i


def _video_codec_args(cfg, fmt):
    """ffmpeg -c:v arguments per container. output.video_codec can override the
    mp4 encoder (e.g. 'h264_nvenc' to encode on an NVIDIA GPU); default libx264."""
    if fmt == "mov":
        # mov conserves opacity and is lossless
        return ["-c:v", "qtrle"]                             
    if fmt == "webm":
        # webm conserve opacity, but is... lossfull?... loser?... whatever
        return ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p"]      
    enc = cfg["output"].get("video_codec") or "libx264"
    if enc not in ("libx264", "h264_nvenc", "hevc_nvenc"):
        enc = "libx264"
    # h264/yuv420p needs even dimensions; pad up if odd.
    return ["-c:v", enc, "-pix_fmt", "yuv420p",
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]


def _open_ffmpeg_pipe(cfg, fmt, out, audio_path):
    """Start ffmpeg reading a PNG stream from stdin, so we never touch the disk
    for intermediate frames. Returns the Popen handle (write frames to .stdin)."""
    fps, ff = cfg["canvas"]["fps"], cfg["output"]["ffmpeg"]
    cmd = [ff, "-y", "-f", "image2pipe", "-framerate", str(fps), "-i", "-"]
    has_audio = bool(audio_path) and fmt in ("mp4", "mov")
    if has_audio:
        cmd += ["-i", audio_path]
    cmd += _video_codec_args(cfg, fmt)
    if has_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [out]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def cpu_count_safe():
    """Number of system cores, with fallbacks if the OS won't report it."""
    try:
        n = os.cpu_count()
        if n and n > 0:
            return int(n)
    except Exception:  # noqa: BLE001
        pass
    try:
        return max(1, mp.cpu_count())
    except Exception:  # noqa: BLE001
        return 1


def resolve_workers(setting):
    """Convert the output.workers setting into a valid process count.

    Accepts:
      "auto"  -> all cores minus one (keeps the machine usable)
      "all"   -> all cores
      "1"/int -> that exact count (clamped to the available range)
    """
    total = cpu_count_safe()
    try:
        if setting in (None, "auto", ""):
            return max(1, total - 1)
        if setting == "all":
            return total
        n = int(setting)
        return max(1, min(n, total))
    except (ValueError, TypeError):
        return 1


def render_all(cfg, progress=None, workers=None, out_path=None):
    """Render all frames and export according to output.format.

    out_path: optional exact path for the output video. If None, defaults to
    <output.dir>/out.<format>. Ignored for png_sequence.
    """
    parts = [Participant(s, cfg) for s in cfg["participants"]]
    if not parts:
        raise ValueError("No participants.")
    n = max(len(p.env) for p in parts)
    outdir = cfg["output"]["dir"]
    os.makedirs(outdir, exist_ok=True)

    fmt = cfg["output"]["format"]
    thr = eff_threshold(cfg["aura"], 0)
    font = get_font(cfg)
    if workers is None:
        workers = resolve_workers(cfg["output"].get("workers", "auto"))

    envs = [p.env for p in parts]
    colors = [p.color for p in parts]
    waves = [p.wave for p in parts]
    use_pool = workers > 1 and n > 8
    animate_idle = wave_animates_idle(cfg)

    if fmt == "png_sequence":
        return _render_png_sequence(cfg, parts, n, thr, font, outdir,
                                    envs, colors, waves, workers, use_pool, progress)

    # ---- video: stream frames into ffmpeg ----
    audio_path = None
    if cfg["output"].get("mux_audio") and fmt in ("mp4", "mov"):
        audio_path = mix_audio(cfg, os.path.join(outdir, "_aura_mix.wav"))
    out = out_path or os.path.join(outdir, f"out.{fmt}")

    idle_bytes = _png_bytes(render_frame(-10_000, parts, cfg, font))
    proc = _open_ffmpeg_pipe(cfg, fmt, out, audio_path)
    try:
        if use_pool:
            window = max(2 * workers, 4)
            with mp.Pool(workers, initializer=_init_worker,
                         initargs=(cfg, envs, colors, waves)) as pool:
                pend, nxt = deque(), 0
                while nxt < min(window, n):
                    pend.append(pool.apply_async(_render_png_bytes, (nxt,)))
                    nxt += 1
                for written in range(n):
                    data = pend.popleft().get()
                    proc.stdin.write(data if data is not None else idle_bytes)
                    if nxt < n:
                        pend.append(pool.apply_async(_render_png_bytes, (nxt,)))
                        nxt += 1
                    if progress and written % 10 == 0:
                        progress(written, n)
        else:
            for i in range(n):
                if not animate_idle and frame_is_idle(parts, i, thr):
                    proc.stdin.write(idle_bytes)
                else:
                    proc.stdin.write(_png_bytes(render_frame(i, parts, cfg, font)))
                if progress and i % 10 == 0:
                    progress(i, n)
        proc.stdin.close()
        rc = proc.wait()
    except BrokenPipeError:
        proc.wait()
        raise RuntimeError("ffmpeg closed the pipe early, check the encoder "
                           "(e.g. video_codec) and ffmpeg availability.")
    if rc != 0:
        raise subprocess.CalledProcessError(rc, "ffmpeg")
    if progress:
        progress(n, n)

    # tidy up the temporary mixed-audio file
    if audio_path:
        try:
            os.remove(audio_path)
        except OSError:
            pass
    return out


def _render_png_sequence(cfg, parts, n, thr, font, outdir,
                         envs, colors, waves, workers, use_pool, progress):
    """Write a numbered PNG per frame to the output folder (frames are the
    deliverable). Idle frames are rendered once and copied."""
    prefix = cfg["output"]["prefix"]
    idle_path = os.path.join(outdir, "_idle.png")
    render_frame(-10_000, parts, cfg, font).save(idle_path)
    if wave_animates_idle(cfg):                    # silent frames move, render them all
        todo = list(range(n))
        idle_frames = []
    else:
        todo = [i for i in range(n) if not frame_is_idle(parts, i, thr)]
        idle_frames = [i for i in range(n) if frame_is_idle(parts, i, thr)]

    done = 0
    if use_pool and len(todo) > 8:
        with mp.Pool(workers, initializer=_init_worker_disk,
                     initargs=(cfg, envs, colors, waves, outdir)) as pool:
            for _ in pool.imap_unordered(_render_one_to_disk, todo, chunksize=8):
                done += 1
                if progress and done % 10 == 0:
                    progress(done, n)
    else:
        for i in todo:
            render_frame(i, parts, cfg, font).save(
                os.path.join(outdir, f"{prefix}_{i:06d}.png"))
            done += 1
            if progress and done % 10 == 0:
                progress(done, n)

    for i in idle_frames:
        shutil.copyfile(idle_path, os.path.join(outdir, f"{prefix}_{i:06d}.png"))
        done += 1
        if progress and done % 25 == 0:
            progress(done, n)
    try:
        os.remove(idle_path)
    except OSError:
        pass
    if progress:
        progress(n, n)
    return outdir


def _init_worker_disk(cfg, envs, colors, waves, frames_dir):
    _init_worker(cfg, envs, colors, waves)
    _W["frames_dir"] = frames_dir

