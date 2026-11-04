# VaaniTTS

Paste up to **50,000 characters** of Hindi, English or Hinglish, click once, and get a
single downloadable audio file. Runs locally on your Mac — no build step, no npm install,
no Python packages.

```
tts/
├── server.py          # stdlib web server + chunking + speech engines
├── static/            # the whole UI (HTML/CSS/JS)
├── output/            # generated audio + history (created on first run)
├── .env               # your API keys (never commit this)
└── .env.example
```

## 1. Pick an engine

| Engine | Free allowance | Best for | Key |
|---|---|---|---|
| **Azure AI Speech** | **500,000 neural characters / month, every month** | Best free option — 10 full 50k conversions per month. Strong Hindi + Indian English + multilingual (Hinglish) voices. | [Create a Speech resource](https://portal.azure.com) → Keys and Endpoint |
| **Sarvam AI** | ₹100 credits on signup (~33,000 characters on Bulbul) | Most natural Indian-language voices, great Hinglish handling | [dashboard.sarvam.ai](https://dashboard.sarvam.ai) |
| **Browser voices** | Free, unlimited | Quick previews only — cannot export audio files | not included in this app |

For 50k-character runs, **Azure's 500k/month free tier** is the practical choice.
(Google Cloud TTS also has a free monthly allowance, but its voices are weaker for Hindi
and its REST API caps each request at ~5k bytes.)

> Without any key the app still starts in **test mode**, producing silent audio so you can
> try the full flow.

## 2. Configure

```bash
cd tts
cp .env.example .env
```

Open `.env` and paste your key:

```ini
AZURE_SPEECH_KEY=your_key_here
AZURE_SPEECH_REGION=centralindia     # the region of your Speech resource
```

(or set `SARVAM_API_KEY=...` instead — the app auto-detects whichever key is present)

## 3. Run

```bash
python3 server.py
```

It opens <http://127.0.0.1:8000> automatically. To use another port:
`PORT=8080 python3 server.py`. On macOS you can also just double-click **`start.command`**.

## How it works

1. Your text is split at sentence boundaries into chunks of ≤1,800 characters
   (handles `।`, `.`, `?`, `!`, line breaks; long sentences are split on word boundaries).
2. Each chunk is sent to the speech engine one by one, with live progress and ETA.
3. Audio is streamed into one MP3 and saved in `output/`, together with a metadata JSON.
4. The UI plays it and offers a download. Every finished conversion stays in
   **Recent conversions** so you can replay or re-download it later.

50k characters ≈ 55–65 minutes of audio and takes roughly 1–3 minutes to generate,
depending on the engine and network.

## Features

- **50,000 character** paste limit with live character / word / duration estimate
- Hindi, English (India) and **multilingual Hinglish** voices
- Speed control (0.6×–1.6×)
- Live progress bar, ETA, cancel
- One-click MP3 download, playback, and a persistent local history
- Drag & drop `.txt` / `.md` files
- Draft autosave, `⌘/Ctrl + Enter` to convert
- Everything local: keys stay in `.env`, audio stays in `output/`

## Troubleshooting

| Symptom | Fix |
|---|---|
| `401` / `403` | Key is wrong or belongs to a different region. Copy the key + region from the Speech resource's *Keys and Endpoint* page. |
| `429` / quota | Free monthly characters used up, or requests too fast. The app retries automatically 3×; wait and retry. |
| `Engine not configured` | No `.env`, or the server needs a restart after editing `.env`. |
| Voice sounds robotic | Try `hi-IN-SwaraNeural` (Hindi) or `en-US-AvaMultilingualNeural` (Hinglish). Multilingual voices are the most natural for mixed text. |
| Long text fails | Keep `CHUNK_CHARS=1800`. If your network is slow, try `CHUNK_CHARS=900`. |
