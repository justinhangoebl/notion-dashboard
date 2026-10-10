"""Check the microphone and speech models: records a few seconds and
transcribes them with each model that can run on this machine.

    python -m notion_dashboard.voice.check        # 8 seconds
    python -m notion_dashboard.voice.check 12     # 12 seconds
"""

from __future__ import annotations

import sys
import time

SAMPLE_RATE = 16000


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0

    try:
        import ctranslate2
        import numpy as np
        import sounddevice as sd
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(f"Voice dependencies missing ({exc.name}). Run:\n  pip install -e '.[voice]'")

    device = sd.query_devices(kind="input")
    print(f"Microphone: {device['name']}")

    for remaining in (3, 2, 1):
        print(f"Recording in {remaining}...", end="\r", flush=True)
        time.sleep(1)
    print(f"Recording {seconds:.0f}s - speak now (German or English)...")

    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    audio = audio[:, 0]

    peak = float(np.abs(audio).max())
    print(f"Done. Peak level {peak:.2f}")
    if peak < 0.01:
        print(
            "\nThe recording is silent. Check Windows Settings -> Privacy & security -> Microphone ->\n"
            '"Let desktop apps access your microphone", and that the right input device is the default.'
        )
        return

    configs = [("base", "cpu", "int8")]
    if ctranslate2.get_cuda_device_count() > 0:
        configs.append(("large-v3-turbo", "cuda", "float16"))

    for name, device_name, compute_type in configs:
        try:
            model = WhisperModel(name, device=device_name, compute_type=compute_type)
            start = time.perf_counter()
            segments, info = model.transcribe(audio, beam_size=1)
            text = " ".join(s.text.strip() for s in segments)
            elapsed = time.perf_counter() - start
            print(f"\n[{name} on {device_name}] {elapsed:.2f}s, language {info.language} ({info.language_probability:.0%})")
            print(f"  {text or '(nothing recognised)'}")
        except Exception as exc:
            print(f"\n[{name} on {device_name}] failed: {exc}")


if __name__ == "__main__":
    main()
