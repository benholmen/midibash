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

pins_numbers = [0, 2, 4, 6, 8, 10, 12, 14]

pins = {}

try:
    i2c = board.I2C()
    mcp0 = MCP23017(i2c, address=0x20)
    # mcp1 = MCP23017(i2c, address=0x21)
    # mcp2 = MCP23017(i2c, address=0x22)
    # mcp3 = MCP23017(i2c, address=0x23)
    print("MCP23017 found successfully!")
except Exception as e:
    print(f"Could not connect to MCP23017: {e}")
    exit()

notes = {
    60: (mcp0, 0),
    61: (mcp0, 1),
    62: (mcp0, 2),
    63: (mcp0, 3),
    # 64: (mcp1, 0),
    # 65: (mcp1, 2),
    # 66: (mcp1, 4),
    # 67: (mcp1, 6),
}

for midi_key, physical_location in notes.items():
    mcp, pin = physical_location
    i2c_pin = mcp.get_pin(pin)
    i2c_pin.switch_to_output(value=False)
    pins[midi_key] = i2c_pin

while True:
    n = 0
    for midi_key, pin in pins.items():
        print(midi_key)
        pin.value = True
        time.sleep(0.1)
        pin.value = False
        time.sleep(1)
