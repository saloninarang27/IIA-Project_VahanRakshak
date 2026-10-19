"""
Server-side OCR for registration-plate images.

A photo usually contains much more text than the plate: car badges, dealer
stickers, state names ("NEW YORK", "TAXI"), the "IND" strip, watermarks. So OCR
runs in two stages:

    1. Text detection + recognition: every text region in the image becomes a
       detection {text, confidence, box}.
    2. Plate selection (select_plate_text): drop mostly-lowercase words, group
       detections into rows, consider every run of adjacent boxes in a row (a plate
       is often split into "DL" + "1A B2345"), and keep the most plate-like run:
       the TALLEST text (plate characters dominate the plate) that has digits, a
       plate-like length and ideally an Indian registration pattern.

Engines are optional and probed at runtime, in order:
    1. rapidocr   (pip install rapidocr_onnxruntime) - detection-based, best on full photos
    2. pytesseract (pip install pytesseract + the Tesseract binary on PATH)
    3. easyocr    (pip install easyocr)

If none is installed, extract_plate_text() raises OCRUnavailable and the web UI
falls back to Tesseract.js in the browser, which applies the same selection rules.
"""
import io
import re
import subprocess
import sys

PLATE_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MAX_IMAGE_SIDE = 1600

MIN_PLATE_CHARS = 4
MAX_PLATE_CHARS = 11
# state code, RTO number, series letters, number - e.g. MH12DE1433, DL1AB2345
INDIAN_PLATE_RE = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$")
BH_SERIES_RE = re.compile(r"^\d{2}BH\d{4}[A-Z]{1,2}$")


class OCRUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Plate selection
# ---------------------------------------------------------------------------
def _normalize(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def _mostly_lowercase(text):
    lower = sum(1 for c in text if c.islower())
    upper = sum(1 for c in text if c.isupper())
    return lower > upper


def _rows(detections):
    """Group detections whose vertical centres and heights agree into text rows."""
    rows = []
    for d in sorted(detections, key=lambda d: -d["height"]):
        for row in rows:
            ref = row[0]
            if (abs(d["cy"] - ref["cy"]) < 0.4 * ref["height"]
                    and 0.6 <= d["height"] / ref["height"] <= 1.67):
                row.append(d)
                break
        else:
            rows.append([d])
    return [sorted(r, key=lambda d: d["x0"]) for r in rows]


def _join_run(run):
    """
    Join adjacent boxes. Detectors sometimes return overlapping boxes that both
    contain the same character ("12" and "2 XY 4821"), so characters that sit inside
    the overlap and repeat the end of the previous box are dropped.
    """
    parts = [run[0]["text"]]
    for a, b in zip(run, run[1:]):
        text_b = b["text"]
        overlap = a["x1"] - b["x0"]
        norm_a = _normalize(a["text"])
        if overlap > 0 and norm_a:
            char_width = (a["x1"] - a["x0"]) / len(norm_a)
            for k in range(min(3, len(norm_a)), 0, -1):
                stripped = text_b.lstrip(" -.")
                if (overlap >= 0.4 * k * char_width and _normalize(stripped[:k]) == norm_a[-k:]
                        and len(_normalize(stripped[:k])) == k):
                    text_b = stripped[k:]
                    break
        parts.append(text_b.strip())
    return " ".join(p for p in parts if p)


def _plate_score(text, height, max_height, confidence):
    norm = _normalize(text)
    if not (MIN_PLATE_CHARS <= len(norm) <= MAX_PLATE_CHARS) or not any(c.isdigit() for c in norm):
        return None
    score = height / max_height                  # plate characters are the largest text
    score += 0.3 * confidence
    if any(c.isalpha() for c in norm):
        score += 0.15
    score += 0.02 * len(norm)                    # prefer the whole row over a fragment of it
    if INDIAN_PLATE_RE.match(norm) or BH_SERIES_RE.match(norm):
        score += 0.35
    return round(score, 4)


def select_plate_text(detections):
    """
    detections: [{"text", "confidence", "box": [x0, y0, x1, y1]}, ...]
    Returns {"text", "confidence", "box", "score", "alternatives"}; text is "" if
    nothing plate-like was found.
    """
    items = []
    for d in detections:
        text = (d.get("text") or "").strip()
        if not text or _mostly_lowercase(text):
            continue                              # watermarks, brand names, URLs
        x0, y0, x1, y1 = d["box"]
        items.append({"text": text, "confidence": float(d.get("confidence") or 0.0),
                      "x0": x0, "x1": x1, "height": max(1.0, y1 - y0), "cy": (y0 + y1) / 2, "box": d["box"]})
    if not items:
        return {"text": "", "confidence": 0.0, "box": None, "score": None, "alternatives": []}

    max_height = max(i["height"] for i in items)
    candidates = []
    for row in _rows(items):
        for start in range(len(row)):
            for end in range(start + 1, len(row) + 1):
                run = row[start:end]
                # adjacent boxes only: a gap wider than ~1.5 character heights ends the plate
                if any(b["x0"] - a["x1"] > 1.5 * a["height"] for a, b in zip(run, run[1:])):
                    break
                text = _join_run(run)
                height = sum(r["height"] for r in run) / len(run)
                confidence = min(r["confidence"] for r in run)
                score = _plate_score(text, height, max_height, confidence)
                if score is None:
                    continue
                box = [min(r["box"][0] for r in run), min(r["box"][1] for r in run),
                       max(r["box"][2] for r in run), max(r["box"][3] for r in run)]
                candidates.append({"text": text, "normalized": _normalize(text), "confidence": round(confidence, 3),
                                   "score": score, "box": [round(v) for v in box]})

    # A stacked two-row plate (common on motorcycles): two rows of similar height, one above the other
    for c in candidates[:]:
        if any(ch.isdigit() for ch in c["normalized"]) and len(c["normalized"]) <= 6:
            for upper in items:
                h = c["box"][3] - c["box"][1]
                if (0.7 <= upper["height"] / h <= 1.4 and 0 < c["box"][1] - upper["box"][3] < 0.8 * h
                        and upper["box"][0] < c["box"][2] and upper["box"][2] > c["box"][0]):
                    text = f"{upper['text']} {c['text']}"
                    score = _plate_score(text, h, max_height, min(c["confidence"], upper["confidence"]))
                    if score is not None:
                        candidates.append({"text": text, "normalized": _normalize(text),
                                           "confidence": round(min(c["confidence"], upper["confidence"]), 3),
                                           "score": score + 0.05, "box": [min(upper["box"][0], c["box"][0]), upper["box"][1],
                                                                          max(upper["box"][2], c["box"][2]), c["box"][3]]})

    if not candidates:
        return {"text": "", "confidence": 0.0, "box": None, "score": None, "alternatives": []}
    # best score; on a tie prefer the longer reading (more of the plate captured)
    candidates.sort(key=lambda c: (-c["score"], -len(c["normalized"])))
    seen, unique = set(), []
    for c in candidates:
        if c["normalized"] not in seen:
            seen.add(c["normalized"])
            unique.append(c)
    best = unique[0]
    return {"text": best["text"], "confidence": best["confidence"], "box": best["box"], "score": best["score"],
            "alternatives": [{k: c[k] for k in ("text", "normalized", "score")} for c in unique[1:5]]}


# ---------------------------------------------------------------------------
# Engines: each returns a list of detections
# ---------------------------------------------------------------------------
def _load_image(image_bytes):
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    scale = MAX_IMAGE_SIDE / max(img.size)
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    elif img.width < 600:
        scale = 600 / img.width
        img = img.resize((600, max(1, round(img.height * scale))), Image.LANCZOS)
    return img


_rapidocr_engine = None


def _rapidocr(img):
    global _rapidocr_engine
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    if _rapidocr_engine is None:
        _rapidocr_engine = RapidOCR()
    result, _ = _rapidocr_engine(np.array(img)[:, :, ::-1])  # RGB -> BGR
    detections = []
    for box, text, conf in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        detections.append({"text": text, "confidence": float(conf), "box": [min(xs), min(ys), max(xs), max(ys)]})
    return detections


def _tesseract(img):
    import pytesseract
    from PIL import ImageOps

    gray = ImageOps.autocontrast(img.convert("L"))
    data = pytesseract.image_to_data(gray, config="--psm 11", output_type=pytesseract.Output.DICT)
    detections = []
    for text, conf, x, y, w, h in zip(data["text"], data["conf"], data["left"], data["top"], data["width"], data["height"]):
        if text.strip() and float(conf) >= 0:
            detections.append({"text": text, "confidence": float(conf) / 100.0, "box": [x, y, x + w, y + h]})
    return detections


_easyocr_reader = None


def _easyocr(img):
    global _easyocr_reader
    import easyocr
    import numpy as np

    if _easyocr_reader is None:
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    detections = []
    for box, text, conf in _easyocr_reader.readtext(np.array(img)):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        detections.append({"text": text, "confidence": float(conf), "box": [min(xs), min(ys), max(xs), max(ys)]})
    return detections


_ENGINES = [("rapidocr", "rapidocr_onnxruntime", _rapidocr),
            ("tesseract", "pytesseract", _tesseract),
            ("easyocr", "easyocr", _easyocr)]

_probe_cache = {}


def _imports_cleanly(module):
    """
    Import the engine in a child process first: a broken native build (e.g. an
    onnxruntime wheel that does not match the machine's VC++ runtime) can crash the
    interpreter outright, and that must not take the Mediator down with it.
    """
    if module not in _probe_cache:
        try:
            proc = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, timeout=60)
            _probe_cache[module] = proc.returncode == 0
        except Exception:
            _probe_cache[module] = False
    return _probe_cache[module]


def available_engines():
    import importlib.util
    found = []
    for name, module, _ in _ENGINES:
        if importlib.util.find_spec(module) is None or not _imports_cleanly(module):
            continue
        if name == "tesseract":
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
            except Exception:
                continue
        found.append(name)
    return found


def extract_plate_text(image_bytes):
    """
    Return {"engine", "raw_text", "confidence", "plate_box", "alternatives",
    "detections", "image_size"} or raise OCRUnavailable.
    """
    engines = available_engines()
    if not engines:
        raise OCRUnavailable("No server-side OCR engine installed (rapidocr_onnxruntime, pytesseract+Tesseract or easyocr).")
    img = _load_image(image_bytes)
    errors = []
    for name, _, fn in _ENGINES:
        if name not in engines:
            continue
        try:
            detections = fn(img)
        except Exception as e:  # try the next engine
            errors.append(f"{name}: {e}")
            continue
        selected = select_plate_text(detections)
        return {
            "engine": name,
            "raw_text": selected["text"],
            "confidence": round(selected["confidence"], 3),
            "plate_box": selected["box"],
            "alternatives": selected["alternatives"],
            "detections": [{"text": d["text"], "confidence": round(d["confidence"], 3),
                            "box": [round(v) for v in d["box"]]} for d in detections],
            "image_size": list(img.size),
        }
    raise OCRUnavailable("; ".join(errors))
