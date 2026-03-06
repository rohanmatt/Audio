"""
speech_to_text.py
Deepgram Nova-3 speech-to-text using the official Deepgram Python SDK.

Two modes:
  1. transcribe_file()  — for pre-recorded audio bytes (Streamlit file upload).
  2. LiveTranscriber    — context-manager wrapper around the Deepgram WebSocket
                          connection for real-time mic streaming.
"""

import threading
from typing import Callable

import httpx
from deepgram import DeepgramClient
from deepgram.core.events import EventType
from dotenv import load_dotenv
load_dotenv()

# ── FILE-BASED STT (upload mode) ─────────────────────────────────────────────

def transcribe_file(audio_bytes: bytes, api_key: str, mimetype: str = "audio/wav") -> str:
    """
    Transcribe a complete audio file using Deepgram's pre-recorded REST endpoint.
    Fastest option for single-shot file uploads from Streamlit.

    Args:
        audio_bytes: Raw audio content from a file upload.
        api_key:     Deepgram API key.
        mimetype:    MIME type of the audio (e.g. "audio/wav", "audio/mpeg").

    Returns:
        Transcript string, or an error string beginning with "[STT error:".
    """
    url = (
        "https://api.deepgram.com/v1/listen"
        "?model=nova-3&smart_format=true&language=en"
    )
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": mimetype,
    }
    try:
        resp = httpx.post(url, headers=headers, content=audio_bytes, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        transcript = (
            data["results"]["channels"][0]["alternatives"][0]["transcript"]
        )
        return transcript.strip()
    except httpx.HTTPStatusError as e:
        return f"[STT error: HTTP {e.response.status_code} — {e.response.text[:200]}]"
    except Exception as e:
        return f"[STT error: {e}]"


def mime_from_filename(filename: str) -> str:
    """Infer MIME type from uploaded filename extension."""
    ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "wav":  "audio/wav",
        "mp3":  "audio/mpeg",
        "m4a":  "audio/mp4",
        "webm": "audio/webm",
        "ogg":  "audio/ogg",
    }.get(ext, "audio/wav")


# ── LIVE STREAMING STT (WebSocket mode) ──────────────────────────────────────

class LiveTranscriber:
    """
    Wraps the Deepgram SDK WebSocket connection for real-time transcription.
    Mirrors the pattern from the official Deepgram SDK sample exactly.

    Usage:

        def on_transcript(text: str):
            print("Got:", text)

        with LiveTranscriber(api_key=DEEPGRAM_API_KEY, on_transcript=on_transcript) as lt:
            lt.send(audio_chunk_bytes)   # call repeatedly with mic chunks

    The on_transcript callback fires from a background thread on every
    non-empty transcript result.
    """

    def __init__(
        self,
        api_key: str,
        on_transcript: Callable[[str], None],
        model: str = "nova-3",
        language: str = "en",
        interim_results: bool = False,
    ):
        self._api_key       = api_key
        self._on_transcript = on_transcript
        self._model         = model
        self._language      = language
        self._interim       = interim_results
        self._connection    = None
        self._ready         = threading.Event()

    # ── SDK event handlers (match official sample) ──
    def _on_open(self, _):
        self._ready.set()

    def _on_message(self, result):
        channel = getattr(result, "channel", None)
        if not channel or not hasattr(channel, "alternatives"):
            return
        transcript = channel.alternatives[0].transcript
        is_final   = getattr(result, "is_final", True)
        if transcript and (is_final or self._interim):
            self._on_transcript(transcript)

    def _on_error(self, error):
        print(f"[LiveTranscriber] WebSocket error: {error}")

    # ── context manager ──
    def __enter__(self):
        client = DeepgramClient(api_key=self._api_key)
        self._connection = client.listen.v1.connect(
            model=self._model,
            language=self._language,
        ).__enter__()
        self._connection.on(EventType.OPEN,    self._on_open)
        self._connection.on(EventType.MESSAGE, self._on_message)
        self._connection.on(EventType.ERROR,   self._on_error)
        self._ready.wait(timeout=10)   # block until WebSocket is open
        return self

    def __exit__(self, *args):
        if self._connection:
            self._connection.__exit__(*args)

    def send(self, audio_chunk: bytes) -> None:
        """Push a raw audio chunk into the live transcription stream."""
        if self._connection:
            self._connection.send_media(audio_chunk)

    def stream_url(self, url: str) -> None:
        """
        Stream a remote audio URL directly into Deepgram in a background thread.
        Mirrors the threading pattern from the official SDK sample.
        """
        def _stream():
            self._ready.wait()
            with httpx.stream("GET", url, follow_redirects=True) as response:
                for chunk in response.iter_bytes():
                    self.send(chunk)

        threading.Thread(target=_stream, daemon=True).start()