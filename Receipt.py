from PIL import Image, ImageDraw
import barcode
from barcode.writer import ImageWriter as BarcodeWriter
import io
import sys
import time
import numpy
from escpos.printer import Serial as ReceiptSerial


class Receipt:
    # 203 dpi / 8 dpmm

    mid_radius = 30
    min_note = 48
    max_note = 84
    width = 576
    height = 2400
    chunk_height = 200
    x_padding = mid_radius
    y_padding = chunk_height
    mm_per_second = height / 60

    _barcode = None
    _image = None
    _draw = None

    def __init__(self, text):
        self.text = text

        self._generate_barcode(str(text))

        self._image = self._barcode.copy()
        self._draw = ImageDraw.Draw(self._image)

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

    def expand(self):
        expanded = Image.new("RGB", (self.width, self.height + self._barcode.height), (255, 255, 255))
        expanded.paste(self._image, (0, 0))
        expanded.paste(self._barcode, (0, self.height))

        self._image = expanded
        self.height = expanded.height
        self._draw = ImageDraw.Draw(self._image) # todo: is this necessary?

    def add_note(self, note):
        x = (note.note - self.min_note) / (self.max_note - self.min_note) * (
            self.width - self.x_padding * 2
        ) + self.x_padding
        y = note.time * self.mm_per_second + self.y_padding

        if y > self.height:
            self.expand()

        radius = (note.velocity / 127) * self.mid_radius
        self._draw.circle((x, y), radius, (255, 255, 255), (0, 0, 0), 3)

    def chunk(self, n):
        try:
            box = (
                0,
                n * self.chunk_height,
                self.width,
                (n + 1) * self.chunk_height
            )

            return self._image.crop(box)
        except ValueError:
            print("Could not return crop outside of bounds")

    def save(self) -> None:
        self._image.save(f"receipts/{self.text}.png")
