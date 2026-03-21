import os
import json
import base64
import asyncio
import websockets
import struct
import threading
import queue
import sys
import subprocess
from gpiozero import Button

# --- CONFIGURATION ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
XAI_API_KEY = os.environ.get("XAI_API_KEY")
URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-1.5"
XAI_URL = "wss://api.x.ai/v1/realtime"
HEADERS = {"Authorization": " Bearer " + OPENAI_API_KEY}

# GPIO PINS
PIN_HOOK = 17       # Handset Switch
PIN_PULSE = 23      # Rotary Pulse (Blue/Green)
PIN_OFF_NORMAL = 24 # Rotary Active (Whites)

# GLOBAL STATE
audio_queue = queue.Queue()
ai_task = None
dial_tone_process = None
is_connected = False
pulse_count = 0

# --- AUDIO HELPERS ---

def play_audio_subprocess():
    """Output thread for OpenAI Audio"""
    command = ["aplay", "-D", "plughw:Device,0", "-t", "raw", "-r", "24000", "-f", "S16_LE", "-c", "1", "--quiet"]
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
    except FileNotFoundError:
        return

    while True:
        data = audio_queue.get()
        if data is None: # Poison pill
            break
        try:
            process.stdin.write(data)
            process.stdin.flush()
        except (BrokenPipeError, ValueError):
            break

    try:
        process.stdin.close()
        process.wait()
    except:
        pass

def start_dial_tone():
    """Plays dial-tone.wav in a loop using a shell loop"""
    global dial_tone_process
    if dial_tone_process is not None:
        return # Already playing

    print("Playing dial tone...")
    try:
        # We use a shell loop: "while true; do aplay...; done"
        # This forces the sound to repeat infinitely.
        dial_tone_process = subprocess.Popen(
            "while :; do aplay -D plughw:Device,0 -q dial-tone.wav; done",
            shell=True, # Required for the loop syntax
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid # logic to allow killing the whole group later
        )
    except Exception as e:
        print(f"Error starting dial tone: {e}")
def stop_dial_tone():
    """Kills the dial tone process"""
    global dial_tone_process
    if dial_tone_process:
        print("Stopping dial tone.")
        try:
            os.killpg(os.getpgid(dial_tone_process.pid), 15) # Kill process group
            dial_tone_process = None
        except:
            dial_tone_process = None

# --- AI & NETWORK TASKS ---

async def send_microphone_audio(ws):
    """Streams mic input to OpenAI"""
    command = ["arecord", "-D", "plughw:Device,0", "-t", "raw", "-r", "24000", "-f", "S16_LE", "-c", "1", "-q"]
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE)

    try:
        while True:
            data = await process.stdout.read(4096)
            if not data: break

            base64_audio = base64.b64encode(data).decode("utf-8")
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append", 
                "audio": base64_audio
            }))
    except asyncio.CancelledError:
        print("Mic stream stopped.")
    finally:
        if process.returncode is None:
            process.terminate()

