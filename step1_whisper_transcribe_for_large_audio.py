import json
import math
from pathlib import Path
from pydub import AudioSegment
from faster_whisper import WhisperModel


def seconds_to_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def split_audio(audio_path, chunk_dir, chunk_minutes=5):
    audio = AudioSegment.from_file(audio_path)
    chunk_dir = Path(chunk_dir)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunk_ms = chunk_minutes * 60 * 1000
    total_ms = len(audio)

    chunks = []

    for i in range(math.ceil(total_ms / chunk_ms)):
        start_ms = i * chunk_ms
        end_ms = min((i + 1) * chunk_ms, total_ms)

        chunk = audio[start_ms:end_ms]
        chunk_path = chunk_dir / f"chunk_{i:03d}.wav"
        chunk.export(chunk_path, format="wav")

        chunks.append({
            "path": str(chunk_path),
            "offset_seconds": start_ms / 1000
        })

    return chunks


def transcribe_audio_cpu_chunked(
    audio_path,
    output_json,
    speaker="host",
    model_size="small",
    chunk_minutes=5
):
    model = WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8"
    )

    chunks = split_audio(
        audio_path=audio_path,
        chunk_dir=f"outputs/temp_chunks_{speaker}",
        chunk_minutes=chunk_minutes
    )

    results = []
    order = 0

    for chunk_info in chunks:
        chunk_path = chunk_info["path"]
        offset = chunk_info["offset_seconds"]

        print(f"Transcribing: {chunk_path}")

        segments, info = model.transcribe(
            chunk_path,
            beam_size=1,
            vad_filter=True,
            word_timestamps=False
        )

        for segment in segments:
            start = offset + segment.start
            end = offset + segment.end

            results.append({
                "speaker": speaker,
                "start": round(start, 3),
                "end": round(end, 3),
                "start_timestamp": seconds_to_timestamp(start),
                "end_timestamp": seconds_to_timestamp(end),
                "text": segment.text.strip(),
                "order": order
            })

            order += 1

    Path(output_json).parent.mkdir(parents=True, exist_ok=True)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Saved transcript to {output_json}")


if __name__ == "__main__":
    transcribe_audio_cpu_chunked(
        audio_path="inputs/guest.m4a",
        output_json="outputs/guest_transcript.json",
        speaker="guest",
        model_size="small",
        chunk_minutes=5
    )