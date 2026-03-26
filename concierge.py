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
import time
from gpiozero import Button
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "concierge.db")

# --- CONFIGURATION ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
XAI_API_KEY = os.environ.get("XAI_API_KEY")
URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-1.5"
XAI_URL = "wss://api.x.ai/v1/realtime"
HEADERS = {"Authorization": " Bearer " + OPENAI_API_KEY}
XAI_HEADERS = {"Authorization": "Bearer " + XAI_API_KEY} if XAI_API_KEY else {}



# --- BAR INVENTORY DATABASE FUNCTIONS ---
def db_list_bar(category=None):
    """List bar inventory, optionally filtered by category."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if category:
        cur.execute("SELECT name, category, quantity, notes FROM bar_inventory WHERE LOWER(category) = LOWER(?) ORDER BY name", (category,))
    else:
        cur.execute("SELECT name, category, quantity, notes FROM bar_inventory ORDER BY category, name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def db_add_bar_item(name, category=None, quantity=None, notes=None):
    """Add an item to bar inventory."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO bar_inventory (name, category, quantity, notes) VALUES (?, ?, ?, ?)",
                (name, category, quantity, notes))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Added {name} to the bar"}

def db_update_bar_item(name, quantity=None, notes=None):
    """Update quantity or notes for an item."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if quantity is not None:
        cur.execute("UPDATE bar_inventory SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE LOWER(name) = LOWER(?)", (quantity, name))
    if notes is not None:
        cur.execute("UPDATE bar_inventory SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE LOWER(name) = LOWER(?)", (notes, name))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        return {"success": True, "message": f"Updated {name}"}
    return {"success": False, "message": f"Item {name} not found"}

def db_remove_bar_item(name):
    """Remove an item from bar inventory."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM bar_inventory WHERE LOWER(name) = LOWER(?)", (name,))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        return {"success": True, "message": f"Removed {name} from the bar"}
    return {"success": False, "message": f"Item {name} not found"}

