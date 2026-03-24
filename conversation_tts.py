"""
Multi-Engine Conversation TTS
==============================
Generates a multi-speaker conversation MP3 using one of four TTS engines,
selected via TTS_ENGINE in your .env file.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ENGINE         LATENCY   QUALITY   COST      EXTRA INSTALL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 elevenlabs     ~0.7s     ★★★★★    paid      (none)
 openai_tts     ~1.0s     ★★★★☆    paid      (none)
 amazon_polly   ~0.5s     ★★★★☆    paid*     pip install boto3
 gtts           ~1.5s     ★★★☆☆    FREE      pip install gtts
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * Polly has a generous free tier (5M chars/month for 12 months)

Setup:
    pip install requests pydub python-dotenv
    pip install boto3        # only for amazon_polly
    pip install gtts         # only for gtts

    Copy .env.example to .env and fill in your credentials.

Usage:
    python conversation_tts.py --input conversation.json
    python conversation_tts.py --input conversation.json --output out.mp3
    python conversation_tts.py --list-voices          # engine-aware

    CLI flags always override .env values:
    python conversation_tts.py --input conversation.json --engine gtts

JSON format (see conversation.json for a full example):
    {
      "voices": {
        "elevenlabs"  : { "doctor": "<voice_id>",  "patient": "<voice_id>" },
        "openai_tts"  : { "doctor": "nova",        "patient": "onyx"       },
        "amazon_polly": { "doctor": "Joanna",      "patient": "Matthew"    },
        "gtts"        : { "doctor": "en",          "patient": "en"         }
      },
      "voice_settings": {
        "doctor":  { "stability": 0.55, "similarity_boost": 0.75, "style": 0.25 },
        "patient": { "stability": 0.40, "similarity_boost": 0.80, "style": 0.50 }
      },
      "conversation": [
        { "speaker": "doctor",  "text": "How are you feeling?" },
        { "speaker": "patient", "text": "Not great, doctor."   }
      ]
    }
"""

from __future__ import annotations

import abc
import argparse
import json
import os
import sys
import time
import requests
from io import BytesIO
from pathlib import Path
from pydub import AudioSegment

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("Missing: pip install python-dotenv")

# Load .env from script directory, fall back to cwd
_env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_env_path if _env_path.exists() else Path(".env"))

# Silence gaps (milliseconds)
GAP_BETWEEN_LINES  = 700   # after every line
GAP_SPEAKER_CHANGE = 400   # extra when speaker changes


# ══════════════════════════════════════════════════════════════════════════════
#  BASE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TTSEngine(abc.ABC):
    """Abstract base — every engine implements synthesize() and list_voices()."""

    name: str = "base"

    @abc.abstractmethod
    def synthesize(self, text: str, voice: str, speaker: str,
                   voice_settings: dict | None) -> AudioSegment:
        """Return an AudioSegment for one line of text."""

    @abc.abstractmethod
    def list_voices(self) -> None:
        """Print available voices to stdout."""

    @staticmethod
    def _post_with_retry(url: str, headers: dict, payload: dict,
                         max_attempts: int = 3) -> requests.Response:
        for attempt in range(max_attempts):
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code == 429:
                wait = 2 ** attempt * 3
                print(f"    Rate limited — waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError("API rate limit exceeded after retries.")


# ══════════════════════════════════════════════════════════════════════════════
#  ENGINE 1 — ElevenLabs  (fastest premium, best voice cloning)
# ══════════════════════════════════════════════════════════════════════════════

class ElevenLabsEngine(TTSEngine):
    name = "elevenlabs"
    _BASE = "https://api.elevenlabs.io/v1"
    _DEFAULT_SETTINGS = {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.3,
        "use_speaker_boost": True,
    }

    def __init__(self, api_key: str, model_id: str = "eleven_multilingual_v2"):
        self.api_key  = api_key
        self.model_id = model_id

    def synthesize(self, text: str, voice: str, speaker: str,
                   voice_settings: dict | None) -> AudioSegment:
        settings = voice_settings or self._DEFAULT_SETTINGS
        resp = self._post_with_retry(
            url     = f"{self._BASE}/text-to-speech/{voice}",
            headers = {
                "xi-api-key"   : self.api_key,
                "Content-Type" : "application/json",
                "Accept"       : "audio/mpeg",
            },
            payload = {
                "text"          : text,
                "model_id"      : self.model_id,
                "voice_settings": settings,
            },
        )
        return AudioSegment.from_file(BytesIO(resp.content), format="mp3")

    def list_voices(self) -> None:
        resp = requests.get(f"{self._BASE}/voices",
                            headers={"xi-api-key": self.api_key})
        resp.raise_for_status()
        print(f"\n  {'ID':25s}  {'Name':30s}  Labels")
        print("  " + "-" * 76)
        for v in resp.json()["voices"]:
            print(f"  {v['voice_id']:25s}  {v['name']:30s}  {v.get('labels', {})}")


# ══════════════════════════════════════════════════════════════════════════════
#  ENGINE 2 — OpenAI TTS  (natural, 6 voices, easy setup)
# ══════════════════════════════════════════════════════════════════════════════

class OpenAITTSEngine(TTSEngine):
    name = "openai_tts"
    _VOICES = {
        "alloy"  : "Neutral, balanced",
        "echo"   : "Male, clear",
        "fable"  : "Expressive, British",
        "onyx"   : "Deep, authoritative male",
        "nova"   : "Friendly female",
        "shimmer": "Soft, warm female",
    }

    def __init__(self, api_key: str, model_id: str = "tts-1"):
        self.api_key  = api_key
        self.model_id = model_id

    def synthesize(self, text: str, voice: str, speaker: str,
                   voice_settings: dict | None) -> AudioSegment:
        resp = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type" : "application/json",
            },
            json = {
                "model"          : self.model_id,
                "input"          : text,
                "voice"          : voice,
                "response_format": "mp3",
            },
        )
        resp.raise_for_status()
        return AudioSegment.from_file(BytesIO(resp.content), format="mp3")

    def list_voices(self) -> None:
        print(f"\n  OpenAI TTS voices  (model: {self.model_id})\n")
        for name, desc in self._VOICES.items():
            print(f"  {name:10s}  {desc}")
        print("\n  Models: tts-1  (fast)  |  tts-1-hd  (higher quality, slower)")


