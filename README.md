# Conversation TTS — Multi-Engine Voice Generator

Convert a JSON conversation script into a natural-sounding MP3 with distinct voices for each speaker. Supports four TTS engines — swap between them with a single line in your `.env`.

---

## Engines

| Engine | Latency | Quality | Cost | Dependency |
|---|---|---|---|---|
| `elevenlabs` *(default)* | ~0.7s/line | ★★★★★ | Paid | — |
| `openai_tts` | ~1.0s/line | ★★★★☆ | Paid | — |
| `amazon_polly` | ~0.5s/line | ★★★★☆ | Paid* | `boto3` |
| `gtts` | ~1.5s/line | ★★★☆☆ | **Free** | `gtts` |

\* Polly has a free tier: 5 million characters/month for the first 12 months.

---

## Installation

### 1. Clone / download the files

```
conversation_tts.py
conversation.json
.env.example
requirements.txt
README.md
```

### 2. Install Python dependencies

```bash
# Core (always required)
pip install requests pydub python-dotenv

# Amazon Polly only
pip install boto3

# gTTS only
pip install gtts
```

Or install everything at once:

```bash
pip install -r requirements.txt
```

### 3. Install ffmpeg (required by pydub for MP3 handling)

| OS | Command |
|---|---|
| macOS | `brew install ffmpeg` |
| Ubuntu / Debian | `sudo apt install ffmpeg` |
| Windows | Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH |

### 4. Configure your `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials (see [Configuration](#configuration) below).

---

## Quick Start

```bash
# Run with default engine (elevenlabs)
python conversation_tts.py --input conversation.json

# Specify output file
python conversation_tts.py --input conversation.json --output heart_attack.mp3

# Switch engine via CLI flag (overrides .env)
python conversation_tts.py --input conversation.json --engine gtts

# List available voices for the active engine
python conversation_tts.py --list-voices
```

---

## Configuration

### `.env` file

Copy `.env.example` to `.env` and fill in the values for the engine(s) you want to use.

```env
# ── Pick one engine ────────────────────────────────────────────
TTS_ENGINE=elevenlabs
#TTS_ENGINE=openai_tts
#TTS_ENGINE=amazon_polly
#TTS_ENGINE=gtts

# ── ElevenLabs ─────────────────────────────────────────────────
ELEVENLABS_API_KEY=your_key_here
ELEVENLABS_MODEL_ID=eleven_multilingual_v2

# ── OpenAI TTS ─────────────────────────────────────────────────
OPENAI_API_KEY=your_key_here
OPENAI_TTS_MODEL=tts-1

# ── Amazon Polly ───────────────────────────────────────────────
AWS_ACCESS_KEY_ID=your_key_here
AWS_SECRET_ACCESS_KEY=your_secret_here
AWS_REGION=us-east-1
POLLY_ENGINE=neural

# ── gTTS (no key needed) ───────────────────────────────────────
GTTS_SLOW=false
```

**Priority:** CLI `--engine` flag → `TTS_ENGINE` in `.env` → defaults to `elevenlabs`.

> ⚠️ Add `.env` to your `.gitignore` — never commit API keys.

---

## Conversation JSON Format

The JSON file has three sections:

```json
{
  "voices": { ... },
  "voice_settings": { ... },
  "conversation": [ ... ]
}
```

### `voices`

Define a voice per speaker for each engine. The script automatically picks the right section based on `TTS_ENGINE`.

```json
"voices": {
  "elevenlabs"  : { "doctor": "21m00Tcm4TlvDq8ikWAM", "patient": "pNInz6obpgDQGcFmaJgB" },
  "openai_tts"  : { "doctor": "nova",    "patient": "onyx"    },
  "amazon_polly": { "doctor": "Joanna",  "patient": "Matthew" },
  "gtts"        : { "doctor": "en",      "patient": "en-uk"   }
}
```

### `voice_settings` *(optional, ElevenLabs only)*

Fine-tune the expressiveness of each speaker independently.

