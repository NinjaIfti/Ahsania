"""Writes the synthetic golden set: made-up documents with known values (spec §11.3). No real patient appears.

Run from the repository root:  uv run --no-project --with pillow python eval/make_golden.py
The values come from a fixed random seed, so re-running it writes the same documents and expected values.
"""

import json
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GOLDEN = Path(__file__).resolve().parent / "golden"
SEED = 2026
LOBES = {
    "RUL": "right upper lobe",
    "RML": "right middle lobe",
    "RLL": "right lower lobe",
    "LUL": "left upper lobe",
    "LLL": "left lower lobe",
}
DESCRIPTIONS = ["spiculated mass", "ground-glass nodule", "cavitating lesion", "part-solid nodule", "lobulated mass"]
IMPRESSIONS = [
    "Suspicious for primary lung malignancy.",
    "Findings likely represent primary bronchogenic carcinoma.",
    "Stable appearance compared with the previous study.",
    "Interval progression of the known pulmonary lesion.",
]
CHANGES = {
    "new": "This lesion is new compared with the previous study.",
    "increased": "The lesion has increased in size since the previous study.",
    "decreased": "The lesion has decreased in size since the previous study.",
    "stable": "The lesion is stable compared with the previous study.",
}
EFFUSION_TEXT = {
    "none": "No pleural effusion.",
    "left": "Small left pleural effusion.",
    "right": "Moderate right pleural effusion.",
    "bilateral": "Bilateral pleural effusions.",
}


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def write_case(template: str, number: int, image: Image.Image, values: dict, ignore: list[str] | None = None) -> None:
    folder = GOLDEN / template / f"case-{number:02d}"
    folder.mkdir(parents=True)
    image.save(folder / "page-1.jpg", quality=85)
    expected = {"style": "typed", "values": values, "ignore": ignore or []}
    (folder / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")


def redacted_header(draw: ImageDraw.ImageDraw, y: int) -> int:
    """Hospital header with the identifier lines already blacked out, as the worker receives them."""
    draw.text((80, y), "AHSANIA MISSION CANCER & GENERAL HOSPITAL (SYNTHETIC)", fill="black", font=font(34))
    for label in ("Patient Name:", "Reg No:", "Mobile:"):
        y += 60
        draw.text((80, y), label, fill="black", font=font(30))
        draw.rectangle((330, y - 6, 900, y + 40), fill="black")
    return y + 90


def radiology(rng: random.Random, number: int) -> None:
    modality = rng.choice(["CT", "CT", "MRI", "X-ray", "PET-CT"])
    study = date(2025, 1, 1) + timedelta(days=rng.randrange(600))
    contrast = rng.choice([True, False, None]) if modality in ("CT", "MRI") else None
    title = {"CT": "CT CHEST", "MRI": "MRI THORAX", "X-ray": "CHEST X-RAY", "PET-CT": "PET-CT WHOLE BODY"}[modality]
    if contrast is True:
        title += " WITH CONTRAST"
    elif contrast is False:
        title += " WITHOUT CONTRAST"
    lesions = []
    findings = []
    for _ in range(rng.randrange(0, 3)):
        lobe = rng.choice(list(LOBES))
        long_axis = round(rng.uniform(0.8, 6.5), 1)
        short_axis = round(rng.uniform(0.5, long_axis), 1)
        description = rng.choice(DESCRIPTIONS)
        if rng.random() < 0.3:
            size = f"{round(long_axis * 10)} x {round(short_axis * 10)} mm"
        else:
            size = f"{long_axis} x {short_axis} cm"
        findings.append(f"A {size} {description} in the {LOBES[lobe]}.")
        lesions.append({"lobe": lobe, "long_axis_cm": long_axis, "short_axis_cm": short_axis, "description": description})
    effusion = rng.choice(list(EFFUSION_TEXT))
    findings.append(EFFUSION_TEXT[effusion])
    change = rng.choice([None, *CHANGES]) if lesions else None
    if change:
        findings.append(CHANGES[change])
    nodes = rng.choice([None, "Enlarged right hilar lymph node, 1.4 cm.", "Subcarinal lymphadenopathy."])
    if nodes:
        findings.append(nodes)
    impression = rng.choice(IMPRESSIONS)

    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    y = redacted_header(draw, 70)
    draw.text((80, y), title, fill="black", font=font(38))
    y += 70
    draw.text((80, y), f"Date: {study:%d/%m/%Y}", fill="black", font=font(30))
    y += 80
    draw.text((80, y), "FINDINGS", fill="black", font=font(32))
    for line in findings:
        y += 55
        draw.text((80, y), line, fill="black", font=font(28))
    y += 90
    draw.text((80, y), f"Impression: {impression}", fill="black", font=font(28))

    values = {
        "modality": modality,
        "study_date": study.isoformat(),
        "contrast": contrast,
        "lesions": lesions,
        "lymph_nodes": nodes,
        "metastasis_sites": None,
        "pleural_effusion": effusion,
        "reported_change": change,
        "impression": impression,
    }
    write_case("radiology_report", number, image, values)


def film_canvas(rng: random.Random) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    shade = rng.randrange(10, 40)
    image = Image.new("RGB", (1200, 1500), (shade, shade, shade))
    draw = ImageDraw.Draw(image)
    draw.ellipse((220, 300, 980, 1300), fill=(shade + 70,) * 3)
    return image, draw


def xray(rng: random.Random, number: int) -> None:
    study = date(2025, 1, 1) + timedelta(days=rng.randrange(600))
    view, view_text = rng.choice([("PA", "PA"), ("AP", "AP"), ("lateral", "LAT")])
    side = rng.choice(["L", "R"])
    image, draw = film_canvas(rng)
    draw.text((40, 40), "AMCGH RADIOLOGY (SYNTHETIC)", fill="white", font=font(36))
    draw.text((40, 95), f"{study:%d-%m-%Y}", fill="white", font=font(36))
    draw.text((1000, 40), view_text, fill="white", font=font(48))
    draw.text((1060 if side == "R" else 60, 700), side, fill="white", font=font(90))
    values = {"study_date": study.isoformat(), "view": view, "side_marker": side, "capture_source": None}
    write_case("xray_film_photo", number, image, values, ignore=["capture_source"])


def ct_film(rng: random.Random, number: int) -> None:
    study = date(2025, 1, 1) + timedelta(days=rng.randrange(600))
    modality = rng.choice(["CT", "MRI"])
    window, window_text = rng.choice([("lung", "LUNG WINDOW  W:1500 L:-600"), ("mediastinal", "MEDIASTINAL WINDOW  W:350 L:40")])
    slice_label = f"IM {rng.randrange(10, 200)}"
    image, draw = film_canvas(rng)
    draw.text((40, 40), f"{modality}  {study:%d/%m/%Y}", fill="white", font=font(40))
    draw.text((40, 1380), window_text, fill="white", font=font(34))
    draw.text((900, 1380), slice_label, fill="white", font=font(40))
    values = {"modality": modality, "study_date": study.isoformat(), "window": window, "slice_label": slice_label, "capture_source": None}
    write_case("ct_mri_film_photo", number, image, values, ignore=["capture_source"])


def main() -> None:
    if GOLDEN.exists():
        shutil.rmtree(GOLDEN)
    rng = random.Random(SEED)
    for n in range(1, 13):
        radiology(rng, n)
    for n in range(1, 5):
        xray(rng, n)
    for n in range(1, 5):
        ct_film(rng, n)
    print(f"wrote {sum(1 for _ in GOLDEN.glob('*/*/expected.json'))} cases to {GOLDEN}")


if __name__ == "__main__":
    main()
