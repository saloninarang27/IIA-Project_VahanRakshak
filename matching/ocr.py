"""
Server-side OCR for registration-plate images.

Engines are optional and probed at runtime, in order:
    1. pytesseract  (pip install pytesseract + the Tesseract binary on PATH)
    2. easyocr      (pip install easyocr)

If neither is installed, extract_plate_text() raises OCRUnavailable and the web UI
falls back to Tesseract.js running in the browser - the raw OCR text then goes
through exactly the same normalisation and matching pipeline.
"""
import io

PLATE_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class OCRUnavailable(RuntimeError):
    pass


def _preprocess(image_bytes):
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img).convert("L")
    if img.width < 600:
        scale = 600 / img.width
        img = img.resize((600, max(1, int(img.height * scale))), Image.LANCZOS)
    return ImageOps.autocontrast(img)


def _tesseract(img):
    import pytesseract

    config = f"--psm 7 -c tessedit_char_whitelist={PLATE_CHARSET}"
    data = pytesseract.image_to_data(img, config=config, output_type=pytesseract.Output.DICT)
    words = [(t, float(c)) for t, c in zip(data["text"], data["conf"]) if t.strip() and float(c) >= 0]
    if not words:
        return "", 0.0
    text = " ".join(t for t, _ in words)
    return text, round(sum(c for _, c in words) / len(words) / 100.0, 3)


_easyocr_reader = None


def _easyocr(img):
    global _easyocr_reader
    import easyocr
    import numpy as np

    if _easyocr_reader is None:
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    results = _easyocr_reader.readtext(np.array(img), allowlist=PLATE_CHARSET + " ")
    if not results:
        return "", 0.0
    text = " ".join(r[1] for r in results)
    return text, round(sum(r[2] for r in results) / len(results), 3)


_ENGINES = [("tesseract", "pytesseract", _tesseract), ("easyocr", "easyocr", _easyocr)]


def available_engines():
    import importlib.util
    found = []
    for name, module, _ in _ENGINES:
        if importlib.util.find_spec(module) is None:
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
    """Return {"engine", "raw_text", "confidence"} or raise OCRUnavailable."""
    engines = available_engines()
    if not engines:
        raise OCRUnavailable("No server-side OCR engine installed (pytesseract+Tesseract or easyocr).")
    img = _preprocess(image_bytes)
    errors = []
    for name, _, fn in _ENGINES:
        if name not in engines:
            continue
        try:
            text, confidence = fn(img)
            return {"engine": name, "raw_text": text, "confidence": confidence}
        except Exception as e:  # try the next engine
            errors.append(f"{name}: {e}")
    raise OCRUnavailable("; ".join(errors))
