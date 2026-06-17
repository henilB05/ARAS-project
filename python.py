import socket
import wave
import os
import struct
import time
import subprocess
import threading

from groq import Groq
from gtts import gTTS

# ── Config ────────────────────────────────
GROQ_API_KEY      = "Groq api"   # ← paste your gsk_... key here
HOST              = "0.0.0.0"
VA_PORT           = 5000   # full 10-sec recording + AI answer
VA_TARGET_BYTES   = 640000 # 10 sec @ 16kHz 32-bit mono

client = Groq(api_key=GROQ_API_KEY)


# ── Convert raw 32-bit ESP32 audio to 16-bit WAV for Whisper ──
def save_wav_16bit(raw_data, filename):
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "s32le",
        "-ar", "16000",
        "-ac", "1",
        "-i", "pipe:0",
        "-ar", "16000",
        "-ac", "1",
        "-sample_fmt", "s16",
        filename
    ], input=bytes(raw_data), check=True,
       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ── Transcribe audio file using Groq Whisper ──────────────────
def transcribe(filename):
    with open(filename, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(filename, f.read()),
            model="whisper-large-v3",
            language="en",
            response_format="text"
        )
    return result.strip() if isinstance(result, str) else result.text.strip()

# ── Ask Groq llama-3.3-70b ────────────────────────────────────
def ask_llama(command):
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "You are a smart helmet voice assistant for a motorcycle rider. "
                           "Answer concisely in 1-2 sentences. No markdown, no bullet points, plain speech only."
            },
            {
                "role": "user",
                "content": command
            }
        ],
        max_tokens=200
    )
    return response.choices[0].message.content.strip()

# ══════════════════════════════════════════
# VOICE ASSISTANT SERVER — port 5000
# ══════════════════════════════════════════

def handle_va_client(conn, addr):
    print(f"[VA] Connection from {addr}")
    try:
        # ── 1. Receive 10-sec audio ──────────────────────────
        print("[VA] Receiving audio...")
        audio_data = bytearray()

        while len(audio_data) < VA_TARGET_BYTES:
            data = conn.recv(4096)
            if not data:
                break
            audio_data.extend(data)

        print(f"[VA] Audio received: {len(audio_data)} bytes")

        # ── 2. Convert & save as 16-bit WAV ──────────────────
        save_wav_16bit(audio_data, "recording.wav")
        print("[VA] recording.wav saved")

        # ── 3. Transcribe with Groq Whisper ──────────────────
        print("[VA] Transcribing with Groq Whisper...")
        user_text = transcribe("recording.wav")
        print(f"\n[USER SAID]\n{user_text}\n")

        # ── 4. Strip wake word, get command ──────────────────
        command = user_text.strip()

        print(f"[COMMAND] {command}")

        if not command:
            answer = "I could not understand. Please speak again."
        else:
            # ── 5. Ask Groq llama-3.3-70b ─────────────────────
            print("[VA] Asking Groq llama-3.3-70b...")
            answer = ask_llama(command)
            print(f"\n[GROQ ANSWER]\n{answer}\n")

        # ── 6. TTS → WAV ─────────────────────────────────────
        tts = gTTS(answer, lang='en')
        tts.save("reply.mp3")

        subprocess.run([
            "ffmpeg", "-y",
            "-i", "reply.mp3",
            "-ac", "1",
            "-ar", "16000",
            "-sample_fmt", "s16",
            "reply.wav"
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print("[VA] reply.wav generated")

        # ── 7. Send text answer ───────────────────────────────
        answer_bytes = answer.encode("utf-8")
        conn.sendall(struct.pack("<I", len(answer_bytes)))
        conn.sendall(answer_bytes)
        print(f"[VA] Text sent: {len(answer_bytes)} bytes")

        # ── 8. Send WAV ───────────────────────────────────────
        wav_size = os.path.getsize("reply.wav")
        conn.sendall(struct.pack("<I", wav_size))
        print(f"[VA] Sending WAV: {wav_size} bytes...")

        with open("reply.wav", "rb") as f:
            while True:
                chunk = f.read(1024)
                if not chunk:
                    break
                conn.sendall(chunk)

        print("[VA] WAV sent")

    except Exception as e:
        print(f"[VA] Error: {e}")

    finally:
        time.sleep(1.0)
        conn.close()
        print("[VA] Done. Waiting for next connection.\n")


def va_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, VA_PORT))
    server.listen(1)
    print(f"[VA] Server ready on port {VA_PORT}")

    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_va_client, args=(conn, addr), daemon=True)
        t.start()

# ══════════════════════════════════════════
# MAIN — start both servers
# ══════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 40)
    print("  Smart Helmet Server")
    print(f"  Assistant : port {VA_PORT}")
    print("=" * 40)



    va_server()
