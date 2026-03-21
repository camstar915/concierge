#!/usr/bin/env python3
from gpiozero import Button
import subprocess
import time

b = Button(17, pull_up=True)
test = None

def down():
    global test
    print("\rHandset: DOWN — PLAYING speaker test (Ctrl+C to quit)", end="", flush=True)
    if test is None or test.poll() is not None:
        test = subprocess.Popen(["speaker-test", "-c2", "-t", "wav", "-D", "plughw:Device,0"])

def lifted():
    global test
    print("\rHandset: LIFTED — speaker test stopped          ", end="", flush=True)
    if test and test.poll() is None:
        test.terminate()
        test = None

print("Hook + Speaker test ready")
print("Handset: DOWN — waiting", end="", flush=True)

b.when_released = down    # handset down = start speaker test
b.when_pressed  = lifted  # handset up   = stop speaker test

try:
    while True:
        time.sleep(0.1)
except KeyboardInterrupt:
    if test:
        test.terminate()
    print("\nStopped")
