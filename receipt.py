import mido
from mido import MidiFile
from pathlib import Path
from PIL import Image, ImageDraw
import barcode
from barcode.writer import ImageWriter as BarcodeWriter
import io
import sys
import time
import numpy


def main():
    id = "1234"
    notes = []
    track_length = 0
    seconds_since_started = None
    width = 576
    height = 2208
    mid_radius = 30
    min_note = 60
    max_note = 80
    h_padding = 25
    v_padding = 150
    trapezoid_height = int(height / 2)

    for msg in MidiFile("recordings/test.mid"):
        if seconds_since_started is not None:
            seconds_since_started += msg.time
        elif not msg.is_meta:
            seconds_since_started = 0

        if msg.type == "note_on":
            msg.time = seconds_since_started
            track_length = seconds_since_started
            notes.append(msg)

    # Write the barcode and load it with Pillow
    buffer = io.BytesIO()
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
    code128 = barcode.get("code128", id, writer=BarcodeWriter())
    code128.write(buffer, options=barcode_options)
    barcode_img = Image.open(buffer).convert("RGBA")

    code128.write("receipts/barcode.png", options=barcode_options)

    receipt = Image.new("RGB", (width, height), (255, 255, 255))

    draw = ImageDraw.Draw(receipt)

    # transform a trapezoid of the barcode
    (barcode_width, barcode_height) = barcode_img.size
    src_coords = [
        (0, 0),
        (barcode_width, 0),
        (barcode_width, barcode_height),
        (0, barcode_height),
    ]
    dest_coords = [
        (width / 2.2, 0),
        (width - width / 2.2, 0),
        (width, trapezoid_height),
        (0, trapezoid_height),
    ]
    trapezoid = barcode_img.transform(
        (width, trapezoid_height),
        Image.PERSPECTIVE,
        find_coeffs(dest_coords, src_coords),
        Image.NEAREST,
    )

    # leading and trailing trapezoid
    receipt.paste(trapezoid, (0, 0), trapezoid)
    receipt.paste(
        trapezoid.transpose(Image.FLIP_TOP_BOTTOM),
        (0, height - trapezoid_height, width, height),
        trapezoid.transpose(Image.FLIP_TOP_BOTTOM),
    )

    # fixed width barcode between trapezoids
    if trapezoid_height * 2 < height:
        receipt.paste(
            barcode_img.resize((width, height - trapezoid_height * 2), Image.NEAREST),
            (0, trapezoid_height, width, height - trapezoid_height),
        )

    for note in notes:
        x = (note.note - min_note) / (max_note - min_note) * (
            width - h_padding * 2
        ) + h_padding
        y = (
            note.time / track_length * (height - (50 * 2) - v_padding * 2)
            + 50
            + v_padding
        )
        radius = (note.velocity / 127) * mid_radius
        print(note.velocity, note.note, (x, y))
        draw.circle((x, y), radius, (255, 255, 255), (0, 0, 0), 3)

    receipt.save("receipts/test.png")

def find_coeffs(pa, pb):
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0] * p1[0], -p2[0] * p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1] * p1[0], -p2[1] * p1[1]])

    A = numpy.matrix(matrix, dtype=float)
    B = numpy.array(pb).reshape(8)

    res = numpy.dot(numpy.linalg.inv(A.T * A) * A.T, B)
    return numpy.array(res).reshape(8)

if __name__ == "__main__":
    main()
