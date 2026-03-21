from gpiozero import Button
from signal import pause
import time

# --- CONFIGURATION ---
# "Pulse" wire (Blue) connected to GPIO 23.
# The other side (Green) is connected to Ground.
pulse_pin = 23

# "Off-Normal" wire (White) connected to GPIO 24.
# The other side (White) is connected to Ground.
off_normal_pin = 24

# --- SETUP PINS ---
# pull_up=True means the pin is HIGH (1) when open, and LOW (0) when pressed (grounded)
pulse_switch = Button(pulse_pin, pull_up=True, bounce_time=0.01)
off_normal_switch = Button(off_normal_pin, pull_up=True, bounce_time=0.1)

# Variables to store state
pulse_count = 0
dialing = False

def count_pulse():
    """Called every time the pulse switch opens/closes"""
    global pulse_count
    if dialing:
        pulse_count += 1
        print(".", end="", flush=True)

def rotation_started():
    """Called when the dial is moved from rest"""
    global dialing, pulse_count
    dialing = True
    pulse_count = 0
    print("Dial started...", end="", flush=True)

def rotation_ended():
    """Called when the dial returns to rest"""
    global dialing, pulse_count
    dialing = False

    # Check if we actually got pulses (ignoring accidental touches)
    if pulse_count > 0:
        digit = pulse_count

        # 10 pulses means the number 0
        if digit == 10:
            digit = 0

        print(f"\nDigit Dialed: {digit}")
    else:
        print("\n(Ignored)")

    pulse_count = 0

# --- EVENT BINDINGS ---
# The pulse switch is "Normally Closed" (connected to ground).
# When it opens (pulses), the voltage goes HIGH (released).
# Depending on your specific dial, you might need 'when_pressed' instead.
# For most Western Electric dials, the pulses happen when the switch OPENS.
pulse_switch.when_released = count_pulse

# The off-normal switch is "Normally Open".
# When you start dialing, it closes (connects to ground -> pressed).
off_normal_switch.when_pressed = rotation_started
off_normal_switch.when_released = rotation_ended

print("Rotary Dial Listener Running...")
print("Spin the dial to test.")

try:
    pause() # Keep the script running
except KeyboardInterrupt:
    print("\nStopped")
