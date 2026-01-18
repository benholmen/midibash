#!/usr/bin/env python3
from gpiozero import Button
import mido
from mido import MidiFile
from pathlib import Path
import sys
import time

# https://learn.adafruit.com/adafruit-i2c-to-8-channel-solenoid-driver/circuitpython-and-python
import board
from adafruit_mcp230xx.mcp23017 import MCP23017

instrument_name = 'LPK25 mk2'
button_note = 49    # C# above C3

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
midi_port = None

def main():
    global button_note, midi_port
    
    init_button()

    init_keyboard()
    
    init_pins()

    print("\033[90m", "waiting for messages", "\033[0m")

    try:
        while True:
            now = time.time()

            # check for new note
            msg = midi_port.receive(block=False)

            # todo: refactor away from the button_note
            if msg and recording and msg.note is not button_note:
                record_note(msg)

            if msg and msg.type == 'note_on':
                print("\t\033[90m", msg, "\033[0m")

                # todo: refactor away from the button_note
                if msg.note is button_note:
                    # use this note as a button for now
                    print("\033[1;31mBUTTON!!\033[0m", recording)

                    if recording:
                        end_recording()
                    else:
                        start_recording()

                pin = pin_for(msg.note)

                if (pin is not None):
                    start_note(msg.note, duration_for(msg.velocity))

            turn_off_solenoids()
            
            # sleep
            time.sleep(0.0005)

    except KeyboardInterrupt:
        print("\n\033[1;31mCleaning up\033[0m")

        if recording:
            end_recording()

        turn_off_solenoids(force = True)

def pin_for(note: int) -> int:
    if note in pin_mapping:
        return pin_mapping.get(note)
    
    return None

def duration_for(velocity: int) -> int:
    # velocity is 1-128; should clamp it to some set range
    # this will be the duration we activate the solenoid
    min = 4
    max = 10

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
    global instrument_name, midi_port
    
    while midi_port is None:
        for input_name in mido.get_input_names():
            if instrument_name in input_name:
                midi_port = mido.open_input(input_name)

                sys.stdout.write(f"\nUsing {input_name}")        

        if midi_port is None:
            sys.stdout.write(f" Available inputs: " + ", ".join(mido.get_input_names()).ljust(40, " ") + "\r")
                
            time.sleep(0.5)

def init_pins() -> None:
    global pin_mapping, pins

    try:
        i2c = board.I2C()
        mcp = MCP23017(i2c, address=0x20)
        print("MCP23017 found successfully!")
    except Exception as e:
        print(f"Could not connect to MCP23017: {e}")
        exit()
    
    for midi_note, pin in pin_mapping.items():
        print(f"mapping midi note {midi_note} to pin {pin}")
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
