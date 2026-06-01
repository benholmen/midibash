#!/usr/bin/env python3
from gpiozero import Button
import mido
from mido import MidiFile
from pathlib import Path
import os
import pigpio
import random
import serial as ScannerSerial
import signal
import sys
import threading
import time
import Receipt

# https://learn.adafruit.com/adafruit-i2c-to-8-channel-solenoid-driver/circuitpython-and-python
import board
from adafruit_mcp230xx.mcp23017 import MCP23017

SCANNER_PORT = "/dev/ttyACM0"
INSTRUMENT_NAME = "LPK25 mk2"
PRINTER_PORT = "/dev/ttyUSB0"
PRINTER_BAUD = 115200
PRINTER_MAX_WIDTH = 512
PRINTER_MAX_HEIGHT = 400  # vertical chunk size
BUTTON_GPIO = 17  # BCM pin wired button-to-GND
BUTTON_DEBOUNCE_TIME = 50_000  # µsec
BUTTON_COOLDOWN_TIME = 5.0  # sec
RECORDINGS_PATH = "recordings/"

# midi note -> i2c pin mapping; see https://audiodev.blog/midi-note-chart/
pin_mapping = {
    57: 1,  # A3
    60: 0,  # C4
    65: 2,  # F4
    69: 3,  # A4
}

active_solenoids = {}
pins = {}
button_record = None
recording = False
midi_port = None
midi_file = None
midi_track = None
last_time = None
receipt = None


