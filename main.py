#!/usr/bin/env python3
from collections import deque
import mido
from mido import MidiFile
from pathlib import Path
from prometheus_client import start_http_server, Counter, Gauge
import os
import pigpio
import random
import Receipt
import serial as ScannerSerial
import sys
import threading
import time

# https://learn.adafruit.com/adafruit-i2c-to-8-channel-solenoid-driver/circuitpython-and-python
import board
from adafruit_mcp230xx.mcp23017 import MCP23017

SCANNER_PORT = "/dev/ttyACM0"
KEYBOARD_NAMES = [
    "iRig Keys 2 PRO",
    "LPK25 mk2",
]
BUTTON_GPIO = 23  # BCM pin wired button-to-GND
BUTTON_DEBOUNCE_TIME = 50_000  # µsec
BUTTON_COOLDOWN_TIME = 1.0  # sec
RECORDING_LIGHT_GPIO = 24
RECORDINGS_PATH = "recordings/"
REPLAYS_PATH = "replay/"
IDLE_DELAY = 120

# midi note -> i2c pin mapping; see https://audiodev.blog/midi-note-chart/
# MCP23017 addresses are 0x20, 0x21, 0x22, 0x23, 0x24
pin_mapping = {
    60: (0x21, 0),  # C4
    61: (0x21, 1),
    62: (0x21, 2),
    63: (0x21, 3),
    64: (0x21, 4),
    65: (0x21, 5),
    66: (0x21, 6),
    67: (0x21, 7),
    68: (0x20, 0),
    69: (0x20, 1),
    70: (0x20, 2),
    71: (0x20, 3),
    72: (0x20, 4),  # C5
    73: (0x20, 5),
    74: (0x20, 6),
    75: (0x20, 7),
    76: (0x24, 0),
    77: (0x24, 1),
    78: (0x24, 2),
    79: (0x24, 3),
    80: (0x24, 4),
    81: (0x24, 5),
    82: (0x24, 6),
    83: (0x24, 7),
    84: (0x23, 0),  # C6
    85: (0x23, 1),
    86: (0x23, 2),
    87: (0x23, 3),
    88: (0x23, 4),
    89: (0x23, 5),
    90: (0x23, 6),
    91: (0x23, 7),
    92: (0x22, 0),
    93: (0x22, 1),
    94: (0x22, 2),
    95: (0x22, 3),
    96: (0x22, 4),  # C7
}

active_solenoids = {}
pins = {}
button_record = None
recording = False
midi_ports = {}
midi_file = None
midi_track = None
start_time = None
last_time = None
receipt = None
playing = False
playing_id = None
pi = None
playback_messages = deque()
live_messages = deque()
recording_id = None
last_activity_timestamp = time.time()

# Prometheus
PROMETHEUS_PORT = 8000
KEYS_PRESSED = Counter('keys_pressed', 'Keys pressed', ['note'])
NOTES_PLAYED = Counter('notes_played', 'Notes played', ['note'])
NOTES_RECORDED = Counter('notes_recorded', 'Notes recorded', ['note'])
TRACKS_RECORDED = Counter('tracks_recorded', 'Tracks recorded', ['track_id'])
TRACKS_REPLAYED = Counter('tracks_replayed', 'Tracks replayed', ['track_id'])
RECEIPT_PAPER_PRINTED = Counter('receipt_paper_printed', 'Total feet of receipt paper printed')
# LAST_NOTE_TIME = Gauge('last_note_timestamp', 'Time since last note recorded')
PI_TEMP = Gauge('pi_temp', 'CPU Temp')
STATUS = Gauge('status', 'Status')

