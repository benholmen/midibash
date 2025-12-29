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

try:
    i2c = board.I2C()
    mcp = MCP23017(i2c)
    print("MCP23017 found successfully!")
except Exception as e:
    print(f"Could not connect to MCP23017: {e}")
    print("Check your wiring and run 'sudo i2cdetect -y 1' again.")
    exit()

# Create a list of all 8 pins on Port A (A0-A7)
solenoids = []
for i in range(8):
    pin = mcp.get_pin(i)
    pin.switch_to_output(value=False)
    solenoids.append(pin)

print("Starting Solenoid Test Loop (A0-A7)...")
print("Press Ctrl+C to stop.")

try:
    while True:
        for index, noid in enumerate(solenoids):
            print(f"Activating A{index}...")
            noid.value = True
            
            # Verify the state by reading it back
            time.sleep(0.1) 
            print(f"A{index} state is now: {noid.value}")
            
            time.sleep(0.5)
            noid.value = False
            time.sleep(0.1)
            
        print("-" * 20)
        time.sleep(1)

except KeyboardInterrupt:
    print("\nCleaning up... turning all solenoids off.")
    for noid in solenoids:
        noid.value = False

def main():
    instrument_name = 'LPK25 mk2'
    button_note = 36
    active_solenoids = {}
    recording = False
    midi_file = None
    midi_track = None
    last_time = None
    midi_port = None

    def start_recording():
        nonlocal midi_file, midi_track, recording, last_time

        print("Starting recording")
        midi_file = MidiFile()
        midi_track = midi_file.add_track('Ben')
        recording = True
        last_time = time.time()

    def end_recording():
        nonlocal midi_file, midi_track, recording

        print("Ending recording")
        if len(midi_track) > 0:
            Path('recordings').mkdir(exist_ok=True)
            midi_file.save('recordings/output.mid')
        else:
            print("Track is empty, skipping.")

        recording = False
    
    # button_record = Button(2)
    # button_record.when_pressed = start_recording
    # button_record.when_pressed = end_recording

    while midi_port is None:
        for input_name in mido.get_input_names():
            if instrument_name in input_name:
                midi_port = mido.open_input(input_name)

                sys.stdout.write(f"\nUsing {input_name}")        

        if midi_port is None:
            sys.stdout.write(f" Available inputs: " + ", ".join(mido.get_input_names()).ljust(40, " ") + "\r")
                
            time.sleep(1)

    print("\033[90m", "waiting for messages", "\033[0m")

    try:
        while True:
            now = time.time()

            # check for new note
            msg = midi_port.receive(block=False)

            # todo: refactor away from the button_note
            if msg and recording and msg.note is not button_note:
                msg.time = int(mido.second2tick(now - last_time, midi_file.ticks_per_beat, 500000))
                last_time = now
                midi_track.append(msg)

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

                if (pin):
                    start_note(pin)
                    active_solenoids[pin] = now + (duration_for(msg.velocity) / 100)

            # check for expired notes
            for pin in list(active_solenoids.keys()):
                if now >= active_solenoids[pin]:
                    end_note(pin)
                    del active_solenoids[pin]

            # debug output
            active_count = len(active_solenoids)
            status_bar = "".join([str(k) + " " for k in active_solenoids.keys()])
            sys.stdout.write(f"\r{status_bar.ljust(40, ".")}")
            sys.stdout.flush()
            
            # sleep
            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n\033[1;31mCleaning up\033[0m")

        if recording:
            end_recording()

        for pin in list(active_solenoids.keys()):
            stop(pin)

def pin_for(note: int) -> int:
    min = 36
    max = 85

    if (note < min or note > max):
        return

    return note - min

def duration_for(velocity: int) -> int:
    # velocity is 1-128; should clamp it to some set range
    # such as 10-40
    # this will be the duration we activate the solenoid
    min = 10
    max = 40

    return round(velocity / 128 * (max - min)) + min

def start_note(pin: int) -> None:
    # print("↓", pin)
    return

def end_note(pin: int) -> None:
    # print ("↑", pin)
    return

def bash(pin: int, duration: int) -> None:
    print("↯↯", pin, "for", duration, "ms")

if __name__ == "__main__":
    main()