def main():
    global receipt

    # tmp: init the receipt and save it
    start = time.perf_counter()
    receipt = Receipt.Receipt(next_id())
    # receipt.save()

    elapsed = (time.perf_counter() - start) * 1000 # Convert to milliseconds
    print(f"init:   {elapsed:.3f} ms")

    for x in range(10):
        receipt.add_note(
            mido.Message('note_on', note=random.randint(48, 84), velocity=random.randint(20, 127), time=x * 7)
        )
        elapsed = (time.perf_counter() - start) * 1000 # Convert to milliseconds
        print(f"note {x}: {elapsed:.3f} ms")
    receipt.save()

    for n in range(0, 2):
        chunk = receipt.chunk(n)
        chunk.save(f"receipts/{n}.png")

    elapsed = (time.perf_counter() - start) * 1000 # Convert to milliseconds
    print(f"save:   {elapsed:.3f} ms")

    exit(0)

    print("\033[90m", "initializing button", "\033[0m")
    button_handler = init_button()

    print("\033[90m", "initializing keyboard", "\033[0m")
    init_keyboard()

    print("\033[90m", "initializing pins", "\033[0m")
    init_pins()

    print("\033[90m", "initializing barcode scanner", "\033[0m")
    init_barcode_scanner()

    print("\033[93m", "… waiting for scans + midi …", "\033[0m")

    try:
        while True:
            # turn off any solenoids that have expired
            turn_off_solenoids()

            advance_receipt()

            # sleep for 1 ms
            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n\033[1;31mCleaning up\033[0m")

        button_handler.cancel()

        if recording:
            end_recording()

        turn_off_solenoids(force=True)


def handle_midi_msg(msg) -> None:
    global recording

    print("\t\033[90m", msg, "\033[0m")

    if recording:
        record_note(msg)

    if msg.type == "note_on":
        print("\t\033[90m", msg, "\033[0m")

        pin = pin_for(msg.note)

        if pin is not None:
            start_note(msg.note, duration_for(msg.velocity))


def pin_for(note: int) -> int:
    if note in pin_mapping:
        return pin_mapping.get(note)

    return None


def duration_for(velocity: int) -> int:
    # velocity is 1-128; we clamp it a sensible range
    # this will be the duration we activate the solenoid, in milliseconds
    min = 7
    max = 30

    return round(velocity / 128 * (max - min)) + min


def start_note(note: int, duration_ms: int) -> None:
    global active_solenoids, pins

    # todo: refactor this so we can limit the number of active solenoids at once, e.g.
    # active_solenoids[] = {
    #     note: note,
    #     end_at: time.time() + duration_ms / 1000
    # }
    # if count(active_solenoids > limit):
    #     unset the oldest note

    active_solenoids[note] = time.time() + duration_ms / 1000

    pins[note].value = True


def end_note(note: int) -> None:
    global active_solenoids, pins

    del active_solenoids[note]
    pins[note].value = False


def init_button() -> None:
    pi = pigpio.pi()

    if not pi.connected:
        print("Cannot connect to pigpiod — run: sudo pigpiod", file=sys.stderr)
        sys.exit(1)

    return ButtonHandler(pi, toggle_recording)


def init_keyboard() -> None:
    global INSTRUMENT_NAME, midi_port

    while midi_port is None:
        for input_name in mido.get_input_names():
            if INSTRUMENT_NAME in input_name:
                midi_port = mido.open_input(input_name, callback=handle_midi_msg)

                print(f"Using {input_name}")

        if midi_port is None:
            sys.stdout.write(
                f" Available inputs: "
                + ", ".join(mido.get_input_names()).ljust(40, " ")
                + "\r"
            )

            time.sleep(0.5)


def init_pins() -> None:
    global pin_mapping, pins

    try:
        i2c = board.I2C()
        mcp = MCP23017(i2c, address=0x20)
        print("Using MCP23017 0x20")
    except Exception as e:
        print(f"Could not connect to MCP23017: {e}")
        exit()

    for midi_note, pin in pin_mapping.items():
        print(f"midi {midi_note} → pin {pin}")
        i2c_pin = mcp.get_pin(pin)
        i2c_pin.switch_to_output(value=False)
        pins[midi_note] = i2c_pin


def init_barcode_scanner() -> None:
    scanner_serial = ScannerSerial.Serial(SCANNER_PORT, timeout=0)
    thread = threading.Thread(
        target=barcode_scanner_thread, args=(scanner_serial,), daemon=True
    )
    thread.start()


def barcode_scanner_thread(serial) -> None:
    buffer = ""

    while True:
        try:
            if serial.in_waiting > 0:
                data = serial.read(serial.in_waiting).decode("utf-8")

                for char in data:
                    if char == "\n" or char == "\r":
                        if buffer:
                            # todo: play a midi file if the scanner got something
                            print("\t\033[90m", f"scanned {buffer}", "\033[0m")
                            buffer = ""
                    else:
                        buffer += char

            time.sleep(0.01)
        except Exception as e:
            print(f"Scanner thread error: {e}")
            time.sleep(1)


def turn_off_solenoids(force: bool = False) -> None:
    global active_solenoids

    now = time.time()
    for note in list(active_solenoids.keys()):
        if force or now >= active_solenoids[note]:
            end_note(note)


def toggle_recording():
    global recording

    if recording:
        end_recording()
    else:
        start_recording()


def start_recording():
    global midi_file, midi_track, recording, last_time

    print("\033[1;31m⏺︎ recording...\033[0m")
    midi_file = MidiFile()
    midi_track = midi_file.add_track("Ben")
    recording = True
    last_time = None


def record_note(msg) -> None:
    global last_time, midi_file, midi_track

    now = time.time()

    # The very first note should be at time 0
    # eliminate delay between recording start
    # and first key press
    if last_time is None:
        last_time = now

    msg.time = int(mido.second2tick(now - last_time, midi_file.ticks_per_beat, 500000))
    last_time = now
    midi_track.append(msg)

    receipt.add_note(msg)


def end_recording():
    global midi_file, midi_track, recording

    print("\033[1;31m⏹︎ done recording\033[0m")
    if len(midi_track) > 0:
        Path("recordings").mkdir(exist_ok=True)
        midi_file.save("recordings/output.mid")
    else:
        print("Track is empty, skipping.")

    recording = False


def start_receipt() -> None:
    # todo: print the first chunk of the receipt with no notes
    # todo: thread this if possible
    return None


def advance_receipt() -> None:
    # if recording, and we have advanced the correct amount of time, print a chunk of receipt
    # todo: thread this if possible
    return None


def finish_receipt() -> None:
    # todo: print the remaining part of the receipt
    # todo: thread this if possible
    # todo: generate the NEXT barcode template
    return None


def next_id(default=1000):
    global RECORDINGS_PATH

    try:
        return (
            max(
                int(f.name[:-4])
                for f in os.scandir(RECORDINGS_PATH)
                if f.is_file() and f.name.endswith(".mid") and f.name[:-4].isdigit()
            )
            + 1
        )
    except ValueError:
        return default


class ButtonHandler:
    global BUTTON_COOLDOWN_TIME, BUTTON_DEBOUNCE_TIME, BUTTON_GPIO

    def __init__(self, pi, callback):
        self.pi = pi
        self.callback = callback
        self._last_press = 0.0

        pi.set_mode(BUTTON_GPIO, pigpio.INPUT)
        pi.set_pull_up_down(BUTTON_GPIO, pigpio.PUD_UP)
        pi.set_glitch_filter(BUTTON_GPIO, BUTTON_DEBOUNCE_TIME)

        self._cb = pi.callback(BUTTON_GPIO, pigpio.FALLING_EDGE, self._on_press)

    def _on_press(self, gpio, level, tick):
        now = time.monotonic()
        if (now - self._last_press) < BUTTON_COOLDOWN_TIME:
            remaining_seconds = BUTTON_COOLDOWN_TIME - (now - self._last_press)
            print(f"[WARN] In cooldown period, {remaining_seconds:.1f}s remain")
            return
        self._last_press = now

        self.callback()

    def cancel(self):
        self._cb.cancel()
        self.pi.stop()


if __name__ == "__main__":
    main()
