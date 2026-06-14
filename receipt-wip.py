
import argparse
import sys
from PIL import Image
from escpos.printer import Serial
from escpos import constants

PRINTER_WIDTH = 512  # dots — 80mm paper at 203 DPI
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200


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
    img = Image.open(path).convert("1")
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
    chunk_height = 200
    width, height = img.size
    for top in range(0, height, chunk_height):
        bottom = min(top + chunk_height, height)

        box = (0, top, width, bottom)
        chunk = img.crop(box)

        printer.image(chunk)

    #     yield chunk
    printer.cut()


if __name__ == "__main__":
    main()
