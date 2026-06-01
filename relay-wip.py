import pigpio
import time

# Define the GPIO pin (Broadcom/BCM numbering)
RELAY_PIN = 14

# Initialize the pigpio library
pi = pigpio.pi()

if not pi.connected:
    print("Could not connect to pigpiod. Is the daemon running?")
    exit()

try:
    print(f"Turning relay on (Pin {RELAY_PIN})...")
    # Set pin as output and turn it ON (Logic High)
    pi.write(RELAY_PIN, 1)

    # Wait for 5 seconds
    time.sleep(5)

    print("Turning relay off...")
    # Turn it OFF (Logic Low)
    pi.write(RELAY_PIN, 0)

except KeyboardInterrupt:
    print("\nScript stopped by user.")

finally:
    # Clean up: stop the connection and ensure pin is safe
    pi.write(RELAY_PIN, 0)
    pi.stop()
    print("Connection closed.")
