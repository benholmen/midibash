#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "python-escpos>=3.0",
#   "pillow>=12.1.0",
# ]
# ///
"""
Print an image full-width on the Epson TM-H6000IV receipt printer and auto-cut.

Usage:
    uv run receipt-wip.py <image_file>

Connects via serial (USB-to-RS232 adapter). Printer baud rate set via DIP Switch 1.
"""

import argparse
import sys
from PIL import Image
from escpos.printer import Serial
from escpos import constants

PRINTER_WIDTH = 576  # dots — 80mm paper at 203 DPI
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 9600


def check_paper(printer) -> None:
    # DLE EOT 4 — paper roll sensor status
    # Bits 2-3: 00 = paper OK, 11 = paper near end
    try:
        status = printer.query_status(constants.RT_STATUS_PAPER)
        paper_low = bool(status[0] & 0x0C)
        if paper_low:
            print("DEBUG: paper supply is low — replace roll soon")
        else:
            print("DEBUG: paper level OK")
    except Exception as e:
        print(f"DEBUG: could not read paper status: {e}")


def load_and_scale(path: str) -> Image.Image:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    new_h = int(h * PRINTER_WIDTH / w)
    return img.resize((PRINTER_WIDTH, new_h), Image.LANCZOS)


def main():
    parser = argparse.ArgumentParser(
        description="Print an image full-width on the Epson TM-H6000IV"
    )
    parser.add_argument("image", help="Path to the image file to print")
    args = parser.parse_args()

    img = load_and_scale(args.image)

    try:
        printer = Serial(SERIAL_PORT, baudrate=BAUD_RATE)
    except Exception as e:
        print(f"Could not connect to printer: {e}", file=sys.stderr)
        sys.exit(1)

    check_paper(printer)
    printer.image(img)
    printer.cut()


if __name__ == "__main__":
    main()
