# /// script
# dependencies = [
#     "mido>=1.3.3",
#     "pigpio>=1.78",
#     "python-rtmidi>=1.5.8",
# ]
# ///
import mido
from mido import MidiFile
from pathlib import Path
import pigpio
import sys
import time

def main():
    instrument_name = 'LPK25 mk2'
    button_note = 36
    active_solenoids = {}
    recording = False

    if instrument_name not in mido.get_input_names():
        print(f"\033[1;31mCould not find {instrument_name}.\033[0m")

        while instrument_name not in mido.get_input_names():
            sys.stdout.write(f" Available inputs: " + ", ".join(mido.get_input_names()).ljust(40, " ") + "\r")
                
            time.sleep(1)

        sys.stdout.write(f"\n\n{instrument_name} is now available, proceeding")

    # init pigpio, if present
    gpio = pigpio.pi()
    if not gpio.connected:
        print("\033[1;31mCould not init pigpio, did you run sudo pigpiod?\033[0m")

    midi_port = mido.open_input(instrument_name)

    print("\033[90m", "waiting for messages", "\033[0m")

    try:
        while True:
            now = time.time()

            # check for new note
            msg = midi_port.receive(block=False)

            if msg and recording:
                msg.time = int(mido.second2tick(now - last_time, midi_file.ticks_per_beat, 500000))
                last_time = now
                midi_track.append(msg)

            if msg and msg.type == 'note_on':
                print("\t\033[90m", msg, "\033[0m")

                if msg.note is button_note:
                    # use this note as a button for now
                    print("\033[1;31mBUTTON!!\033[0m")

                    if recording:
                        # save_file(midi_file)
                        Path('recordings').mkdir(exist_ok=True)
                        midi_file.save('recordings/output.mid')
                        midi_track = None
                        recording = False
                    else:
                        midi_file = MidiFile()
                        midi_track = midi_file.add_track('Ben')
                        recording = True
                        last_time = now

                pin = pin_for(msg.note)

                if (pin):
                    start(pin)
                    active_solenoids[pin] = now + (duration_for(msg.velocity) / 100)

            # check for expired notes
            for pin in list(active_solenoids.keys()):
                if now >= active_solenoids[pin]:
                    stop(pin)
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
            Path('recordings').mkdir(exist_ok=True)
            midi_file.save('recordings/output.mid')

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

def start(pin: int):
    # print("↓", pin)
    return

def stop(pin: int):
    # print ("↑", pin)
    return

def bash(pin: int, duration: int):
    print("↯↯", pin, "for", duration, "ms")

if __name__ == "__main__":
    main()
