from faster_whisper import WhisperModel
import json
from pathlib import Path

def transcribe_audio_cpu(audio_path, output_json, speaker="host"):
    model = WhisperModel(
        "medium",
        device="cpu",
        compute_type="int8"
    )

    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        word_timestamps=False,
        vad_filter=True
    )

    results = []

    for i, segment in enumerate(segments):
        results.append({
            "speaker": speaker,
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "start_timestamp": seconds_to_timestamp(segment.start),
            "end_timestamp": seconds_to_timestamp(segment.end),
            "text": segment.text.strip(),
            "order": i
        })

    Path(output_json).parent.mkdir(parents=True, exist_ok=True)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Saved transcript to {output_json}")


def seconds_to_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


if __name__ == "__main__":
    transcribe_audio_cpu(
        audio_path="inputs/guest.m4a",
        output_json="outputs/guest_transcript.json",
        speaker="guest"
    )