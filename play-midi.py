#!/usr/bin/env python3
import mido
from mido import MidiFile
from pathlib import Path
import sys
import time

def main():
    instrument_name = "LPK25 mk2"
    button_note = 36
    active_solenoids = {}
    pending_messages = []
    recording = False
    playing = False
    midi_file = None
    midi_track = None
    last_time = None
    midi_port = None
    
    def start_playing():
        nonlocal pending_messages, playing
        pending_messages = []
        playing = True

        absolute_time = None
        for msg in MidiFile("recordings/output.mid"):
            if absolute_time:
                absolute_time += msg.time
            elif not msg.is_meta:
                absolute_time = time.time()

            if msg.type == "note_on":
                msg.time = absolute_time
                pending_messages.append(msg)

        print(pending_messages)
        exit(0)

    def end_playing():
        nonlocal playing
        playing = False

    def start_recording():
        nonlocal midi_file, midi_track, recording, last_time

        print("Starting recording")
        midi_file = MidiFile()
        midi_track = midi_file.add_track("Ben")
        recording = True
        last_time = time.time()

    def end_recording():
        nonlocal midi_file, midi_track, recording

        print("Ending recording")
        if len(midi_track) > 0:
            Path("recordings").mkdir(exist_ok=True)
            midi_file.save("recordings/output.mid")
        else:
            print("Track is empty, skipping.")

        recording = False

    start_playing()

    while midi_port is None:
        for input_name in mido.get_input_names():
            if instrument_name in input_name:
                midi_port = mido.open_input(input_name)

                sys.stdout.write(f"\nUsing {input_name}")

        if midi_port is None:
            sys.stdout.write(
                " Available inputs: "
                + ", ".join(mido.get_input_names()).ljust(40, " ")
                + "\r"
            )

            time.sleep(1)

    print("\033[90m", "waiting for messages", "\033[0m")

    try:
        while True:
            now = time.time()

            # check for new note
            msg = midi_port.receive(block=False)

            # todo: refactor away from the button_note
            if msg and recording and msg.note is not button_note:
                msg.time = int(
                    mido.second2tick(now - last_time, midi_file.ticks_per_beat, 500000)
                )
                last_time = now
                midi_track.append(msg)

            if msg and msg.type == "note_on":
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

                if pin:
                    start_note(pin)
                    active_solenoids[pin] = now + (duration_for(msg.velocity) / 100)

            # check for expired notes
            for pin in list(active_solenoids.keys()):
                if now >= active_solenoids[pin]:
                    end_note(pin)
                    del active_solenoids[pin]

            # debug output
            status_bar = "".join([str(k) + " " for k in active_solenoids.keys()])
            sys.stdout.write(f"\r{status_bar.ljust(40, '.')}")
            sys.stdout.flush()

            # sleep
            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n\033[1;31mCleaning up\033[0m")

        if recording:
            end_recording()

        for pin in list(active_solenoids.keys()):
            end_note(pin)


def pin_for(note: int) -> int:
    min = 36
    max = 85

    if note < min or note > max:
        return

    return note - min


def duration_for(velocity: int) -> int:
    # velocity is 1-128; should clamp it to some set range
    # this will be the duration we activate the solenoid
    min = 5
    max = 20

    return round(velocity / 128 * (max - min)) + min


def start_note(pin: int) -> None:
    print("↓", pin)


def end_note(pin: int) -> None:
    print("↑", pin)


def track_length(path: str) -> int:
    length = None
    for msg in MidiFile(path):
        if length is not None:
            length += msg.time
        elif not msg.is_meta:
            # This will be the first non-meta message, so ignore the time value
            # and initialize length to 0
            length = 0

    return length

if __name__ == "__main__":
    main()
