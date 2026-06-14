
import argparse
import sys
from PIL import Image
from escpos.printer import Serial
from escpos import constants

PRINTER_WIDTH = 512  # dots — 80mm paper at 203 DPI
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200
CHUNK_HEIGHT = 200


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

    width, height = img.size
    for top in range(0, height, CHUNK_HEIGHT):
        bottom = min(top + CHUNK_HEIGHT, height)

        box = (0, top, width, bottom)
        chunk = img.crop(box)

        printer.image(chunk)

    printer.cut()


if __name__ == "__main__":
    main()
