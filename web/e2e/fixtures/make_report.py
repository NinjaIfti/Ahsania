"""Writes report.jpg: a made-up radiology report for end-to-end tests (no real patient)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LINES = [
    "AHSANIA MISSION CANCER & GENERAL HOSPITAL (DEMO)",
    "Patient Name: Test Person",
    "Mobile: 01712345678",
    "Reg No: AMH-00123",
    "",
    "CT CHEST REPORT",
    "Date: 01/09/2026",
    "Findings: 2.3 x 1.8 cm spiculated mass in right upper lobe.",
    "Impression: Suspicious for primary lung malignancy.",
]

image = Image.new("RGB", (1800, 1100), "white")
draw = ImageDraw.Draw(image)
font = ImageFont.load_default(size=44)
for i, line in enumerate(LINES):
    draw.text((60, 60 + 100 * i), line, fill="black", font=font)
image.save(Path(__file__).with_name("report.jpg"), quality=92)
