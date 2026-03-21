#!/usr/bin/env python3
from gpiozero import Button
import subprocess

b = Button(17, pull_up=True)
recording = None

def down():
    global recording
    print("\rHandset: DOWN — recording… (speak now!)", end="", flush=True)
    if recording is None or recording.poll() is not None:
        recording = subprocess.Popen([
            "arecord", "-D", "plughw:Device,0", "-f", "cd", "-c", "1",
            "-t", "wav", "/tmp/recording.wav"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def up():
    global recording
    print("\rHandset: UP — playing back           ", end="", flush=True)
    if recording and recording.poll() is None:
        recording.terminate()
        recording.wait()
    subprocess.run([
        "aplay", "-D", "plughw:Device,0", "--quiet", "/tmp/recording.wav"
    ])

print("Record when DOWN · Play when UP — ready")
print("Handset: DOWN — waiting", end="", flush=True)

b.when_released = down   # handset down = start recording
b.when_pressed  = up     # handset up   = stop and play back

try:
    while True:
        pass
except KeyboardInterrupt:
    if recording: recording.terminate()
    print("\nStopped")
