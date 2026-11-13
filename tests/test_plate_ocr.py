"""
Plate-text selection from OCR detections (matching/ocr.py).

The fixtures are the detections RapidOCR returned for real photos that the old
single-line OCR could not read: a full car photo, a watermarked stock image, a
two-box plate, and foreign plates with state names / "TAXI" / "TEMP PLATE" around
them. Recorded detections keep these tests independent of any OCR engine.
"""
import pytest

from matching import ocr
from matching.ocr import select_plate_text


def _dets(rows):
    return [{"text": t, "confidence": c, "box": b} for t, c, b in rows]


REAL_PHOTO_DETECTIONS = {
    "full car photo, badge + dealer sticker + site watermark": (_dets([
        ("Ford", 0.73, [478, 93, 578, 133]),
        ("MH12DE1433", 0.99, [195, 288, 870, 413]),
        ("Planet Foro", 0.9, [847, 616, 1023, 660]),
        ("Team-", 0.99, [2, 737, 78, 759]),
        ("BHP.com", 0.86, [72, 735, 192, 758]),
    ]), "MH12DE1433"),
    "stock image: plate split in two boxes, watermark on the same row": (_dets([
        ("shutterstc", 0.98, [952, 0, 1189, 191]),
        ("DL", 0.99, [212, 267, 533, 487]),
        ("1A B2345", 0.97, [475, 260, 1329, 494]),
        ("IND", 0.98, [115, 350, 219, 405]),
        ("shuttersto", 0.88, [1290, 289, 1499, 484]),
        ("hutterstck'", 0.96, [301, 559, 542, 770]),
        ("hutterstck", 1.0, [974, 558, 1214, 768]),
        ("shutterstock", 0.94, [55, 777, 346, 823]),
        ("IMAGEID:2093983801", 0.99, [1264, 779, 1452, 799]),
        ("www.shutterstock.com", 0.99, [1292, 811, 1453, 827]),
    ]), "DL1AB2345"),
    "foreign plate with country code": (_dets([
        ("00-AA-000", 0.97, [94, 44, 594, 166]),
        ("AZ", 0.98, [49, 105, 103, 143]),
    ]), "00AA000"),
    "temporary plate": (_dets([("191TPV", 0.98, [0, 278, 1488, 847])]), "191TPV"),
    "state name above, TAXI below": (_dets([
        ("NEWYORK", 1.0, [156, 35, 432, 74]),
        ("11455-TY", 0.97, [37, 64, 546, 256]),
        ("TAXI", 0.99, [250, 235, 339, 266]),
    ]), "11455TY"),
}


@pytest.mark.parametrize("case", list(REAL_PHOTO_DETECTIONS))
def test_selects_plate_from_real_photo_detections(case):
    detections, expected = REAL_PHOTO_DETECTIONS[case]
    selected = select_plate_text(detections)
    assert ocr._normalize(selected["text"]) == expected
    assert selected["box"] is not None


def test_prefers_whole_row_over_fragments():
    detections = _dets([("DL", 0.99, [90, 40, 200, 120]), ("01", 0.99, [215, 40, 320, 120]),
                        ("AB", 0.99, [345, 40, 460, 120]), ("1001", 0.99, [480, 40, 690, 120]),
                        ("IND", 0.99, [20, 105, 55, 125])])
    selected = select_plate_text(detections)
    assert ocr._normalize(selected["text"]) == "DL01AB1001"
    assert {"01AB1001", "AB1001"} & {a["normalized"] for a in selected["alternatives"]}


@pytest.mark.parametrize("middle, expected", [("1a", "DL1AB2345"), ("lA", "DLLAB2345")])
def test_tesseract_style_tokens_keep_whole_plate(middle, expected):
    """Browser Tesseract read 'DL 1A B2345' as DL / 1a-or-lA / B2345 plus the border as '|'."""
    detections = _dets([("DL", 0.88, [245, 290, 520, 470]), (middle, 0.55, [560, 292, 730, 468]),
                        ("B2345", 0.93, [760, 288, 1310, 472]), ("|", 0.40, [1330, 280, 1350, 480])])
    selected = select_plate_text(detections)
    assert ocr._normalize(selected["text"]) == expected     # "lA" -> "LA" is fixed later by OCR-aware matching
    assert "|" not in selected["text"]


def test_overlapping_boxes_do_not_duplicate_characters():
    detections = _dets([("MH", 0.99, [94, 45, 234, 122]), ("12", 1.0, [218, 43, 369, 123]),
                        ("2 XY 4821", 0.94, [322, 41, 688, 128])])
    assert ocr._normalize(select_plate_text(detections)["text"]) == "MH12XY4821"


def test_stacked_two_row_plate():
    detections = _dets([("KA 05", 0.95, [100, 40, 400, 140]), ("MX 2481", 0.95, [80, 170, 430, 270])])
    assert ocr._normalize(select_plate_text(detections)["text"]) == "KA05MX2481"


def test_no_plate_like_text():
    detections = _dets([("Ford", 0.9, [0, 0, 100, 40]), ("shutterstock", 0.9, [0, 50, 300, 90]),
                        ("TAXI", 0.9, [0, 100, 80, 130])])
    selected = select_plate_text(detections)
    assert selected["text"] == "" and selected["box"] is None
    assert select_plate_text([])["text"] == ""


def test_broken_engine_import_is_not_reported_available(monkeypatch):
    """A native wheel that crashes on import must be skipped, not loaded into the Mediator."""
    import importlib.util
    monkeypatch.setattr(ocr, "_probe_cache", {"rapidocr_onnxruntime": False, "easyocr": False, "pytesseract": False})
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert ocr.available_engines() == []
    with pytest.raises(ocr.OCRUnavailable):
        ocr.extract_plate_text(b"not used")


@pytest.mark.skipif("rapidocr" not in ocr.available_engines(), reason="rapidocr_onnxruntime not installed")
@pytest.mark.parametrize("sample, expected", [
    ("plate_clean_DL01AB1001.png", "DL01AB1001"),
    ("plate_skewed_DL01AB1234.png", "DL01AB1234"),
    ("plate_unregistered_MH12XY4821.png", "MH12XY4821"),
])
def test_rapidocr_end_to_end_on_samples(sample, expected):
    with open(f"frontend/assets/samples/{sample}", "rb") as f:
        result = ocr.extract_plate_text(f.read())
    assert result["engine"] == "rapidocr"
    assert ocr._normalize(result["raw_text"]) == expected


def test_whole_plate_beats_a_plate_shaped_fragment():
    # real photo "DL 7C D 1939": OCR reads the D as 0, so "DL7C0" alone also looks like a plate
    from matching.ocr import select_plate_text
    dets = [{"text": "DL7C0", "confidence": 0.9, "box": [100, 100, 200, 140]},
            {"text": "1939", "confidence": 0.9, "box": [205, 100, 280, 140]},
            {"text": "2093983801", "confidence": 0.9, "box": [100, 200, 200, 210]}]   # stock-photo id, small text
    assert select_plate_text(dets)["text"] == "DL7C0 1939"
