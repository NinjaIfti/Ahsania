"""Writes eval/test-sheet.pdf: a made-up radiology report to print, photograph and capture in the app.

Page 1 is typed and filled in (patient ID RC204518); page 2 is the same report left blank to fill in by hand.
Run from the repository root:  uv run --no-project --with reportlab python eval/make_test_sheet.py
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

OUT = Path(__file__).resolve().parent / "test-sheet.pdf"
W, H = A4
LEFT = 20 * mm
RIGHT = W - 20 * mm

FINDINGS = [
    "A 3.2 x 2.4 cm spiculated mass in the right upper lobe.",
    "A 1.1 x 0.9 cm ground-glass nodule in the left lower lobe.",
    "Enlarged right hilar lymph node, 1.4 cm.",
    "Small left pleural effusion.",
    "The lesion has increased in size since the previous study.",
]
IMPRESSION = "Suspicious for primary lung malignancy."


def header(c: Canvas, reg_no: str | None) -> float:
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(W / 2, H - 22 * mm, "AHSANIA MISSION CANCER & GENERAL HOSPITAL")
    c.setFont("Helvetica", 10)
    c.drawCentredString(W / 2, H - 28 * mm, "Department of Radiology & Imaging  ·  SYNTHETIC TEST DOCUMENT — NOT A REAL PATIENT")
    c.setLineWidth(1)
    c.line(LEFT, H - 32 * mm, RIGHT, H - 32 * mm)
    y = H - 42 * mm
    c.setFont("Helvetica", 12)
    if reg_no:
        rows = [("Patient Name:", "Test Patient One"), ("Reg No:", reg_no), ("Age / Sex:", "56 / M")]
        for label, value in rows:
            c.drawString(LEFT, y, label)
            c.setFont("Helvetica-Bold", 12)
            c.drawString(LEFT + 35 * mm, y, value)
            c.setFont("Helvetica", 12)
            y -= 8 * mm
    else:
        for label in ("Patient Name:", "Reg No:", "Age / Sex:"):
            c.drawString(LEFT, y, label)
            c.line(LEFT + 35 * mm, y - 1.5 * mm, LEFT + 120 * mm, y - 1.5 * mm)
            y -= 10 * mm
    c.line(LEFT, y + 2 * mm, RIGHT, y + 2 * mm)
    return y - 8 * mm


def filled(c: Canvas) -> None:
    y = header(c, "RC204518")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(LEFT, y, "CT CHEST WITH CONTRAST")
    y -= 9 * mm
    c.setFont("Helvetica", 12)
    c.drawString(LEFT, y, "Date: 14/08/2026")
    y -= 14 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawString(LEFT, y, "FINDINGS")
    c.setFont("Helvetica", 12)
    for line in FINDINGS:
        y -= 9 * mm
        c.drawString(LEFT, y, line)
    y -= 9 * mm
    c.drawString(LEFT, y, "No distant metastasis seen.")
    y -= 16 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawString(LEFT, y, "IMPRESSION")
    c.setFont("Helvetica", 12)
    y -= 9 * mm
    c.drawString(LEFT, y, IMPRESSION)
    y -= 30 * mm
    c.drawString(RIGHT - 60 * mm, y, "Consultant Radiologist")


def blank(c: Canvas) -> None:
    y = header(c, None)
    c.setFont("Helvetica", 12)
    for label in ("Study (CT / MRI / X-ray / PET-CT):", "Date (DD/MM/YYYY):", "Contrast given (Yes / No):"):
        c.drawString(LEFT, y, label)
        c.line(LEFT + 68 * mm, y - 1.5 * mm, RIGHT, y - 1.5 * mm)
        y -= 11 * mm
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawString(LEFT, y, "FINDINGS")
    c.setFont("Helvetica", 12)
    for _ in range(9):
        y -= 11 * mm
        c.line(LEFT, y, RIGHT, y)
    y -= 14 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawString(LEFT, y, "IMPRESSION")
    for _ in range(3):
        y -= 11 * mm
        c.line(LEFT, y, RIGHT, y)


def main() -> None:
    c = Canvas(str(OUT), pagesize=A4)
    c.setTitle("AMCGH capture test sheet (synthetic)")
    filled(c)
    c.showPage()
    blank(c)
    c.showPage()
    c.save()
    print(OUT)


if __name__ == "__main__":
    main()
