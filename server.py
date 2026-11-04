#!/usr/bin/env python3
"""
VaaniTTS (Edge TTS Edition) - Text-to-speech studio for Hindi + English.

Powered by Microsoft Edge TTS - 100% Free, Unlimited, no API key needed!
Includes ultra-natural Male & Female voices for Hindi (Madhur, Swara) and English.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import tempfile
import threading
import time
import uuid
import wave
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR = BASE_DIR / "output"
ENV_FILE = BASE_DIR / ".env"

MAX_CHARS = 50_000
CHUNK_CHARS = 2_500  # Edge TTS handles larger chunks easily
PORT = 8000


# --------------------------------------------------------------------------- #
# Voice catalogue (Microsoft Edge TTS Neural Voices — 100% Free)
# --------------------------------------------------------------------------- #

EDGE_VOICES = [
    # Hindi Voices
    {"id": "hi-IN-MadhurNeural", "label": "Madhur (Hindi · Male)", "lang": "hi-IN", "gender": "Male", "group": "Hindi"},
    {"id": "hi-IN-SwaraNeural", "label": "Swara (Hindi · Female)", "lang": "hi-IN", "gender": "Female", "group": "Hindi"},
    
    # English (India) Voices
    {"id": "en-IN-PrabhatNeural", "label": "Prabhat (Indian English · Male)", "lang": "en-IN", "gender": "Male", "group": "English (India)"},
    {"id": "en-IN-NeerjaNeural", "label": "Neerja (Indian English · Female)", "lang": "en-IN", "gender": "Female", "group": "English (India)"},

    # English (US) Multilingual / Mixed Voices
    {"id": "en-US-AndrewMultilingualNeural", "label": "Andrew (Hinglish/Multilingual · Male)", "lang": "en-US", "gender": "Male", "group": "Hinglish / Mixed"},
    {"id": "en-US-AvaMultilingualNeural", "label": "Ava (Hinglish/Multilingual · Female)", "lang": "en-US", "gender": "Female", "group": "Hinglish / Mixed"},
]


# --------------------------------------------------------------------------- #
# Text chunking
# --------------------------------------------------------------------------- #

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।॥;])\s+|\n+")


def _hard_split(unit: str, limit: int) -> list[str]:
    parts, rest = [], unit
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(window.rfind(" "), window.rfind(","), window.rfind("，"))
        if cut < limit * 0.5:
            cut = limit
        parts.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        parts.append(rest)
    return [p for p in parts if p]


def split_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    units: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for sentence in _SENTENCE_SPLIT.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            units.extend(_hard_split(sentence, limit) if len(sentence) > limit else [sentence])

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not unit:
            continue
        if not current:
            current = unit
        elif len(current) + 1 + len(unit) <= limit:
            current += " " + unit
        else:
            chunks.append(current)
            current = unit
    if current:
        chunks.append(current)
    return chunks


# --------------------------------------------------------------------------- #
# Speech synthesis (Edge TTS)
# --------------------------------------------------------------------------- #

class TTSError(Exception):
    pass


async def _synthesize_edge(text: str, voice_id: str, rate: float) -> bytes:
    import edge_tts
    # Convert rate (0.5x - 2.0x) to percentage string like "+10%" or "-20%"
    percent = round((rate - 1.0) * 100)
    rate_str = f"{percent:+d}%" if percent else "+0%"
    
    communicate = edge_tts.Communicate(text, voice_id, rate=rate_str)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    audio = buf.getvalue()
    if not audio:
        raise TTSError("Edge TTS returned empty audio.")
    return audio


def synthesize_chunk(text: str, voice_id: str, rate: float) -> bytes:
    try:
        return asyncio.run(_synthesize_edge(text, voice_id, rate))
    except Exception as exc:
        raise TTSError(f"Edge TTS error: {exc}") from None


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #

class Job:
    def __init__(self, text: str, voice: dict, rate: float, chunks: list[str]):
        self.id = uuid.uuid4().hex[:12]
        self.text = text
        self.voice = voice
        self.rate = rate
        self.provider = "edge-tts"
        self.chunks = chunks
        self.status = "queued"
        self.done = 0
        self.error = ""
        self.cancel = threading.Event()
        self.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.started = 0.0
        self.finished = 0.0
        self.filename = f"{self.id}.mp3"
        self.mime = "audio/mpeg"

    def snapshot(self) -> dict:
        elapsed = (self.finished or time.time()) - self.started if self.started else 0
        remaining = 0.0
        if self.done and self.status == "running" and elapsed:
            remaining = max(0.0, elapsed / self.done * (len(self.chunks) - self.done))
        return {
            "id": self.id,
            "status": self.status,
            "done": self.done,
            "total": len(self.chunks),
            "percent": round(self.done / len(self.chunks) * 100) if self.chunks else 100,
            "chars": len(self.text),
            "provider": self.provider,
            "voice": {"id": self.voice["id"], "label": self.voice["label"]},
            "rate": self.rate,
            "elapsed": round(elapsed, 1),
            "eta": round(remaining, 1),
            "error": self.error,
            "created_at": self.created_at,
            "preview": re.sub(r"\s+", " ", self.text)[:140],
            "filename": self.filename if self.status == "done" else "",
            "mime": self.mime,
        }


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def load_meta(job_id: str) -> dict | None:
    if not re.fullmatch(r"[a-f0-9]{12}", job_id or ""):
        return None
    path = OUTPUT_DIR / f"{job_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def run_job(job: Job) -> None:
    job.status = "running"
    job.started = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = OUTPUT_DIR / f".{job.id}.part"
    try:
        with open(tmp_path, "wb") as sink:
            for index, chunk in enumerate(job.chunks):
                if job.cancel.is_set():
                    job.status = "cancelled"
                    return
                audio = None
                last_error = None
                for attempt in range(4):
                    try:
                        audio = synthesize_chunk(chunk, job.voice["id"], job.rate)
                        break
                    except TTSError as exc:
                        last_error = exc
                        if job.cancel.is_set():
                            break
                        time.sleep(1.5 * (attempt + 1))
                if audio is None:
                    raise TTSError(str(last_error or "Synthesis failed."))
                sink.write(audio)
                job.done = index + 1

        if job.status == "cancelled":
            tmp_path.unlink(missing_ok=True)
            return

        final_path = OUTPUT_DIR / job.filename
        tmp_path.replace(final_path)

        job.finished = time.time()
        job.status = "done"
        meta = {**job.snapshot(), "file": job.filename}
        (OUTPUT_DIR / f"{job.id}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        job.finished = time.time()
        job.status = "error"
        job.error = str(exc)[:500]
        tmp_path.unlink(missing_ok=True)
        (OUTPUT_DIR / f"{job.id}.json").write_text(
            json.dumps(job.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")


def start_job(text: str, voice: dict, rate: float) -> Job:
    chunks = split_text(text)
    if not chunks:
        raise ValueError("Nothing to synthesize - the text is empty.")
    job = Job(text, voice, rate, chunks)
    with JOBS_LOCK:
        JOBS[job.id] = job
        finished = [j for j in JOBS.values() if j.status in ("done", "error", "cancelled")]
        if len(finished) > 50:
            for old in sorted(finished, key=lambda j: j.created_at)[: len(finished) - 50]:
                JOBS.pop(old.id, None)
    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return job


# --------------------------------------------------------------------------- #
# HTTP API
# --------------------------------------------------------------------------- #

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_CHARS * 8:
            raise ValueError("Invalid request body.")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:
        if "/api/" in (self.path or ""):
            return
        super().log_message(fmt, *args)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/api/config":
            return self.send_json({
                "provider": "edge-tts",
                "configured": True,
                "voices": EDGE_VOICES,
                "max_chars": MAX_CHARS,
                "chunk_chars": CHUNK_CHARS,
                "region": "",
                "model": "Microsoft Edge Neural",
                "setup": "",
            })

        if path == "/api/history":
            items = []
            if OUTPUT_DIR.exists():
                for meta in OUTPUT_DIR.glob("*.json"):
                    try:
                        data = json.loads(meta.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    if data.get("status") == "done" and (OUTPUT_DIR / data.get("file", "")).exists():
                        items.append({k: data.get(k) for k in (
                            "id", "preview", "chars", "provider", "voice", "rate",
                            "created_at", "file", "elapsed")})
            items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
            return self.send_json({"items": items[:40]})

        if path.startswith("/api/jobs/"):
            parts = path.strip("/").split("/")
            job_id = parts[2] if len(parts) > 2 else ""
            is_audio = len(parts) == 4 and parts[3] == "audio"
            job = JOBS.get(job_id)
            if job:
                if is_audio:
                    return self.serve_audio(job)
                return self.send_json(job.snapshot())

            meta = load_meta(job_id)
            if not meta:
                return self.send_json({"error": "Job not found."}, 404)
            if is_audio:
                file_path = OUTPUT_DIR / str(meta.get("file") or "")
                if meta.get("status") != "done" or not file_path.is_file():
                    return self.send_json({"error": "Audio is not available."}, 409)
                return self.send_audio_file(file_path, str(meta.get("mime") or "audio/mpeg"))
            return self.send_json(meta)

        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        try:
            if path == "/api/jobs":
                return self.create_job()
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job = JOBS.get(path.strip("/").split("/")[2])
                if not job:
                    return self.send_json({"error": "Job not found."}, 404)
                job.cancel.set()
                return self.send_json({"ok": True})
            return self.send_json({"error": "Not found."}, 404)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 400)

    def do_DELETE(self) -> None:
        path = self.path.split("?")[0]
        if not path.startswith("/api/jobs/"):
            return self.send_json({"error": "Not found."}, 404)
        job_id = path.strip("/").split("/")[2]
        if not re.fullmatch(r"[a-f0-9]{12}", job_id):
            return self.send_json({"error": "Job not found."}, 404)
        with JOBS_LOCK:
            job = JOBS.pop(job_id, None)
        if job:
            job.cancel.set()
        for suffix in (".mp3", ".wav", ".json", ".part"):
            (OUTPUT_DIR / f"{job_id}{suffix}").unlink(missing_ok=True)
        return self.send_json({"ok": True})

    def create_job(self) -> None:
        data = self.read_json()
        text = (data.get("text") or "").strip()
        if not text:
            raise ValueError("Paste some text first.")
        if len(text) > MAX_CHARS:
            raise ValueError(f"Text is {len(text):,} characters - the limit is {MAX_CHARS:,}.")
        rate = float(data.get("rate") or 1.0)
        if not 0.5 <= rate <= 2.0:
            raise ValueError("Speed must be between 0.5x and 2.0x.")
        voice_id = data.get("voice")
        voice = next((v for v in EDGE_VOICES if v["id"] == voice_id), EDGE_VOICES[0])
        job = start_job(text, voice, rate)
        return self.send_json(job.snapshot(), 201)

    def serve_audio(self, job: Job) -> None:
        path = OUTPUT_DIR / job.filename
        if job.status != "done" or not path.exists():
            return self.send_json({"error": "Audio is not ready."}, 409)
        return self.send_audio_file(path, job.mime)

    def send_audio_file(self, path: Path, mime: str) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range", "")
        match = re.match(r"bytes=(\d*)-(\d*)$", range_header.strip())
        if match and size:
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            elif match.group(2):
                start = max(0, size - int(match.group(2)))
            if start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
            status = 206

        length = max(0, end - start + 1)
        disposition = "attachment" if "download=1" in (self.path or "") else "inline"
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Disposition",
                         f'{disposition}; filename="vaani-{path.stem}.{path.suffix.lstrip(".")}"')
        self.end_headers()
        with open(path, "rb") as audio:
            audio.seek(start)
            remaining = length
            while remaining > 0:
                block = audio.read(min(65536, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


load_env()
MAX_CHARS = int(env("MAX_CHARS", "50000"))
CHUNK_CHARS = max(400, min(2500, int(env("CHUNK_CHARS", "2500"))))
PORT = int(env("PORT", "8000"))


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    url = f"http://127.0.0.1:{PORT}"
    print("\n  VaaniTTS (Microsoft Edge Neural Voice Studio)")
    print("  Engine : Microsoft Edge TTS (100% Free, Ultra-Natural, Male & Female Hindi Voices)")
    print(f"  Open   : {url}\n")
    if env("NO_BROWSER") != "1":
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
