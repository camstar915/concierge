import os
import json
import base64
import asyncio
import websockets
import soundfile
import struct
import threading
import queue
import sys
import subprocess

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

url = "wss://api.openai.com/v1/realtime?model=gpt-realtime"
headers = {"Authorization": " Bearer " + OPENAI_API_KEY}

audio_queue = queue.Queue()
CHANNELS = 1
RATE = 24000

def float_to_16bit_pcm(float32_array):
    # Clamp values to [-1.0, 1.0] to prevent clipping artifacts
    clipped = [max(-1.0, min(1.0, x)) for x in float32_array]
    # Convert float to 16-bit PCM bytes
    pcm16 = b''.join(struct.pack('<h', int(x * 32767)) for x in clipped)
    return pcm16

def base64_encode_audio(float32_array):
    pcm_bytes = float_to_16bit_pcm(float32_array)
    encoded = base64.b64encode(pcm_bytes).decode('ascii')
    return encoded

def play_audio_subprocess():
    command = ["aplay", "-D", "plughw:Device,0", "-t", "raw", "-r", "24000", "-f", "S16_LE", "-c", "1", "--quiet"]

    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
    except FileNotFoundError:
        print("Error: 'aplay' not found. Ensure ALSA is installed.")
        return

    while True:
        data = audio_queue.get()
        if data is None:
            break
        try:
            process.stdin.write(data)
            process.stdin.flush()
        except BrokenPipeError:
            print("Audio player process died unexpectedly.")
            break

    process.stdin.close()
    process.wait()

async def send_microphone_audio(ws):
    """
    Streams audio from the microphone (arecord) to the WebSocket.
    """
    # We record at 24000Hz, S16_LE, Mono, Raw (no headers)
    # The 'plughw' device should handle sample rate conversion if your hardware is 48k
    command = [
        "arecord", 
        "-D", "plughw:Device,0", 
        "-t", "raw", 
        "-r", "24000", 
        "-f", "S16_LE", 
        "-c", "1", 
        "-q" # Quiet mode
    ]

    print("Starting microphone stream...")

    # Start arecord as an async subprocess
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE
    )

    try:
        while True:
            # Read 4KB chunks (approx 0.08s of audio)
            data = await process.stdout.read(4096)
            if not data:
                break

            # Encode to base64
            base64_audio = base64.b64encode(data).decode("utf-8")

            # Send to OpenAI
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64_audio
            }))

            # We don't need to commit/create_response manually because
            # server_vad (Voice Activity Detection) is enabled by default.

    except Exception as e:
        print(f"Microphone error: {e}")
    finally:
        if process.returncode is None:
            process.terminate()


async def main():
	player_thread = threading.Thread(target=play_audio_subprocess)
	player_thread.daemon = True
	player_thread.start()
	async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
		print("Connected to realtime api")

		await ws.send(json.dumps({
			"type": "session.update",
			"session": {
				"type": "realtime",
				"instructions": "You are a classy bartender stuck in a rotary phone. Keep responses short. When giving recipies, give measurements and speak slower. Ask if the user needs you to repeat anything.",
				"output_modalities": ["audio"],
				"audio": {
					"output": {
						"voice": "alloy"
					}
				}
			}
		}))
		print("session configured - ready for audio input")

		await ws.send(json.dumps({
			"type": "response.create",
			"response": {
				"output_modalities": ["audio"],
				"instructions": "Greet the user as if they just picked up the phone. Simply ask what you can help them make."
			}
		}))

		microphone_task = asyncio.create_task(send_microphone_audio(ws))

		async for message in ws:
			data = json.loads(message)
			event_type = data.get("type", "unknown")

			if event_type == "error":
				print("Error:", json.dumps(data))

			elif event_type == "response.output_audio.done":
				print("response output audio done")

			elif event_type == "response.output_audio.delta":
				base64_audio = data.get("delta")
				if base64_audio:
					audio_bytes = base64.b64decode(base64_audio)
					audio_queue.put(audio_bytes)
				print("output_audio.delta")

			elif event_type == "input_audio_buffer.speech_started":
				print("(User started speaking - clearing audio queue)")
				with audio_queue.mutex:
					audio_queue.queue.clear()

			elif event_type == "error":
				print(f"Error: {data}")

			elif event_type == "response.done":
				print("Response done.")
				pass


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		audio_queue.put(None)
		print("\nStopped by user")