def main() -> None:
    print("\033[90m", "initializing pins", "\033[0m")
    init_pins()

    print("\033[90m", "initializing button", "\033[0m")
    button_handler = init_button()

    print("\033[90m", "initializing keyboard", "\033[0m")
    init_keyboards()

    print("\033[90m", "initializing barcode scanner", "\033[0m")
    init_barcode_scanner()

    print("\033[90m", "initializing prometheus web server", "\033[0m")
    init_prometheus()

    print("\033[93m", "… waiting for scans + midi …", "\033[0m")

    soft_sweep()

    try:
        while True:
            # turn off any solenoids that have expired
            turn_off_solenoids()

            # play any live notes
            play_live_notes()

            # play any playback notes
            play_playback_notes()

            if time.time() > last_activity_timestamp + IDLE_DELAY:
                if random.random() > 0.2:
                    replay_random()
                else:
                    soft_sweep()

            # sleep for 1 ms
            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n\033[1;31mCleaning up\033[0m")

        button_handler.cancel()

        if recording:
            end_recording()

        turn_off_solenoids(force=True)

        pi.stop()


def handle_midi_msg(message) -> None:
    print("\t\033[90m", message, "\033[0m")

    live_messages.append(message)


def pin_for(note: int) -> tuple:
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
    global last_activity_timestamp

    # todo: refactor this so we can limit the number of active solenoids at once, e.g.
    # active_solenoids[] = {
    #     note: note,
    #     end_at: time.time() + duration_ms / 1000
    # }
    # if count(active_solenoids > limit):
    #     unset the oldest note

    active_solenoids[note] = time.time() + duration_ms / 1000

    pins[note].value = True

    # print(f"playing {note}")

    NOTES_PLAYED.labels(note=str(note)).inc()

    last_activity_timestamp = time.time()


def end_note(note: int) -> None:
    del active_solenoids[note]
    pins[note].value = False


def init_button() -> None:
    pi.set_mode(RECORDING_LIGHT_GPIO, pigpio.OUTPUT)
    pi.write(RECORDING_LIGHT_GPIO, 0)  # turn off by default

    return ButtonHandler(pi, toggle_recording)


def init_keyboards() -> None:
    global midi_ports

    while not midi_ports:
        for input_name in mido.get_input_names():
            for keyboard_name in KEYBOARD_NAMES:
                if keyboard_name in input_name:
                    midi_ports[input_name] = mido.open_input(input_name, callback=handle_midi_msg)

                    print(f"Using 🎹 {input_name}")

        if not midi_ports:
            sys.stdout.write(
                f" Available inputs: "
                + ", ".join(mido.get_input_names()).ljust(40, " ")
                + "\r"
            )

            time.sleep(0.5)


def init_pins() -> None:
    global pi

    mcp_addresses_in_use = {address for _, (address, _) in pin_mapping.items()}

    mcps = {}

    try:
        i2c = board.I2C()

        for address in mcp_addresses_in_use:
            mcps[address] = MCP23017(i2c, address=address)
            print(f"Using MCP23017 {address}")
    except Exception as e:
        print(f"Could not connect to MCP23017 at {address}: {e}")
        exit()

    for midi_note, (address, pin) in pin_mapping.items():
        print(f"midi {midi_note} → pin {address} {pin}")
        i2c_pin = mcps[address].get_pin(pin)
        i2c_pin.switch_to_output(value=False)
        pins[midi_note] = i2c_pin

    try:
        pi = pigpio.pi()

        if not pi.connected:
            print("Cannot connect to pigpiod — run: sudo pigpiod")
            exit()
    except Exception as e:
        print(f"Cannot initialize GPIO: {e}")
        exit()


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
                data = serial.read(serial.in_waiting).decode("utf-8", errors="ignore")

                for char in data:
                    if char in ("\r", "\n"):
                        if buffer.strip():
                            process_barcode_scan(buffer.strip())
                            buffer = ""
                    else:
                        buffer += char
                        last_char_time = time.time()
            elif buffer and (time.time() - last_char_time > 0.1):
                process_barcode_scan(buffer.strip())
                buffer = ""

            time.sleep(0.01)
        except Exception as e:
            print(f"Scanner thread error: {e}")
            buffer = ""
            time.sleep(1)


def process_barcode_scan(scanned: str) -> None:
    global playing_id

    if playing_id == scanned:
        print("\t\033[90m", f"scanned {scanned} but currently playing it", "\033[0m")
    else:
        print("\t\033[90m", f"scanned {scanned}", "\033[0m")
        print(playing_id, scanned)
        start_playing(scanned)


def play_live_notes() -> None:
    global last_activity_timestamp

    now = time.time()
    while live_messages and live_messages[0].time < now:
        message = live_messages.popleft()

        if recording:
            record_note(message)

        if message.type == "note_on":
            KEYS_PRESSED.labels(note=str(message.note)).inc()

            pin = pin_for(message.note)

            if pin is not None:
                start_note(message.note, duration_for(message.velocity))

                last_activity_timestamp = now


def play_playback_notes() -> None:
    now = time.time()
    while playback_messages and playback_messages[0].time < now:
        message = playback_messages.popleft()

        pin = pin_for(message.note)

        if pin is not None:
            start_note(message.note, duration_for(message.velocity))

    if playing and not playback_messages:
        end_playing()


def turn_off_solenoids(force: bool = False) -> None:
    now = time.time()
    for note in list(active_solenoids.keys()):
        if force or now >= active_solenoids[note]:
            end_note(note)


def toggle_recording() -> None:
    if recording:
        end_recording()
    else:
        start_recording()


def start_recording() -> None:
    global midi_file, midi_track, receipt, recording, last_time, recording_id

    if receipt and receipt.is_printing():
        print("\033[1;31mstill printing, ignoring\033[0m")
        return

    turn_on_recording_light()

    print("\033[1;31m⏺︎ recording...\033[0m")

    recording_id = next_id()

    midi_file = MidiFile()
    midi_track = midi_file.add_track("midibash")

    receipt = Receipt.Receipt(recording_id, print = True)
    recording = True
    last_time = None

    receipt.start()


def record_note(message) -> None:
    global last_time, start_time

    now = time.time()

    # The very first note should be at time 0
    # eliminate delay between recording start
    # and first key press
    if last_time is None:
        last_time = now
        start_time = now

    message.time = int(mido.second2tick(now - last_time, midi_file.ticks_per_beat, 500000))
    last_time = now
    midi_track.append(message)

    receipt.add_note(message, absolute_time=now - start_time)

    NOTES_RECORDED.labels(note=str(message.note)).inc()


def end_recording() -> None:
    global recording

    turn_off_recording_light()

    print("\033[1;32m⏹︎ done recording\033[0m")
    if len(midi_track) > 0:
        Path("recordings").mkdir(exist_ok=True)
        midi_file.save(f"recordings/{recording_id}.mid")
    else:
        print("Track is empty, skipping.")

    receipt.finish()

    recording = False

    TRACKS_RECORDED.labels(track_id=str(recording_id)).inc()
    RECEIPT_PAPER_PRINTED.inc(receipt.estimate_length(midi_file.length))

def next_id(default=1000):
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


def turn_on_recording_light() -> None:
    pi.write(RECORDING_LIGHT_GPIO, 1)


def turn_off_recording_light() -> None:
    pi.write(RECORDING_LIGHT_GPIO, 0)


def start_playing(id: str) -> None:
    global playing, playing_id

    filename = f"recordings/{id}.mid"
    if not Path(filename).is_file():
        print(f"\033[1;31m⚠️ {filename} does not exist\033[0m")
        return

    print(f"\033[1;32m▶︎ {filename}\033[0m")

    playback_messages.clear()

    absolute_time = None
    for message in MidiFile(filename):
        if absolute_time:
            absolute_time += message.time
        elif not message.is_meta:
            absolute_time = time.time()

        if message.type == "note_on":
            message.time = absolute_time
            playback_messages.append(message)

    playing = True
    playing_id = id

    TRACKS_REPLAYED.labels(track_id=str(playing_id)).inc()


def end_playing() -> None:
    global playing, playing_id

    playing = False
    playing_id = None


def replay_random() -> None:
    replays = list(Path(REPLAYS_PATH).glob("*.mid"))

    if replays:
        random_replay = random.choice(replays)
        print("\033[93m", f"replaying {random_replay} out of", len(replays), "replay options\033[0m")
        start_playing(random_replay.stem)


def soft_sweep() -> None:
    global last_activity_timestamp

    print("\033[93m", "sweeping", "\033[0m")

    bpm = 72
    period = bpm * 8  # thirty-second notes
    # this is Cmaj + 7
    notes = range(60, 96 + 1)

    params = [
        (1, bpm * 8),
        (10, bpm * 12),
        (20, bpm * 16),
        (40, bpm * 4),
        # (127, bpm * 12),
        (1, bpm * 16)
    ]

    shuffled_notes = random.sample(notes, len(notes))

    message_time = time.time() + 0.5
    for velocity, period in params:
        n = 0
        for note in shuffled_notes:
            message_time = message_time + 60 / period
            message = mido.Message('note_on', note=note, velocity=velocity, time=message_time)
            playback_messages.append(message)
            n = n + 1

    last_activity_timestamp = time.time()


def vamp() -> None:
    global last_activity_timestamp

    print("\033[93m", "vamping!", "\033[0m")

    bpm = 72
    period = bpm * 4  # sixteenth notes
    # this is Cmaj + 7
    notes = [
        60, 64, 67,
        72, 76, 69,
        84, 88, 91, 94, 95, 96,
        72, 76, 69,
        84, 88, 91, 94, 95, 96
    ]

    # shuffled_notes = random.sample(notes, len(notes))

    message_time = time.time() + 0.5
    for note in notes:
        message_time = message_time + 60 / period  # todo: maybe swing this?
        message = mido.Message('note_on', note=note, velocity=random.randint(10, 127), time=message_time)
        playback_messages.append(message)

    last_activity_timestamp = time.time()


def init_prometheus() -> None:
    start_http_server(PROMETHEUS_PORT)


class ButtonHandler:
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


if __name__ == "__main__":
    main()