```json
"voice_settings": {
  "doctor":  { "stability": 0.55, "similarity_boost": 0.75, "style": 0.25 },
  "patient": { "stability": 0.40, "similarity_boost": 0.80, "style": 0.50 }
}
```

| Parameter | Range | Effect |
|---|---|---|
| `stability` | 0 – 1 | Higher = more consistent, less expressive |
| `similarity_boost` | 0 – 1 | Higher = closer to the original voice |
| `style` | 0 – 1 | Higher = more expressive / emotional |
| `use_speaker_boost` | bool | Enhances voice clarity |

### `conversation`

An ordered list of `{ "speaker", "text" }` objects. Speaker names must match keys in `voices`.

```json
"conversation": [
  { "speaker": "doctor",  "text": "How are you feeling today?" },
  { "speaker": "patient", "text": "Not great, I have chest pain." }
]
```

You can add as many speakers as you like — just add them to both `voices` and the conversation lines.

---

## Voice Reference

### ElevenLabs — free pre-made voices

| Voice ID | Name | Character |
|---|---|---|
| `21m00Tcm4TlvDq8ikWAM` | Rachel | Calm female |
| `pNInz6obpgDQGcFmaJgB` | Adam | Deep male |
| `ErXwobaYiN019PkySvjV` | Antoni | Warm male |
| `EXAVITQu4vr4xnSDxMaL` | Bella | Soft female |
| `TxGEqnHWrfWFTfGW9XjX` | Josh | Young male |
| `VR6AewLTigWG4xSOukaG` | Arnold | Authoritative male |
| `AZnzlk1XvdvUeBnXmlld` | Domi | Confident female |
| `MF3mGyEYCl7XYWbV9V6O` | Elli | Emotional female |

Run `--list-voices` to see all voices on your account:
```bash
python conversation_tts.py --list-voices
```

### OpenAI TTS voices

| Voice | Character |
|---|---|
| `alloy` | Neutral, balanced |
| `echo` | Male, clear |
| `fable` | Expressive, British |
| `onyx` | Deep, authoritative male |
| `nova` | Friendly female |
| `shimmer` | Soft, warm female |

### Amazon Polly — recommended neural voices (English)

| Voice ID | Gender | Accent |
|---|---|---|
| `Joanna` | Female | US English |
| `Matthew` | Male | US English |
| `Amy` | Female | British English |
| `Brian` | Male | British English |
| `Emma` | Female | British English |
| `Olivia` | Female | Australian English |

### gTTS — language codes

| Code | Language |
|---|---|
| `en` | English (US) |
| `en-uk` | English (UK) |
| `ar` | Arabic |
| `fr` | French |
| `de` | German |
| `es` | Spanish |

Run `--list-voices` with `TTS_ENGINE=gtts` to see all ~60 supported languages.

---

## Getting API Keys

**ElevenLabs**
1. Sign up at [elevenlabs.io](https://elevenlabs.io)
2. Go to Profile → API Key

**OpenAI**
1. Sign up at [platform.openai.com](https://platform.openai.com)
2. Go to API Keys → Create new secret key

**Amazon Polly**
1. Sign in to [AWS Console](https://console.aws.amazon.com)
2. Create an IAM user with the `AmazonPollyFullAccess` policy
3. Generate an Access Key for that user

**gTTS** — no key needed, uses Google Translate TTS for free.

---

## Project Structure

```
.
├── conversation_tts.py   # Main script
├── conversation.json     # Example conversation with all engine voices
├── .env                  # Your credentials (never commit this)
├── .env.example          # Template — copy to .env
├── requirements.txt      # Python dependencies
└── README.md
```

---

## Extending with a New Engine

1. Create a class inheriting from `TTSEngine`
2. Implement `synthesize()` and `list_voices()`
3. Add a branch in `build_engine()`
4. Add the engine's voice mapping to your JSON

```python
class MyCustomEngine(TTSEngine):
    name = "my_engine"

    def synthesize(self, text, voice, speaker, voice_settings):
        # call your API, return AudioSegment
        ...

    def list_voices(self):
        print("my voice list")
```

---

## License

MIT
