from gpiozero import Button
import time

b = Button(17, pull_up=True)

def show():
    state = "LIFTED" if b.is_pressed else "DOWN  "
    print(f"\rHandset: {state}", end="", flush=True)

print("Hookswitch test — watching GPIO 17 (hole 11)")
show()

b.when_pressed  = show
b.when_released = show

try:
    while True:
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\nStopped")
