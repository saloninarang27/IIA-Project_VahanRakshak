"""
Generate sample registration-plate images for the plate-scan demo.

Run: python scripts/generate_plate_samples.py
Writes PNGs to frontend/assets/samples/. Some samples are deliberately degraded
(blur, skew, noise, stylised glyphs) so OCR produces realistic confusions.
"""
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "assets", "samples")

SAMPLES = [
    # (file name, text printed on the plate, degradation)
    ("plate_clean_DL01AB1001.png", "DL 01 AB 1001", None),
    ("plate_blurred_DL01AB1004.png", "DL 01 AB 1004", "blur"),
    ("plate_stylised_DL01AB1008.png", "DL 01 AB 1OO8", "stylised"),   # letter O used for zero
    ("plate_skewed_DL01AB1234.png", "DL 01 AB 1234", "skew"),
    ("plate_unregistered_MH12XY4821.png", "MH 12 XY 4821", None),
]


def _font(size):
    for path in ("C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def render(text, degradation, seed):
    rng = random.Random(seed)
    w, h = 720, 160
    img = Image.new("RGB", (w, h), (250, 250, 248))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, w - 5, h - 5], radius=14, outline=(20, 20, 20), width=6)
    d.rectangle([14, 14, 70, h - 15], fill=(28, 70, 160))
    d.text((42, h - 40), "IND", font=_font(18), fill=(255, 255, 255), anchor="mm")
    size = 92
    font = _font(size)
    while d.textlength(text, font=font) > w - 130 and size > 30:
        size -= 2
        font = _font(size)
    d.text((80 + (w - 95) // 2, h // 2 + 4), text, font=font, fill=(15, 15, 15), anchor="mm")

    if degradation == "blur":
        img = img.filter(ImageFilter.GaussianBlur(2.2))
    elif degradation == "skew":
        img = img.rotate(-4, resample=Image.BICUBIC, expand=True, fillcolor=(120, 120, 120))
    elif degradation == "stylised":
        img = img.filter(ImageFilter.GaussianBlur(0.8))
    if degradation:
        px = img.load()
        for _ in range(4000):
            x, y = rng.randrange(img.width), rng.randrange(img.height)
            v = rng.randrange(60, 200)
            px[x, y] = (v, v, v)
    return img


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for i, (name, text, degradation) in enumerate(SAMPLES):
        render(text, degradation, seed=i).save(os.path.join(OUT_DIR, name))
        print(f"  wrote {name}")


if __name__ == "__main__":
    main()
