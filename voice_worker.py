"""Voice worker: a separate process the dashboard starts after launch, so
the speech model's heavy imports never slow the dashboard down.

Protocol: JSON, one object per line.
  stdin  (commands): {"cmd": "start" | "stop" | "cancel" | "quit"}
  stdout (events):   {"event": "loading"}
                     {"event": "ready", "model": "base", "device": "cpu"}
                     {"event": "listening"}
                     {"event": "level", "value": 0.0-1.0}
                     {"event": "partial", "committed": "...", "pending": "..."}
                     {"event": "finishing"}
                     {"event": "final", "text": "...", "language": "en" | ""}
                     {"event": "no_speech"} / {"event": "cancelled"}
                     {"event": "error", "message": "..."}

The worker exits when stdin closes, i.e. when the dashboard goes away.

    python voice_worker.py [--model base] [--device auto|cpu|cuda]
                           [--language auto|en|de] [--silence 2.0]
                           [--audio-file test.wav]   # testing: file instead of mic
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import wave

import numpy as np

SAMPLE_RATE = 16000
BLOCK = 1600  # 100 ms
NO_SPEECH_TIMEOUT = 8.0
MAX_SECONDS = 180.0

_emit_lock = threading.Lock()


def emit(event: str, **data):
    line = json.dumps({"event": event, **data}, ensure_ascii=False)
    with _emit_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def _normalize(word: str) -> str:
    return word.strip().strip(".,!?;:\"'").casefold()




# ==============================================================
# MODEL
# ==============================================================


class Transcriber:
    """Loads the model in the background; audio can be recorded meanwhile."""

    def __init__(self, model_name: str, device: str, language: str):
        self.model_name = model_name
        self.device_preference = device
        self.language = None if language == "auto" else language
        self.model = None
        self.device = ""
        self.ready = threading.Event()
        self.failed = False
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        emit("loading")
        try:
            import ctranslate2
            from faster_whisper import WhisperModel
        except ImportError as exc:
            self._fail(f"Voice dependencies missing ({exc.name}). Install requirements-voice.txt.")
            return

        candidates = []
        if self.device_preference in ("auto", "cuda") and ctranslate2.get_cuda_device_count() > 0:
            candidates.append(("cuda", "float16"))
        candidates.append(("cpu", "int8"))

        last_error = None
        for device, compute_type in candidates:
            try:
                model = WhisperModel(self.model_name, device=device, compute_type=compute_type)
                # A GPU can be detected but still fail at runtime (missing
                # cuBLAS/cuDNN); a warm-up run catches that here.
                list(model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), beam_size=1)[0])
            except Exception as exc:
                last_error = exc
                continue

            self.model = model
            self.device = device
            self.ready.set()
            emit("ready", model=self.model_name, device=device)
            return

        self._fail(f"Could not load the speech model: {last_error}")

    def _fail(self, message: str):
        self.failed = True
        self.ready.set()
        emit("error", message=message)

    def transcribe(self, audio: np.ndarray, language: str | None):
        """Text of the whole clip, plus faster-whisper's info (language)."""

        segments, info = self.model.transcribe(
            audio,
            language=language,
            beam_size=1,
            # Whisper invents words ("you", "thanks") when fed silence;
            # dropping non-speech first prevents that.
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
        )
        text = " ".join(segment.text.strip() for segment in segments)
        return " ".join(text.split()), info


# ==============================================================
# AUDIO SOURCES
# ==============================================================


class MicrophoneSource:
    def __init__(self, on_audio):
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=BLOCK,
            callback=lambda data, frames, t, status: on_audio(data[:, 0].copy()),
        )

    def start(self):
        self._stream.start()

    def stop(self):
        self._stream.stop()
        self._stream.close()


class FileSource:
    """Plays a WAV file in real time, then silence - for tests."""

    def __init__(self, path: str, on_audio):
        with wave.open(path) as wav:
            frames = wav.readframes(wav.getnframes())
        self._audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        self._on_audio = on_audio
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._play, daemon=True).start()

    def _play(self):
        position = 0
        while self._running:
            block = self._audio[position : position + BLOCK]
            if len(block) < BLOCK:
                block = np.concatenate([block, np.zeros(BLOCK - len(block), dtype=np.float32)])
            self._on_audio(block)
            position += BLOCK
            time.sleep(BLOCK / SAMPLE_RATE)

    def stop(self):
        self._running = False


# ==============================================================
# RECORDING SESSION
# ==============================================================


