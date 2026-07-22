from PIL import Image, ImageDraw
import barcode
from barcode.writer import ImageWriter as BarcodeWriter
import io
import math
import mido
import numpy
import queue
import threading
from escpos.printer import Serial
from escpos import constants


class Receipt:
    # 203 dpi / 8 dpmm

    note_radius = 30
    note_stroke = 3
    min_note = 60
    max_note = 96
    width = 512
    height = 2400  # 11.8 inches
    chunk_height = 200
    x_padding = note_radius
    y_padding = chunk_height
    left_padding = 38  # centers the receipt - determined experimentally
    mm_per_second = height / 60
    serial_port = "/dev/ttyUSB0"
    baud_rate = 115200

    notes = []
    pending_notes = []
    _next_chunk = 1
    _barcode = None
    _image = None
    _draw = None
    _print = None
    _cut_on_last_chunk = False
    _printing = False

    def __init__(self, text, print = True):
        self.text = text

        self._print = print

        self._generate_barcode(str(text))

        self._image = self._barcode.copy()
        self._draw = ImageDraw.Draw(self._image)

        self.printer = Serial(self.serial_port, baudrate=self.baud_rate, profile="TM-T88IV")

        self.render_queue = queue.Queue()

        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

    def start(self):
        # print the first chunk
        self._printing = True
        self.render_queue.put(0)

    def finish(self) -> None:
        self._cut_on_last_chunk = True

        # render any outstanding chunks
        while (self._next_chunk + 1) * self.chunk_height <= self.height:
            print(f"queuing {self._next_chunk}")
            self.render_queue.put(self._next_chunk)

            self._next_chunk += 1

    def add_note(self, note, absolute_time) -> None:
        self.notes.append([absolute_time, note])
        self.pending_notes.append([absolute_time, note])

        x, y = self._coords(note, absolute_time)

        print(f"+ added {note.note} at {absolute_time}s at {x}, {y}")

        if (
            y
            > (self._next_chunk + 1) * self.chunk_height
            + self.note_radius
            + self.note_stroke
        ):
            self.render_queue.put(self._next_chunk)

            self._next_chunk += 1

    def _process_queue(self):
        while True:
            # .get() blocks and waits here until something is added to the queue
            n = self.render_queue.get()
            print(f"rendering {n}")
            self._render_chunk(n)
            self.render_queue.task_done()

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

        code128 = barcode.get("code128", text, writer=BarcodeWriter())
        barcode_img = code128.render(writer_options=barcode_options).convert("1")

        self._barcode = Image.new("1", (self.width, self.height), 1)

        # transform a trapezoid of the barcode
        (barcode_width, barcode_height) = barcode_img.size
        src_coords = [
            (0, 0),
            (barcode_width, 0),
            (barcode_width, barcode_height),
            (0, barcode_height),
        ]
        dest_coords = [
            (self.left_padding + (self.width - self.left_padding) / 2.2, 0),
            (self.width - (self.width - self.left_padding) / 2.2, 0),
            (self.width, self.height / 2),
            (self.left_padding, self.height / 2),
        ]
        trapezoid = barcode_img.transform(
            (self.width, int(self.height / 2)),
            Image.PERSPECTIVE,
            self._find_coeffs(dest_coords, src_coords),
            Image.NEAREST,
            fillcolor=1,
        )

        # leading and trailing trapezoid
        self._barcode.paste(trapezoid, (0, 0))
        self._barcode.paste(
            trapezoid.transpose(Image.FLIP_TOP_BOTTOM),
            (0, int(self.height / 2), self.width, self.height),
        )

    def _find_coeffs(self, pa, pb) -> numpy.ndarray:
        matrix = []
        for p1, p2 in zip(pa, pb):
            matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0] * p1[0], -p2[0] * p1[1]])
            matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1] * p1[0], -p2[1] * p1[1]])

        A = numpy.matrix(matrix, dtype=float)
        B = numpy.array(pb).reshape(8)

        res = numpy.dot(numpy.linalg.inv(A.T * A) * A.T, B)
        return numpy.array(res).reshape(8)

    def expand(self) -> None:
        expanded = Image.new("1", (self.width, self.height + self._barcode.height), 1)
        expanded.paste(self._image, (0, 0))
        expanded.paste(self._barcode, (0, self.height))

        self._image = expanded
        self.height = expanded.height
        self._draw = ImageDraw.Draw(self._image)  # todo: is this necessary?

    def draw_note(self, note, absolute_time) -> None:
        x, y = self._coords(note, absolute_time)

        print(f"✒︎ drawing {note.note} at {absolute_time}s at {x}, {y}")

        if y > self.height:
            print("expanding")
            self.expand()

        # velocity is 0-127; radius should be proportional to velocity
        radius = (note.velocity / 127) * self.note_radius
        self._draw.circle((x, y), radius, 1, 0, self.note_stroke)

    def _render_chunk(self, n) -> None:
        # draw every note in the queue before returning a chunk
        while self.pending_notes:
            absolute_time, note = self.pending_notes.pop()
            self.draw_note(note, absolute_time)

        try:
            box = (0, n * self.chunk_height, self.width, (n + 1) * self.chunk_height)

            chunk = self._image.crop(box)

            if self._print is True:
                self.printer.image(chunk, impl="graphics")
            else:
                chunk.save(f"receipts/{self.text}-{n}.png")
        except ValueError:
            print("Could not return crop outside of bounds")

        if self._cut_on_last_chunk and (n + 1) * self.chunk_height >= self.height:
            print("Last chunk, cutting + saving")
            self.cut()
            self.save()
            self._printing = False

    def cut(self) -> None:
        if self._print is True:
            self.printer.cut()

    def save(self) -> None:
        self._image.save(f"receipts/{self.text}.png")

    def estimate_length(self, length) -> float:
        _, y = self._coords(50, length)
        height_in_inches = (math.ceil(y / 2400) * 2400) / 203

        return (height_in_inches + 2) / 12

    def is_printing(self) -> bool:
        return self._printing

    def _coords(self, note: int | mido.Message, absolute_time: float) -> tuple[float, float]:
        note_num = note if isinstance(note, int) else note.note

        x = (note_num - self.min_note) / (self.max_note - self.min_note) * (
            self.width - self.x_padding * 2 - self.left_padding
        ) + self.x_padding + self.left_padding
        y = absolute_time * self.mm_per_second + self.y_padding + self.note_radius + self.note_stroke

        return x, y
