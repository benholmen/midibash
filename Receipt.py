from PIL import Image, ImageDraw
import barcode
from barcode.writer import ImageWriter as BarcodeWriter
import io
import sys
import time
import numpy
from escpos.printer import Serial as ReceiptSerial

class Receipt:

    mid_radius = 30
    min_note = 48
    max_note = 84
    width = 576
    height = 2208
    notes = []
    _barcode = None

    def __init__(self, text):
        self.text = text

        self._generate_barcode(str(text))

    def _generate_barcode(self, text) -> None:
        barcode_options = {
            "write_text": False,
            "quiet_zone": 0,
            "font_size": 0,
            "module_width": 2.0,
            "module_height": 20.0,
            "margin_top": 0,
            "margin_bottom": 0,
            "text_distance": 0,
        }

        buffer = io.BytesIO()
        code128 = barcode.get("code128", text, writer=BarcodeWriter())
        code128.write(buffer, options=barcode_options)

        barcode_img = Image.open(buffer).convert("RGBA")

        self._barcode = Image.new("RGB", (self.width, self.height), (255, 255, 255))

        draw = ImageDraw.Draw(self._barcode)

        # transform a trapezoid of the barcode
        (barcode_width, barcode_height) = barcode_img.size
        src_coords = [
            (0, 0),
            (barcode_width, 0),
            (barcode_width, barcode_height),
            (0, barcode_height),
        ]
        dest_coords = [
            (self.width / 2.2, 0),
            (self.width - self.width / 2.2, 0),
            (self.width, self.height / 2),
            (0, self.height / 2),
        ]
        trapezoid = barcode_img.transform(
            (self.width, int(self.height / 2)),
            Image.PERSPECTIVE,
            self._find_coeffs(dest_coords, src_coords),
            Image.NEAREST,
        )

        # leading and trailing trapezoid
        self._barcode.paste(trapezoid, (0, 0), trapezoid)
        self._barcode.paste(
            trapezoid.transpose(Image.FLIP_TOP_BOTTOM),
            (0, int(self.height / 2), self.width, self.height),
            trapezoid.transpose(Image.FLIP_TOP_BOTTOM),
        )


    def _find_coeffs(self, pa, pb):
        matrix = []
        for p1, p2 in zip(pa, pb):
            matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0] * p1[0], -p2[0] * p1[1]])
            matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1] * p1[0], -p2[1] * p1[1]])

        A = numpy.matrix(matrix, dtype=float)
        B = numpy.array(pb).reshape(8)

        res = numpy.dot(numpy.linalg.inv(A.T * A) * A.T, B)
        return numpy.array(res).reshape(8)

    def save(self) -> None:
        self._barcode.save("receipts/no-notes.png")