class Session:
    def __init__(self, transcriber: Transcriber, silence_seconds: float, audio_file: str | None):
        self.transcriber = transcriber
        self.silence_seconds = silence_seconds

        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._cancelled = False
        self._speech_seen = False
        self._speech_end = 0.0  # seconds into the recording where speech was last heard
        self._last_level = 0.0

        self._source = FileSource(audio_file, self._on_audio) if audio_file else MicrophoneSource(self._on_audio)
        self.thread = threading.Thread(target=self._run, daemon=True)

    # ---- control ----------------------------------------------------

    def start(self):
        self._source.start()
        emit("listening")
        threading.Thread(target=self._monitor, daemon=True).start()
        self.thread.start()

    def stop(self):
        self._stop.set()

    def cancel(self):
        self._cancelled = True
        self._stop.set()

    # ---- audio ------------------------------------------------------

    def _on_audio(self, block: np.ndarray):
        with self._lock:
            self._chunks.append(block)

        now = time.monotonic()
        if now - self._last_level >= 0.06:
            self._last_level = now
            rms = float(np.sqrt(np.mean(block**2)))
            emit("level", value=round(min(1.0, (rms / 0.1) ** 0.5), 3))

    def _audio(self) -> np.ndarray:
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._chunks)

    # ---- silence detection (independent of transcription speed) -----

    def _monitor(self):
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        options = VadOptions(min_speech_duration_ms=150, min_silence_duration_ms=100)
        started = time.monotonic()

        while not self._stop.wait(0.25):
            elapsed = time.monotonic() - started
            audio = self._audio()
            recent = audio[-int(self.silence_seconds * SAMPLE_RATE) :]
            if len(recent) < SAMPLE_RATE // 2:
                continue

            speech = get_speech_timestamps(recent, options)
            speaking = bool(speech)
            if speaking:
                self._speech_seen = True
                self._speech_end = (len(audio) - len(recent) + speech[-1]["end"]) / SAMPLE_RATE
            elif self._speech_seen and elapsed >= self.silence_seconds:
                self._stop.set()
            elif not self._speech_seen and elapsed >= NO_SPEECH_TIMEOUT:
                self._stop.set()

            if elapsed >= MAX_SECONDS:
                self._stop.set()

    # ---- transcription ----------------------------------------------

    def _run(self):
        try:
            self._transcribe_live()
        except Exception as exc:  # never leave the dashboard waiting
            emit("error", message=f"Transcription failed: {exc}")
        finally:
            self._source.stop()

    def _transcribe_live(self):
        """Re-transcribe the whole recording on every pass.

        Cutting the audio at word timestamps to save work proved unreliable
        (Whisper's timestamps are too imprecise; words got split or lost),
        and notes are short, so each pass sees everything. "Settled" words
        (unchanged since the previous pass) are only a display hint.
        """

        transcriber = self.transcriber
        language = transcriber.language
        guess = language or ""  # best guess so far, passed on to the note cleanup
        previous: list[str] = []
        last_pass_end = 0.0

        while not self._stop.is_set():
            if not transcriber.ready.is_set() or transcriber.failed:
                self._stop.wait(0.1)
                continue

            audio = self._audio()
            total = len(audio) / SAMPLE_RATE
            if total < 0.5 or total - last_pass_end < 0.3:
                self._stop.wait(0.1)
                continue

            text, info = transcriber.transcribe(audio, language)
            if language is None and total >= 2.0 and info.language_probability >= 0.5:
                language = info.language  # keep it stable for the rest of the recording
            guess = language or info.language or guess

            words = text.split()
            settled = 0
            while (
                settled < min(len(words), len(previous))
                and _normalize(words[settled]) == _normalize(previous[settled])
            ):
                settled += 1

            emit("partial", committed=" ".join(words[:settled]), pending=" ".join(words[settled:]))
            previous = words
            last_pass_end = total

        if self._cancelled:
            emit("cancelled")
            return

        emit("finishing")
        transcriber.ready.wait()
        if transcriber.failed:
            return

        # Usually the last live pass already heard everything (you paused
        # before auto-stop); otherwise run one more pass up to the last speech.
        if last_pass_end >= self._speech_end + 0.3:
            text = " ".join(previous)
        else:
            audio = self._audio()
            end = min(len(audio), int((self._speech_end + 0.5) * SAMPLE_RATE))
            text = ""
            if end >= SAMPLE_RATE // 4:
                text, info = transcriber.transcribe(audio[:end], language)
                guess = language or info.language or guess

        if not self._speech_seen or not text:
            emit("no_speech")
        else:
            emit("final", text=text, language=guess)


# ==============================================================
# MAIN LOOP
# ==============================================================


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="base")
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    parser.add_argument("--language", default="auto")
    parser.add_argument("--silence", type=float, default=2.0)
    parser.add_argument("--audio-file")
    args = parser.parse_args()

    # Keep stdout for the protocol only; library warnings go to stderr.
    sys.stdout.reconfigure(encoding="utf-8")

    if sys.platform == "win32":
        import ctypes

        BELOW_NORMAL_PRIORITY_CLASS = 0x4000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)

    transcriber = Transcriber(args.model, args.device, args.language)
    session: Session | None = None

    for line in sys.stdin:
        try:
            command = json.loads(line).get("cmd")
        except (json.JSONDecodeError, AttributeError):
            continue

        if command == "start":
            if session is None or not session.thread.is_alive():
                try:
                    session = Session(transcriber, args.silence, args.audio_file)
                    session.start()
                except Exception as exc:
                    session = None
                    emit("error", message=f"Microphone unavailable: {exc}")
        elif command == "stop" and session is not None:
            session.stop()
        elif command == "cancel" and session is not None:
            session.cancel()
        elif command == "quit":
            break

    if session is not None:
        session.cancel()
        session.thread.join(timeout=2)


if __name__ == "__main__":
    main()
