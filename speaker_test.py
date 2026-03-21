#!/usr/bin/env python3
import subprocess

print("Speaker test running — press Ctrl+C to stop")
subprocess.run(["speaker-test", "-c2", "-t", "wav", "-D", "plughw:Device,0"])