async def run_ai_session(n):
    """The main logic for talking to OpenAI"""
    global is_connected
    print("Connecting to Concierge...")

    # Defining personas
    instructions = "You are a helpful assistant."
    voice = "alloy"
    greeting = "Greet the user like they just picked up the phone."

    if n == 5:
        instructions = "You are a classy bartender stuck in a rotary phone. Keep responses short."
        voice = "alloy"
        greeting = "Greet the user as the rotary bartender as if they just picked up the phone."

    elif n == 0:
        instructions = ("You are 'The Operator'. Your job is to inform the user of "
			"the other personalities we can dial on this phone "
			"the user needs to hang up and dial a new number for another personality"
			"dialing zero is you, the operator. dial 5 for the bartender."
			"dial 1 for a comedian."
			"keep in mind the user needs to hang up and dial to connect to somebody else"
	)
        voice = "sage"
        greeting = "Introduce yourself as The Operator."

    elif n == 1:
        instructions = ("You are a joke teller. Make everything a cheezy joke! Be whitty! "
			"you are a comedian stuck in a rotary phone!"
			"keep the jokes brief and quick hitter whitty unless the user asks for a long joke"
	)
        voice = "shimmer"
        greeting = "The user just picked up the phone. Make a joke!"

    # Start output thread
    player_thread = threading.Thread(target=play_audio_subprocess)
    player_thread.daemon = True
    player_thread.start()

    try:
        async with websockets.connect(URL, additional_headers=HEADERS, max_size=None) as ws:
            print("Connected to API!")
            is_connected = True

            # Config Session
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": instructions,
                    "output_modalities": ["audio"],
                    "audio": {"output": {"voice": voice}}
                }
            }))

            # Initial Greeting
            await ws.send(json.dumps({
                "type": "response.create",
                "response": {
                    "output_modalities": ["audio"],
                    "instructions": greeting
                }
            }))

            # Start Mic
            mic_task = asyncio.create_task(send_microphone_audio(ws))

            # Event Loop
            async for message in ws:
                data = json.loads(message)
                event_type = data.get("type", "unknown")

                if event_type == "response.output_audio.delta" or event_type == "response.audio.delta":
                    if data.get("delta"):
                        audio_queue.put(base64.b64decode(data["delta"]))

                elif event_type == "input_audio_buffer.speech_started":
                    print("(User speaking - clearing queue)")
                    with audio_queue.mutex:
                        audio_queue.queue.clear()

                elif event_type == "response.audio_transcript.done":
                    print(f"AI: {data.get('transcript')}")

    except asyncio.CancelledError:
        print("AI Session Cancelled.")
    except Exception as e:
        print(f"Connection Error: {e}")
    finally:
        is_connected = False
        # Kill the player thread by sending None
        audio_queue.put(None)
        if 'mic_task' in locals():
            mic_task.cancel()

# --- HARDWARE HANDLERS ---

def handle_hook_up():
    """Handset Lifted"""
    print("Phone Off-Hook")
    # If not already connected, play dial tone
    if not is_connected:
        start_dial_tone()

def handle_hook_down():
    """Handset Dropped"""
    print("Phone On-Hook")
    stop_dial_tone()

    # If AI is running, cancel it
    global ai_task
    if ai_task and not ai_task.done():
        print("Hanging up on AI...")
        # We must use call_soon_threadsafe because this callback runs in GPIO thread
        loop.call_soon_threadsafe(ai_task.cancel)

# --- ROTARY LOGIC ---

def count_pulse():
    global pulse_count
    pulse_count += 1

def rotation_started():
    global pulse_count
    # Stop dial tone as soon as they start spinning
    stop_dial_tone()
    pulse_count = 0

def rotation_ended():
    global pulse_count, ai_task, loop
    digit = pulse_count
    if digit == 10: digit = 0

    if pulse_count > 0:
        print(f"Dialed: {digit}")
        # LOGIC: If they dial 5, connect to AI
        if not is_connected:
            if digit in [0, 5, 1]:
                print("Connecting to Service {digit}...")
                # Schedule the async task safely
                ai_task = asyncio.run_coroutine_threadsafe(run_ai_session(digit), loop)
            else:
                print(f"Number {digit} is not in service.")

    pulse_count = 0

# --- MAIN SETUP ---

# Setup GPIO
hook_btn = Button(PIN_HOOK, pull_up=True)
pulse_btn = Button(PIN_PULSE, pull_up=True, bounce_time=0.01) # Blue
off_normal_btn = Button(PIN_OFF_NORMAL, pull_up=True, bounce_time=0.1) # White

# Hook Logic
# Note: Adjust logic if your switch is inverted.
# Usually Pressed=Circuit Closed. If your test said "Lifted" on pressed:
hook_btn.when_pressed = handle_hook_up    # Lifted
hook_btn.when_released = handle_hook_down # Dropped

# Rotary Logic
pulse_btn.when_released = count_pulse
off_normal_btn.when_pressed = rotation_started
off_normal_btn.when_released = rotation_ended

async def main_loop():
    """Keeps the script alive waiting for events"""
    global loop
    loop = asyncio.get_running_loop()
    print(" concierge.py is running...")
    print(" 1. Lift Handset -> Hear Dial Tone")
    print(" 2. Dial '1, 5, or 0' -> Talk to AI")
    print(" 3. Hang up -> Reset")

    # Keep alive forever
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        stop_dial_tone()
        print("\nGoodbye")