# ══════════════════════════════════════════════════════════════════════════════
#  ENGINE 3 — Amazon Polly  (lowest latency, many languages)
# ══════════════════════════════════════════════════════════════════════════════

class AmazonPollyEngine(TTSEngine):
    name = "amazon_polly"

    def __init__(self, region: str = "us-east-1", engine: str = "neural"):
        try:
            import boto3
            self._client = boto3.client(
                "polly",
                region_name           = region
            )
        except ImportError:
            sys.exit("Amazon Polly requires boto3:  pip install boto3")
        self._engine = engine  # "neural" or "standard"

    def synthesize(self, text: str, voice: str, speaker: str,
                   voice_settings: dict | None) -> AudioSegment:
        resp = self._client.synthesize_speech(
            Text         = text,
            VoiceId      = voice,
            OutputFormat = "mp3",
            Engine       = self._engine,
            TextType     = "text",
        )
        return AudioSegment.from_file(
            BytesIO(resp["AudioStream"].read()), format="mp3"
        )

    def list_voices(self) -> None:
        paginator = self._client.get_paginator("describe_voices")
        print(f"\n  {'ID':20s}  {'Gender':8s}  {'Lang':10s}  {'Engines':18s}  Name")
        print("  " + "-" * 76)
        for page in paginator.paginate():
            for v in page["Voices"]:
                engines = ", ".join(v.get("SupportedEngines", []))
                print(f"  {v['Id']:20s}  {v['Gender']:8s}  "
                      f"{v['LanguageCode']:10s}  {engines:18s}  {v['Name']}")


# ══════════════════════════════════════════════════════════════════════════════
#  ENGINE 4 — gTTS  (free, no API key, uses Google Translate TTS)
# ══════════════════════════════════════════════════════════════════════════════

class GTTSEngine(TTSEngine):
    """
    Free Google TTS via the gTTS library.
    The 'voice' field in JSON = BCP-47 language code: 'en', 'en-uk', 'fr', 'ar', etc.
    No API key needed.
    """
    name = "gtts"

    def __init__(self, slow: bool = False):
        try:
            from gtts import gTTS as _gTTS
            self._gTTS = _gTTS
        except ImportError:
            sys.exit("gTTS requires:  pip install gtts")
        self._slow = slow

    def synthesize(self, text: str, voice: str, speaker: str,
                   voice_settings: dict | None) -> AudioSegment:
        tts = self._gTTS(text=text, lang=voice, slow=self._slow)
        buf = BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return AudioSegment.from_file(buf, format="mp3")

    def list_voices(self) -> None:
        try:
            from gtts.lang import tts_langs
        except ImportError:
            sys.exit("gTTS requires:  pip install gtts")
        print("\n  gTTS language codes:\n")
        for code, name in sorted(tts_langs().items()):
            print(f"  {code:10s}  {name}")


# ══════════════════════════════════════════════════════════════════════════════
#  ENGINE FACTORY
# ══════════════════════════════════════════════════════════════════════════════

SUPPORTED_ENGINES = ["elevenlabs", "openai_tts", "amazon_polly", "gtts"]


