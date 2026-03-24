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

Folder layout (relative to this script):
    input/          ← place your JSON conversation files here
    output/         ← generated MP3s are saved here
    temp/           ← per-run temp folders created and deleted here
    .env            ← credentials & engine selection

Usage:
    python conversation_tts.py --input conversation.json
    python conversation_tts.py --input conversation.json --output result.mp3
    python conversation_tts.py --list-voices
    python conversation_tts.py --engine gtts --input conversation.json
"""

from __future__ import annotations

import abc
import argparse
import json
import os
import sys
import tempfile
import time
import requests
from pathlib import Path
from pydub import AudioSegment

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("Missing: pip install python-dotenv")

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
INPUT_DIR  = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR   = BASE_DIR / "temp"

# Load .env from script directory, fall back to cwd
_env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=_env_path if _env_path.exists() else Path(".env"))

# Silence gaps (milliseconds)
GAP_BETWEEN_LINES  = 700   # after every line
GAP_SPEAKER_CHANGE = 400   # extra when speaker changes

def _bytes_to_segment(data: bytes, fmt: str, tmp_dir: Path) -> AudioSegment:
    """
    Write raw audio bytes to a file in tmp_dir, load it with pydub, then
    return the AudioSegment.  Passing a real file path — not a BytesIO —
    means pydub never needs to create its own temp files internally.
    The file stays in tmp_dir and is deleted when the run's TemporaryDirectory
    context manager exits.
    """
    suffix = f".{fmt}"
    fd, fpath = tempfile.mkstemp(suffix=suffix, dir=tmp_dir)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return AudioSegment.from_file(fpath, format=fmt)
    except Exception:
        # mkstemp file is already in tmp_dir, so it will be cleaned up there.
        raise



# ══════════════════════════════════════════════════════════════════════════════
#  BASE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TTSEngine(abc.ABC):
    """Abstract base — every engine implements synthesize() and list_voices()."""

    name: str = "base"

    @abc.abstractmethod
    def synthesize(self, text: str, voice: str, speaker: str,
                   voice_settings: dict | None,
                   tmp_dir: Path) -> AudioSegment:
        """
        Return an AudioSegment for one line of text.
        tmp_dir is a per-run temporary directory; write any intermediate files
        there — they are deleted automatically after the run completes.
        """

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
                   voice_settings: dict | None, tmp_dir: Path) -> AudioSegment:
        settings = voice_settings or self._DEFAULT_SETTINGS
        resp = self._post_with_retry(
            url     = f"{self._BASE}/text-to-speech/{voice}",
            headers = {
                "xi-api-key"  : self.api_key,
                "Content-Type": "application/json",
                "Accept"      : "audio/mpeg",
            },
            payload = {
                "text"          : text,
                "model_id"      : self.model_id,
                "voice_settings": settings,
            },
        )
        return _bytes_to_segment(resp.content, "mp3", tmp_dir)

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
                   voice_settings: dict | None, tmp_dir: Path) -> AudioSegment:
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
        return _bytes_to_segment(resp.content, "mp3", tmp_dir)

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

    def __init__(self, aws_access_key: str, aws_secret_key: str,
                 region: str = "us-east-1", engine: str = "neural"):
        try:
            import boto3
            self._client = boto3.client(
                "polly",
                region_name           = region,
                aws_access_key_id     = aws_access_key,
                aws_secret_access_key = aws_secret_key,
            )
        except ImportError:
            sys.exit("Amazon Polly requires boto3:  pip install boto3")
        self._engine = engine  # "neural" or "standard"

    def synthesize(self, text: str, voice: str, speaker: str,
                   voice_settings: dict | None, tmp_dir: Path) -> AudioSegment:
        resp = self._client.synthesize_speech(
            Text         = text,
            VoiceId      = voice,
            OutputFormat = "mp3",
            Engine       = self._engine,
            TextType     = "text",
        )
        # AudioStream is a streaming body — read it fully into memory
        return _bytes_to_segment(resp["AudioStream"].read(), "mp3", tmp_dir)

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

    gTTS requires writing to a real file before pydub can decode it reliably,
    so we write to tmp_dir and delete it automatically after the run.
    """
    name = "gtts"

    def __init__(self, slow: bool = False):
        try:
            from gtts import gTTS as _gTTS
            self._gTTS = _gTTS
        except ImportError:
            sys.exit("gTTS requires:  pip install gtts")
        self._slow  = slow
        self._count = 0   # unique name per line within the tmp dir

    def synthesize(self, text: str, voice: str, speaker: str,
                   voice_settings: dict | None, tmp_dir: Path) -> AudioSegment:
        self._count += 1
        tmp_file = tmp_dir / f"gtts_{self._count:04d}.mp3"
        tts = self._gTTS(text=text, lang=voice, slow=self._slow)
        tts.save(str(tmp_file))                           # written to tmp_dir
        segment = AudioSegment.from_file(tmp_file, format="mp3")
        # tmp_file will be wiped with the entire tmp_dir at run end
        return segment

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
        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        if not access_key or not secret_key:
            sys.exit(
                "Error: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY not set in .env"
            )
        region = os.getenv("AWS_REGION", "us-east-1")
        engine = os.getenv("POLLY_ENGINE", "neural")
        return AmazonPollyEngine(access_key, secret_key, region, engine)

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
    tmp_dir           : Path,
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

        segment = engine.synthesize(text, voice, speaker, settings, tmp_dir)

        if prev_speaker and prev_speaker != speaker:
            combined += AudioSegment.silent(duration=gap_speaker_change)

        combined    += segment
        combined    += AudioSegment.silent(duration=gap_between)
        prev_speaker = speaker

    return combined


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def resolve_input(name: str) -> Path:
    """
    Resolve an input filename to an absolute path under INPUT_DIR.
    Accepts:
      - bare filename  : "conversation.json"  → input/conversation.json
      - relative path  : "subdir/conv.json"   → input/subdir/conv.json
      - absolute path  : "/abs/path/conv.json" (used as-is, no INPUT_DIR prefix)
    """
    p = Path(name)
    if p.is_absolute():
        return p
    candidate = INPUT_DIR / p
    return candidate