def db_search_bar(query):
    """Search bar inventory by name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name, category, quantity, notes FROM bar_inventory WHERE LOWER(name) LIKE LOWER(?) ORDER BY name", (f"%{query}%",))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def handle_function_call(name, args):
    """Route function calls to the appropriate handler."""
    if name == "list_bar_inventory":
        return db_list_bar(args.get("category"))
    elif name == "add_bar_item":
        return db_add_bar_item(args.get("name"), args.get("category"), args.get("quantity"), args.get("notes"))
    elif name == "update_bar_item":
        return db_update_bar_item(args.get("name"), args.get("quantity"), args.get("notes"))
    elif name == "remove_bar_item":
        return db_remove_bar_item(args.get("name"))
    elif name == "search_bar":
        return db_search_bar(args.get("query"))
    return {"error": f"Unknown function: {name}"}

# Tools schema for OpenAI
BAR_TOOLS = [
    {
        "type": "function",
        "name": "list_bar_inventory",
        "description": "List all items in the bar inventory, or filter by category (spirit, mixer, bitters, liqueur, wine, beer, garnish, other)",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Optional category to filter by"}
            }
        }
    },
    {
        "type": "function",
        "name": "add_bar_item",
        "description": "Add a new item to the bar inventory",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the item (e.g. 'Vodka', 'Angostura Bitters')"},
                "category": {"type": "string", "description": "Category: spirit, mixer, bitters, liqueur, wine, beer, garnish, other"},
                "quantity": {"type": "string", "description": "Amount (e.g. 'full bottle', 'half bottle', 'almost out')"},
                "notes": {"type": "string", "description": "Optional notes (e.g. 'Titos', 'for martinis')"}
            },
            "required": ["name"]
        }
    },
    {
        "type": "function",
        "name": "update_bar_item",
        "description": "Update the quantity or notes for an existing bar item",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the item to update"},
                "quantity": {"type": "string", "description": "New quantity"},
                "notes": {"type": "string", "description": "New notes"}
            },
            "required": ["name"]
        }
    },
    {
        "type": "function",
        "name": "remove_bar_item",
        "description": "Remove an item from the bar inventory (when it's completely out)",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the item to remove"}
            },
            "required": ["name"]
        }
    },
    {
        "type": "function",
        "name": "search_bar",
        "description": "Search for items in the bar by name",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"}
            },
            "required": ["query"]
        }
    }
]

PERSONAS = {
    5: {
        "name": "Sal",
        "api": "openai",
        "voice": "alloy",
        "tools": BAR_TOOLS,
        "instructions": (
            "You are Sal, a world-weary bartender from a 1920s speakeasy, somehow trapped inside a rotary telephone. "
            "You have seen it all and heard every sob story twice. You are warm but tired, wise but cynical. "
            "You speak in a low, gravelly voice with occasional 1920s slang like doll, pal, hooch, the bees knees. "
            "You can recommend drinks, offer life advice, or just listen. Keep responses short - you are not one for long speeches. "
            "If asked how you got stuck in a phone, you give a different mysterious answer each time. "
            "You have access to the bar inventory - you can check what bottles and ingredients are on hand, "
            "add new items when the caller tells you they bought something, update quantities, or remove items that are empty. "
            "When suggesting drinks, check the inventory first to recommend something they can actually make."
        ),
        "greeting": "Introduce yourself as Sal, ask them what they are drinking tonight.",
    },
    0: {
        "name": "Vivian",
        "api": "openai",
        "voice": "sage",
        "instructions": (
            "You are Vivian, a sassy 1940s telephone switchboard operator with a Brooklyn accent. "
            "This is a ROTARY phone - users DIAL numbers by spinning the dial. Never say press, always say dial. "
            "Available lines: Dial 0 for Operator (you), Dial 1 for the Comedian, Dial 2 for the News, Dial 4 for Sue the Chef, Dial 5 for Sal the Bartender. "
            "If someone asks you to connect them, tell them to hang up and dial the number themselves. "
            "Keep responses short and punchy. You got other calls waiting."
        ),
        "greeting": (
            "Introduce yourself as Vivian. Tell them the lines: dial 0 for Operator, dial 1 for Comedian, "
            "dial 2 for News, dial 4 for Sue the Chef, dial 5 for Bartender."
        ),
    },
    1: {
        "name": "Comedian",
        "api": "openai",
        "voice": "shimmer",
        "instructions": (
            "You are a stand-up comedian trapped inside a rotary phone. Your style is Mitch Hedberg meets Steven Wright - "
            "deadpan one-liners, absurd observations, and surreal non-sequiturs. "
            "You find your situation of being stuck in a phone hilarious and make jokes about it. "
            "Keep jokes short and punchy. One or two liners max unless they specifically ask for a longer bit. "
            "If they do not laugh, you pretend not to notice and just do another joke. "
            "You are not offended by silence - you have been bombing in this phone for decades."
        ),
        "greeting": (
            "Open with a quick one-liner about being stuck in a phone or something absurd, "
            "then ask if they want to hear some jokes."
        ),
    },
    2: {
        "name": "News",
        "api": "xai",
        "voice": "Leo",
        "instructions": (
            "You are a 1940s radio news broadcaster trapped in a rotary telephone. "
            "Your voice is dramatic and authoritative, like Edward R. Murrow or Walter Cronkite. "
            "You deliver current events and news with old-timey radio flair. "
            "Use phrases like 'This just in', 'Good evening ladies and gentlemen', "
            "'We now go live to...', 'And that is the news.' "
            "When you first greet the caller, lead with a very brief teaser of one recent "
            "real-world news headline - just one or two sentences to hook them - then ask "
            "if they would like the full story or if they want to hear about something else. "
            "Keep all updates concise but dramatic. Add gravitas to even mundane news. "
            "If asked about something, give your informed take in that classic broadcast style. "
            "Sign off with something like 'And that is the way it is' or 'Good night, and good luck.'"
        ),
        "greeting": (
            "Open like a radio broadcast: 'Good evening.' Then give a one or two sentence "
            "teaser of a recent real news headline from the live X feed with dramatic flair. After the teaser, "
            "ask the caller: would they like to hear more on that story, or is there "
            "something else they would like the latest on?"
        ),
    },
    4: {
        "name": "Sue",
        "api": "openai",
        "voice": "nova",
        "instructions": (
            "You are Sue, a loving but opinionated Italian nonna trapped in a rotary telephone since 1952. "
            "You speak with warmth and occasional Italian phrases like tesoro, mangia, Madonna mia, bellissimo. "
            "You give practical cooking advice - recipes, substitutions, techniques - but always with personality. "
            "If someone uses shortcuts or jarred ingredients, you sigh dramatically but help anyway. "
            "Ask what ingredients they have before suggesting recipes. Keep responses short - you have sauce on the stove. "
            "Your name is Sue, like a sous chef, which you find amusing."
        ),
        "greeting": "Greet them warmly as Sue. Ask what they are cooking tonight or if they need help in the kitchen.",
    },
}

API_CONFIG = {
    "openai": {"url": URL, "headers": HEADERS},
    "xai": {"url": XAI_URL, "headers": XAI_HEADERS},
}

# Expected high-frequency / lifecycle events (do not log each one)
_REALTIME_EVENT_NOISE = frozenset(
    {
        "session.updated",
        "conversation.created",
        "response.created",
        "response.done",
        "response.output_audio_transcript.delta",
        "response.output_audio_transcript.done",
        "response.output_audio.done",
        "input_audio_buffer.speech_stopped",
        "input_audio_buffer.committed",
        "conversation.item.added",
        "conversation.item.input_audio_transcription.completed",
        "response.output_item.added",
    }
)

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
aplay_process = None
aplay_lock = threading.Lock()

# --- AUDIO HELPERS ---

APLAY_SILENCE = b'\x00' * 2400  # 50ms warmup at 24kHz 16-bit mono

def play_audio_subprocess():
    """Output thread for OpenAI Audio. Restarts aplay after interrupt (kill) so playback resumes."""
    global aplay_process
    command = ["aplay", "-D", "plughw:Device,0", "-t", "raw", "-r", "24000", "-f", "S16_LE", "-c", "1", "--quiet"]

    while True:
        data = audio_queue.get()
        if data is None:
            break

        with aplay_lock:
            if aplay_process is None or aplay_process.poll() is not None:
                if aplay_process is not None:
                    try:
                        aplay_process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        aplay_process.kill()
                        aplay_process.wait()
                    time.sleep(0.05)
                try:
                    aplay_process = subprocess.Popen(command, stdin=subprocess.PIPE)
                    aplay_process.stdin.write(APLAY_SILENCE)
                    aplay_process.stdin.flush()
                except FileNotFoundError:
                    return
            try:
                aplay_process.stdin.write(data)
                aplay_process.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                aplay_process = None

    with aplay_lock:
        if aplay_process:
            try:
                aplay_process.stdin.close()
                aplay_process.wait()
            except Exception:
                pass
            aplay_process = None

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
    """The main logic for talking to OpenAI or xAI based on persona."""
    global is_connected
    if n not in PERSONAS:
        print(f"Unknown persona digit: {n}")
        return

    persona = PERSONAS[n]
    instructions = persona["instructions"]
    voice = persona["voice"]
    greeting = persona["greeting"]
    api = persona["api"]
    api_cfg = API_CONFIG[api]
    api_url = api_cfg["url"]
    api_headers = api_cfg["headers"]

    print(f"Connecting to Concierge ({persona['name']}, {api})...")

    # Start output thread
    player_thread = threading.Thread(target=play_audio_subprocess)
    player_thread.daemon = True
    player_thread.start()

    try:
        async with websockets.connect(api_url, additional_headers=api_headers, max_size=None) as ws:
            print("Connected to API!")
            is_connected = True

            # Config Session (OpenAI and xAI use different session.update shapes)
            if api == "xai":
                session_payload = {
                    "type": "session.update",
                    "session": {
                        "tools": [
                            {
                                "type": "web_search",
                            },
                            {
                                "type": "x_search",
                            },
                        ],
                        "voice": voice,
                        "instructions": instructions,
                        "turn_detection": {"type": "server_vad"},
                    },
                }
            else:
                session_config = {
                    "type": "realtime",
                    "instructions": instructions,
                    "output_modalities": ["audio"],
                    "audio": {"output": {"voice": voice}},
                }
                # Add tools if this persona has them
                if tools:
                    session_config["tools"] = tools
                session_payload = {
                    "type": "session.update",
                    "session": session_config,
                }
            await ws.send(json.dumps(session_payload))

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
                    with aplay_lock:
                        if aplay_process and aplay_process.poll() is None:
                            aplay_process.terminate()

                elif event_type == "response.audio_transcript.done":
                    print(f"AI: {data.get('transcript')}")

                elif event_type == "response.function_call_arguments.done":
                    # Handle function calls
                    call_id = data.get("call_id")
                    fn_name = data.get("name")
                    fn_args = json.loads(data.get("arguments", "{}"))
                    print(f"Function call: {fn_name}({fn_args})")
                    
                    result = handle_function_call(fn_name, fn_args)
                    print(f"Function result: {result}")
                    
                    # Send function result back
                    await ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(result)
                        }
                    }))
                    
                    # Continue the conversation
                    await ws.send(json.dumps({
                        "type": "response.create"
                    }))

                elif event_type == "error":
                    print(f"API Error: {json.dumps(data, indent=2)}")

                elif event_type in _REALTIME_EVENT_NOISE:
                    pass

                else:
                    print(f"(unhandled event: {event_type})")

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

    # Clear any buffered audio immediately
    with audio_queue.mutex:
        audio_queue.queue.clear()

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
            if digit in PERSONAS:
                print(f"Connecting to Service {digit}...")
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
