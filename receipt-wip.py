#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "python-escpos>=3.0",
#   "pillow>=12.1.0",
# ]
# ///
"""
Print an image full-width on the Epson M253A receipt printer and auto-cut.

Usage:
    python receipt-wip.py <image_file>

Before first run, find the printer's USB product ID:
    lsusb | grep -i epson
Then update PRINTER_PRODUCT_ID below.
"""

import argparse
import sys
from PIL import Image
from escpos.printer import Usb
from escpos import constants

PRINTER_WIDTH = 576       # dots — 80mm paper at 203 DPI
EPSON_VENDOR_ID = 0x04B8  # Epson USB vendor ID (constant across models)
PRINTER_PRODUCT_ID = 0x0202  # UB-U05 USB interface card


def check_paper(printer: Usb) -> None:
    # DLE EOT 4 — paper roll sensor status
    # Bits 2-3: 00 = paper OK, 11 = paper near end
    # TODO: verify bit mask against actual printer response
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
        description="Print an image full-width on the Epson M253A"
    )
    parser.add_argument("image", help="Path to the image file to print")
    args = parser.parse_args()

    img = load_and_scale(args.image)

    try:
        printer = Usb(EPSON_VENDOR_ID, PRINTER_PRODUCT_ID)
    except Exception as e:
        print(f"Could not connect to printer: {e}", file=sys.stderr)
        print(
            "Check that the printer is on, plugged in via USB, and that "
            "PRINTER_PRODUCT_ID matches `lsusb` output.",
            file=sys.stderr,
        )
        sys.exit(1)

    check_paper(printer)
    printer.image(img)
    printer.cut()


if __name__ == "__main__":
    main()