def resolve_output(name: str, input_path: Path) -> Path:
    """
    Resolve an output filename to an absolute path under OUTPUT_DIR.
    If no name is given, derive it from the input filename stem.
    """
    if name:
        p = Path(name)
        if p.is_absolute():
            return p
        return OUTPUT_DIR / p
    # Default: same stem as input, .mp3 extension, in OUTPUT_DIR
    return OUTPUT_DIR / (input_path.stem + ".mp3")


def list_input_files() -> None:
    """Print all JSON files currently in INPUT_DIR."""
    if not INPUT_DIR.exists():
        print(f"  Input folder does not exist yet: {INPUT_DIR}")
        return
    files = sorted(INPUT_DIR.glob("*.json"))
    if not files:
        print(f"  No JSON files found in {INPUT_DIR}")
        return
    print(f"\n  JSON files in {INPUT_DIR}:\n")
    for f in files:
        print(f"    {f.name}")


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description     = "Generate a multi-speaker conversation MP3 (multi-engine TTS).",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog          = (
            "Input JSON files are read from:  ./input/\n"
            "Output MP3 files are written to: ./output/\n"
            "Temp files are cleaned up automatically after each run.\n\n"
            "Engines: elevenlabs | openai_tts | amazon_polly | gtts\n"
            "Set TTS_ENGINE in .env, or pass --engine on the CLI."
        ),
    )
    parser.add_argument("--input",       default=None,
                        help="JSON filename inside input/ (e.g. conversation.json)")
    parser.add_argument("--output",      default=None,
                        help="MP3 filename inside output/ (default: <input_stem>.mp3)")
    parser.add_argument("--engine",      default=None,
                        help="TTS engine to use — overrides TTS_ENGINE in .env")
    parser.add_argument("--list-voices", action="store_true",
                        help="List voices for the active engine and exit")
    parser.add_argument("--list-inputs", action="store_true",
                        help="List available JSON files in the input/ folder and exit")
    args = parser.parse_args()

    # ── Ensure input/ and output/ directories exist ──
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # ── List input files mode ──
    if args.list_inputs:
        list_input_files()
        sys.exit(0)

    # ── Resolve engine ──
    engine_name = args.engine or os.getenv("TTS_ENGINE", "elevenlabs")
    engine      = build_engine(engine_name)
    print(f"\n  Engine : {engine.name}")

    # ── List voices mode ──
    if args.list_voices:
        engine.list_voices()
        sys.exit(0)

    # ── Require --input for generation ──
    if not args.input:
        parser.error(
            "--input is required.\n"
            f"  Place your JSON file in {INPUT_DIR} then run:\n"
            "  python conversation_tts.py --input conversation.json"
        )

    input_path  = resolve_input(args.input)
    output_path = resolve_output(args.output, input_path)

    if not input_path.exists():
        sys.exit(
            f"Error: input file not found: {input_path}\n"
            f"  Make sure it exists inside {INPUT_DIR}"
        )

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Voice map: engine-specific section takes priority over flat mapping
    all_voices = data.get("voices", {})
    voice_map  = all_voices.get(engine_name) or all_voices

    if not voice_map or not isinstance(voice_map, dict):
        sys.exit(
            f"Error: no voice mapping for engine '{engine_name}' in JSON.\n"
            f"  Add a '{engine_name}' key under 'voices', or provide a flat mapping."
        )

    conversation       = data.get("conversation", [])
    voice_settings_map = data.get("voice_settings")   # ElevenLabs only

    if not conversation:
        sys.exit("Error: 'conversation' list is empty.")

    print(f"  Input  : {input_path}")
    print(f"  Output : {output_path}")
    print(f"  Lines  : {len(conversation)}")
    print(f"  Voices : {voice_map}\n")

    # ── Run inside a temporary directory — wiped automatically on exit ──
    #
    # We also redirect tempfile.tempdir to tmp_dir for the entire synthesis
    # block. This ensures that pydub's internal ffmpeg calls (which create
    # NamedTemporaryFiles when decoding BytesIO objects) land inside tmp_dir
    # rather than in the cwd or the OS default temp location.
    with tempfile.TemporaryDirectory(prefix="tts_run_", dir=TEMP_DIR) as _tmp:
        tmp_dir = Path(_tmp)
        print(f"  Temp   : {tmp_dir}  (auto-deleted on completion)\n")

        try:
            audio = generate_conversation(
                engine             = engine,
                conversation       = conversation,
                voice_map          = voice_map,
                tmp_dir            = tmp_dir,
                voice_settings_map = voice_settings_map,
            )
        except Exception as exc:
            sys.exit(f"\n  Error during synthesis: {exc}")

    # tmp_dir and every file inside it are deleted by the TemporaryDirectory
    # context manager — including all per-line audio files written by each engine.
    print(f"\n  Temp files cleaned up.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio = audio.normalize()
    audio.export(str(output_path), format="mp3", bitrate="192k")

    duration = len(audio) / 1000
    size_kb  = output_path.stat().st_size // 1024
    print(f"  Done!  {output_path}  ({duration:.1f}s, {size_kb} KB)")


if __name__ == "__main__":
    main()