def build_engine(engine_name: str) -> TTSEngine:
    """Read credentials from environment and return the correct engine instance."""

    e = engine_name.lower().strip()

    if e == "elevenlabs":
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            sys.exit("Error: ELEVENLABS_API_KEY not set in .env")
        model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
        return ElevenLabsEngine(api_key=api_key, model_id=model_id)

    elif e == "openai_tts":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            sys.exit("Error: OPENAI_API_KEY not set in .env")
        model_id = os.getenv("OPENAI_TTS_MODEL", "tts-1")
        return OpenAITTSEngine(api_key=api_key, model_id=model_id)

    elif e == "amazon_polly":
        region = os.getenv("AWS_REGION", "us-east-1")
        engine = os.getenv("POLLY_ENGINE", "neural")
        return AmazonPollyEngine(region, engine)

    elif e == "gtts":
        slow = os.getenv("GTTS_SLOW", "false").lower() == "true"
        return GTTSEngine(slow=slow)

    else:
        sys.exit(
            f"Error: unknown TTS_ENGINE '{engine_name}'.\n"
            f"  Supported values: {', '.join(SUPPORTED_ENGINES)}"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  CONVERSATION RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def generate_conversation(
    engine            : TTSEngine,
    conversation      : list,
    voice_map         : dict,
    voice_settings_map: dict | None = None,
    gap_between       : int = GAP_BETWEEN_LINES,
    gap_speaker_change: int = GAP_SPEAKER_CHANGE,
) -> AudioSegment:
    """Synthesize every line and stitch them together with silence gaps."""

    combined     = AudioSegment.empty()
    prev_speaker = None

    for i, line in enumerate(conversation):
        speaker = line["speaker"]
        text    = line["text"]

        if speaker not in voice_map:
            print(f"  [WARNING] Unknown speaker '{speaker}' — skipping line {i+1}.")
            continue

        voice    = voice_map[speaker]
        settings = (voice_settings_map or {}).get(speaker)

        print(f"  [{i+1:02d}/{len(conversation)}] {speaker.upper():8s} "
              f"({voice})  ->  {text[:65]}{'...' if len(text) > 65 else ''}")

        segment = engine.synthesize(text, voice, speaker, settings)

        if prev_speaker and prev_speaker != speaker:
            combined += AudioSegment.silent(duration=gap_speaker_change)

        combined    += segment
        combined    += AudioSegment.silent(duration=gap_between)
        prev_speaker = speaker

    return combined


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description     = "Generate a multi-speaker conversation MP3 (multi-engine TTS).",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog          = (
            "Engines: elevenlabs | openai_tts | amazon_polly | gtts\n"
            "Set TTS_ENGINE in .env, or pass --engine on the CLI.\n"
            "Run --list-voices to see voices for the active engine."
        ),
    )
    parser.add_argument("--input",       default=None,
                        help="Path to conversation JSON file")
    parser.add_argument("--output",      default="conversation.mp3",
                        help="Output MP3 path (default: conversation.mp3)")
    parser.add_argument("--engine",      default=None,
                        help="TTS engine to use — overrides TTS_ENGINE in .env")
    parser.add_argument("--list-voices", action="store_true",
                        help="List voices for the active engine and exit")
    args = parser.parse_args()

    # Resolve engine: CLI > .env > default
    engine_name = args.engine or os.getenv("TTS_ENGINE", "elevenlabs")
    engine      = build_engine(engine_name)

    print(f"\n  Engine : {engine.name}")

    # List-voices mode (no --input needed)
    if args.list_voices:
        engine.list_voices()
        sys.exit(0)

    if not args.input:
        parser.error("--input is required (unless using --list-voices)")

    if not os.path.exists(args.input):
        sys.exit(f"Error: input file '{args.input}' not found.")

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Voice map: engine-specific section takes priority over a flat mapping
    all_voices = data.get("voices", {})
    voice_map  = all_voices.get(engine_name) or all_voices

    if not voice_map or not isinstance(voice_map, dict):
        sys.exit(
            f"Error: no voice mapping for engine '{engine_name}' in JSON.\n"
            f"  Add a '{engine_name}' key under 'voices', or provide a flat mapping."
        )

    conversation       = data.get("conversation", [])
    voice_settings_map = data.get("voice_settings")  # ElevenLabs only

    if not conversation:
        sys.exit("Error: 'conversation' list is empty.")

    print(f"  Input  : {args.input}")
    print(f"  Output : {args.output}")
    print(f"  Lines  : {len(conversation)}")
    print(f"  Voices : {voice_map}\n")

    audio = generate_conversation(
        engine             = engine,
        conversation       = conversation,
        voice_map          = voice_map,
        voice_settings_map = voice_settings_map,
    )

    audio = audio.normalize()
    audio.export(args.output, format="mp3", bitrate="192k")
    duration = len(audio) / 1000
    size_kb  = os.path.getsize(args.output) // 1024
    print(f"\n  Done!  '{args.output}'  ({duration:.1f}s, {size_kb} KB)")


if __name__ == "__main__":
    main()
