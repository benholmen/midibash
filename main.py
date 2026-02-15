#!/usr/bin/env python3
from gpiozero import Button
import mido
from mido import MidiFile
from pathlib import Path
import sys
import serial
import time

# https://learn.adafruit.com/adafruit-i2c-to-8-channel-solenoid-driver/circuitpython-and-python
import board
from adafruit_mcp230xx.mcp23017 import MCP23017

SCANNER_PORT = '/dev/ttyACM0'
INSTRUMENT_NAME = 'LPK25 mk2'
BUTTON_NOTE = 49    # C# above C3

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
midi_file = None
midi_track = None
last_time = None

def main():
    global recording

    print("\033[90m", "initializing button", "\033[0m")
    init_button()
    print("\033[90m", "initializing keyboard", "\033[0m")
    init_keyboard()
    print("\033[90m", "initializing pins", "\033[0m")
    init_pins()

    print("\033[90m", "initializing barcode scanner", "\033[0m")
    scanner_serial = serial.Serial(SCANNER_PORT, timeout=0)
    scanner_buffer = ""

    print("\033[93m", "… waiting for scans + midi …", "\033[0m")

    try:
        while True:
            # check for serial messages (barcode scans)
            # todo: put this in a separate function
            if scanner_serial.in_waiting > 0:
                data = scanner_serial.read(scanner_serial.in_waiting).decode('utf-8')

                for char in data:
                    if char == '\n' or char == '\r':
                        if scanner_buffer:
                            # todo: play a midi file if the scanner got something
                            print("\t\033[90m", f"scanned {scanner_buffer}", "\033[0m")
                            scanner_buffer = ""
                    else:
                        scanner_buffer += char

            # turn off any solenoids that have expired
            turn_off_solenoids()

            # sleep
            time.sleep(0.0005)

    except KeyboardInterrupt:
        print("\n\033[1;31mCleaning up\033[0m")

        if recording:
            end_recording()

        turn_off_solenoids(force = True)

def handle_midi_msg(msg) -> None:
    global BUTTON_NOTE, recording

    # todo: refactor away from the BUTTON_NOTE
    if recording and msg.note is not BUTTON_NOTE:
        record_note(msg)

    if msg.type == 'note_on':
        print("\t\033[90m", msg, "\033[0m")

        # todo: refactor away from the BUTTON_NOTE
        if msg.note is BUTTON_NOTE:
            # use this note as a button for now
            print("\033[1;31mBUTTON!!\033[0m", recording)

            if recording:
                end_recording()
            else:
                start_recording()

        pin = pin_for(msg.note)

        if (pin is not None):
            start_note(msg.note, duration_for(msg.velocity))

def pin_for(note: int) -> int:
    if note in pin_mapping:
        return pin_mapping.get(note)

    return None

def duration_for(velocity: int) -> int:
    # velocity is 1-128; should clamp it to some set range
    # this will be the duration we activate the solenoid
    min = 7
    max = 30

    return round(velocity / 128 * (max - min)) + min

def start_note(note: int, duration_ms: int) -> None:
    global active_solenoids, pins

    active_solenoids[note] = time.time() + duration_ms / 1000

    pins[note].value = True

def end_note(note: int) -> None:
    global active_solenoids, pins

    del active_solenoids[note]
    pins[note].value = False

def init_button() -> None:
    global button_pin
    # button_record = Button(button_pin)
    # button_record.when_pressed = start_recording
    # button_record.when_pressed = end_recording

def init_keyboard() -> None:
    global INSTRUMENT_NAME

    midi_port = None
    while midi_port is None:
        for input_name in mido.get_input_names():
            if INSTRUMENT_NAME in input_name:
                midi_port = mido.open_input(input_name, handle_midi_msg)

                print(f"Using {input_name}")

        if midi_port is None:
            sys.stdout.write(f" Available inputs: " + ", ".join(mido.get_input_names()).ljust(40, " ") + "\r")

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

def turn_off_solenoids(force: bool = False) -> None:
    global active_solenoids

    now = time.time()
    for note in list(active_solenoids.keys()):
        if force or now >= active_solenoids[note]:
            end_note(note)

def start_recording():
    global midi_file, midi_track, recording, last_time

    print("Starting recording")
    midi_file = MidiFile()
    midi_track = midi_file.add_track('Ben')
    recording = True
    last_time = time.time()

def record_note(msg) -> None:
    global last_time, midi_file, midi_track

    now = time.time()

    msg.time = int(mido.second2tick(now - last_time, midi_file.ticks_per_beat, 500000))
    last_time = now
    midi_track.append(msg)

def end_recording():
    global midi_file, midi_track, recording

    print("Ending recording")
    if len(midi_track) > 0:
        Path('recordings').mkdir(exist_ok=True)
        midi_file.save('recordings/output.mid')
    else:
        print("Track is empty, skipping.")

    recording = False


if __name__ == "__main__":
    main()
