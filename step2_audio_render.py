# Step 3: Audio rendering
import argparse
import json
import os
import re
import tempfile
from pathlib import Path

from pydub import AudioSegment, effects
from pydub.silence import detect_nonsilent


# ============================================================
# Time helpers
# ============================================================

def time_to_ms(t) -> int:
    """
    Supports:
    - numeric seconds: 12.0, 39.27
    - string seconds: "12.0"
    - MM:SS: "05:32"
    - HH:MM:SS: "01:05:32"
    - HH:MM:SS.mmm: "01:05:32.500"
    """
    if t is None:
        raise ValueError("Time value is None")

    if isinstance(t, (int, float)):
        return int(float(t) * 1000)

    t = str(t).strip()

    try:
        return int(float(t) * 1000)
    except ValueError:
        pass

    parts = t.split(":")

    if len(parts) == 2:
        minutes = int(parts[0])
        seconds = float(parts[1])
        return int((minutes * 60 + seconds) * 1000)

    if len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return int((hours * 3600 + minutes * 60 + seconds) * 1000)

    raise ValueError(f"Unsupported time format: {t}")


def ms_to_time(ms: int) -> str:
    total = max(0, ms) / 1000
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    s = total % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return f"{m:02d}:{s:06.3f}"


def set_temp_dir(temp_dir: str | None):
    if temp_dir:
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        os.environ["TMP"] = temp_dir
        os.environ["TEMP"] = temp_dir
        tempfile.tempdir = temp_dir


# ============================================================
# Decision JSON adapters
# ============================================================

def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _sort_highlight(item):
    return (
        _safe_int(item.get("recommended_position"), 9999),
        _safe_int(item.get("highlight_id"), 9999),
    )


def _sort_story(item):
    return (
        _safe_int(item.get("story_order"), 999999),
        _safe_int(item.get("order"), 999999),
    )


def normalize_clip_item(item: dict, clip_group: str, sequence_index: int) -> dict:
    """
    Convert both old final_sequence items and new story/highlight items
    into one common format that the audio cutter can understand.
    """
    x = dict(item)
    x["_clip_group"] = clip_group
    x["_sequence_index"] = sequence_index

    # The old script prints and sorts by order. New story JSON uses story_order/highlight_id.
    if "order" not in x:
        if "story_order" in x:
            x["order"] = x["story_order"]
        elif "highlight_id" in x:
            x["order"] = f"H{x['highlight_id']}"
        else:
            x["order"] = sequence_index

    # Keep a clear reference to original timeline position when it exists.
    if "original_order" not in x:
        if isinstance(x.get("source_orders"), list) and x["source_orders"]:
            x["original_order"] = x["source_orders"][0]
        elif "source_order" in x:
            x["original_order"] = x["source_order"]
        elif "order" in item:
            x["original_order"] = item.get("order")

    if "source_orders" not in x:
        if "source_order" in x:
            x["source_orders"] = [x["source_order"]]
        elif "original_order" in x:
            x["source_orders"] = [x["original_order"]]
        else:
            x["source_orders"] = []

    return x


def _normalise_sequence_mode_name(sequence_mode: str) -> str:
    """Accept common CLI aliases so old commands keep working."""
    mode = (sequence_mode or "auto").strip().lower().replace("_", "-")
    aliases = {
        "final-sequence": "final",
        "finalsequence": "final",
        "timeline": "final",
        "timeline-sequence": "final",
        "old": "final",
        "old-final": "final",
        "story-with-highlight": "story-with-highlights",
        "story-highlights": "story-with-highlights",
        "story-with-cold-open": "story-with-highlights",
    }
    return aliases.get(mode, mode)


def _debug_decision_shape(decision: dict) -> str:
    """Compact summary printed when the selected mode reads zero clips."""
    known = [
        "final_sequence",
        "story_sequence",
        "highlight_sequence",
        "chapters",
        "story_chapters",
        "removed_segments",
        "discarded_segments",
    ]
    parts = []
    for key in known:
        value = decision.get(key)
        if isinstance(value, list):
            parts.append(f"{key}={len(value)}")
        elif value is not None:
            parts.append(f"{key}=present")
    return ", ".join(parts) if parts else f"top_level_keys={list(decision.keys())[:12]}"


def get_sequences_from_decision(decision: dict, sequence_mode: str):
    """
    Returns: mode, highlight_sequence, main_sequence

    Supported JSON formats:
    1. Old / strict edit_decision.json:
       { "metadata": {...}, "final_sequence": [...], "discarded_segments": [...] }

    2. Story edit decision JSON:
       { "highlight_sequence": [...], "story_sequence": [...] }

    Important compatibility rule:
    If the user requests story-with-highlights but the file only has final_sequence,
    automatically fall back to final_sequence instead of rendering 0 clips.
    """
    requested_mode = _normalise_sequence_mode_name(sequence_mode)

    if requested_mode == "auto":
        if decision.get("story_sequence"):
            mode = "story-with-highlights"
        elif decision.get("final_sequence"):
            mode = "final"
        elif decision.get("highlight_sequence"):
            mode = "highlights"
        else:
            mode = "final"
    else:
        mode = requested_mode

    highlights = []
    main = []
    idx = 1

    if mode == "final":
        raw = decision.get("final_sequence", [])
        main = [normalize_clip_item(x, "main", i + 1) for i, x in enumerate(raw)]
        return mode, [], main

    if mode in {"highlights", "story-with-highlights"}:
        raw_highlights = sorted(decision.get("highlight_sequence", []), key=_sort_highlight)
        for item in raw_highlights:
            highlights.append(normalize_clip_item(item, "highlight", idx))
            idx += 1

    if mode in {"story", "story-with-highlights"}:
        raw_story = sorted(decision.get("story_sequence", []), key=_sort_story)
        for item in raw_story:
            main.append(normalize_clip_item(item, "main", idx))
            idx += 1

    # Compatibility fallback: many of the refined balanced files intentionally keep
    # the original edit_decision structure and store clips in final_sequence.
    # Without this, --sequence-mode story-with-highlights prints 0 clips.
    if not main and mode in {"story", "story-with-highlights"} and decision.get("final_sequence"):
        print(
            "[WARN] story_sequence not found or empty; "
            "falling back to final_sequence. Use --sequence-mode final for this JSON."
        )
        mode = "final"
        raw = decision.get("final_sequence", [])
        main = [normalize_clip_item(x, "main", i + 1) for i, x in enumerate(raw)]
        highlights = []
        return mode, highlights, main

    if mode == "highlights":
        return mode, highlights, []

    if not highlights and not main:
        print(f"[WARN] No clips found for sequence_mode={sequence_mode!r}. JSON shape: {_debug_decision_shape(decision)}")

    return mode, highlights, main


# ============================================================
# Audio refinement helpers
# ============================================================

def estimate_host_duration_ms(text: str, min_ms: int, max_ms: int, pad_ms: int, cps: float) -> int:
    """
    Estimate host speaking duration from transcript text.
    This prevents host clips from continuing into faint guest background audio.
    """
    if not text:
        return min_ms

    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text))
    effective_chars = chinese_chars + english_words * 1.7
    pauses = len(re.findall(r"[，。！？、,.!?；;：:]", text))

    estimated_sec = effective_chars / cps + pauses * 0.12 + pad_ms / 1000
    estimated_ms = int(estimated_sec * 1000)

    return max(min_ms, min(max_ms, estimated_ms))


def trim_leading_silence_soft(
    clip: AudioSegment,
    silence_thresh: int,
    min_silence_len: int = 300,
    pad_start: int = 120,
):
    ranges = detect_nonsilent(
        clip,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh,
        seek_step=10,
    )
    if not ranges:
        return clip
    start = max(0, ranges[0][0] - pad_start)
    return clip[start:]


def remove_adjacent_guest_overlap(sequence, tolerance_ms: int):
    """
    Story JSON is non-linear, so we must NOT sort by original order.
    This only trims tiny overlaps between adjacent guest clips in the new story order.
    """
    fixed = []
    prev_kept = None

    for item in sequence:
        item = dict(item)
        source = item.get("source")

        if source != "guest" or not prev_kept or prev_kept.get("source") != "guest":
            fixed.append(item)
            prev_kept = item
            continue

        try:
            start_ms = time_to_ms(item["start"])
            end_ms = time_to_ms(item["end"])
            prev_end_ms = time_to_ms(prev_kept["end"])
        except Exception:
            fixed.append(item)
            prev_kept = item
            continue

        if start_ms < prev_end_ms - tolerance_ms:
            if end_ms <= prev_end_ms + tolerance_ms:
                item["_skip_reason"] = "adjacent_guest_duplicate_or_fully_overlapped"
                fixed.append(item)
                continue

            overlap = prev_end_ms - start_ms
            if overlap <= 5000:
                item["start"] = ms_to_time(prev_end_ms)
                item["note"] = "adjacent_guest_overlap_trimmed"

        fixed.append(item)
        prev_kept = item

    return fixed


def process_voice(clip: AudioSegment, source: str, target_dbfs: float, host_gain_db: float) -> AudioSegment:
    if len(clip) == 0:
        return clip

    clip = clip.set_channels(1)
    clip = clip.high_pass_filter(80)
    clip = clip.low_pass_filter(12500)

    clip = effects.compress_dynamic_range(
        clip,
        threshold=-25.0,
        ratio=1.8,
        attack=8,
        release=140,
    )

    if clip.dBFS != float("-inf"):
        gain = target_dbfs - clip.dBFS
        gain = max(min(gain, 6), -10)
        clip = clip.apply_gain(gain)

    if source == "host":
        clip = clip.apply_gain(host_gain_db)

    return clip


def append_opening_or_ending(final_audio: AudioSegment, path: str, label: str, args) -> AudioSegment:
    audio = AudioSegment.from_file(path)
    audio = process_voice(audio, label, args.target_dbfs, 0)
    audio = audio.fade_in(args.fade_in).fade_out(args.fade_out)
    return final_audio + audio


# ============================================================
# Main cutter
# ============================================================

def cut_sequence(sequence, final_audio, audio_files, args, refined_items, stats, sequence_name="main"):
    last_chapter_id = None
    first_main_clip = True

    if args.guest_overlap_mode == "adjacent":
        sequence = remove_adjacent_guest_overlap(sequence, args.guest_overlap_tolerance)

    for item in sequence:
        order = item.get("order")
        source = item.get("source")
        clip_group = item.get("_clip_group", sequence_name)
        chapter_id = item.get("chapter_id")

        if item.get("_skip_reason"):
            print(f"[SKIP] {clip_group} order={order} {source}: {item['_skip_reason']}")
            stats["skipped"] += 1
            refined_items.append(item)
            continue

        if source not in {"host", "guest"}:
            continue

        try:
            start_ms = time_to_ms(item["start"])
            original_end_ms = time_to_ms(item["end"])
        except Exception as e:
            print(f"[SKIP] {clip_group} order={order}: bad time: {e}")
            stats["skipped"] += 1
            continue

        audio = audio_files[source]
        start_ms = max(0, start_ms)
        original_end_ms = min(len(audio), original_end_ms)

        if original_end_ms <= start_ms:
            print(f"[SKIP] {clip_group} order={order} {source}: invalid range")
            stats["skipped"] += 1
            continue

        # Add chapter breathing room for the story-reordered main episode.
        if (
            clip_group == "main"
            and args.chapter_gap > args.gap
            and not first_main_clip
            and chapter_id is not None
            and last_chapter_id is not None
            and chapter_id != last_chapter_id
        ):
            final_audio += AudioSegment.silent(duration=args.chapter_gap - args.gap)

        actual_end_ms = original_end_ms

        if source == "host" and args.refine_host_by_text:
            estimated_duration = estimate_host_duration_ms(
                text=item.get("text", ""),
                min_ms=args.host_min_ms,
                max_ms=args.host_max_ms,
                pad_ms=args.host_text_pad_ms,
                cps=args.host_chars_per_second,
            )
            estimated_end_ms = min(len(audio), start_ms + estimated_duration)

            if estimated_end_ms < original_end_ms:
                actual_end_ms = estimated_end_ms
                stats["host_cut_count"] += 1
                stats["host_saved_ms"] += original_end_ms - actual_end_ms

        clip = audio[start_ms:actual_end_ms]
        before_len = original_end_ms - start_ms

        if args.trim_leading:
            thresh = args.host_leading_thresh if source == "host" else args.guest_leading_thresh
            clip = trim_leading_silence_soft(
                clip,
                silence_thresh=thresh,
                min_silence_len=args.leading_silence_len,
                pad_start=args.leading_pad,
            )

        clip = process_voice(
            clip,
            source=source,
            target_dbfs=args.target_dbfs,
            host_gain_db=args.host_gain,
        )

        fade_in = min(args.fade_in, max(0, len(clip) // 4))
        fade_out = min(args.fade_out, max(0, len(clip) // 4))
        clip = clip.fade_in(fade_in).fade_out(fade_out)

        if len(clip) < args.min_clip_ms:
            print(f"[SKIP] {clip_group} order={order} {source}: too short after trim")
            stats["skipped"] += 1
            continue

        final_audio += clip

        if clip_group == "highlight":
            gap_ms = args.highlight_gap
        elif item.get("needs_transition"):
            gap_ms = args.transition_gap
        else:
            gap_ms = args.gap
        final_audio += AudioSegment.silent(duration=gap_ms)

        stats["used"] += 1
        stats["total_before_ms"] += before_len
        stats["total_after_ms"] += len(clip)

        refined_item = dict(item)
        refined_item["start"] = ms_to_time(start_ms)
        refined_item["end"] = ms_to_time(actual_end_ms)
        refined_item["actual_duration_seconds"] = round(len(clip) / 1000, 3)
        refined_item["actual_gap_after_ms"] = gap_ms

        if source == "host" and actual_end_ms < original_end_ms:
            refined_item["original_end"] = ms_to_time(original_end_ms)
            refined_item["note"] = "host_end_refined_by_text_duration"

        refined_items.append(refined_item)

        chapter_info = ""
        if chapter_id is not None:
            chapter_info = f" | chapter={chapter_id}"

        print(
            f"[CUT] {clip_group:<9} | order={str(order).rjust(4)} | {source:<5} | "
            f"{ms_to_time(start_ms)} -> {ms_to_time(actual_end_ms)} "
            f"(original end {ms_to_time(original_end_ms)}) | "
            f"{before_len/1000:.2f}s -> {len(clip)/1000:.2f}s{chapter_info}"
        )

        if clip_group == "main":
            first_main_clip = False
            last_chapter_id = chapter_id

    return final_audio


def build_episode(args):
    set_temp_dir(args.temp_dir)

    with open(args.decision, "r", encoding="utf-8") as f:
        decision = json.load(f)

    mode, highlights, main_sequence = get_sequences_from_decision(decision, args.sequence_mode)

    if args.guest_overlap_mode == "chronological" and mode != "final":
        print("[WARN] guest-overlap-mode=chronological is unsafe for story JSON. Using adjacent mode instead.")
        args.guest_overlap_mode = "adjacent"

    if args.guest_overlap_mode == "chronological" and mode == "final":
        # Old behavior: sort by old order, only useful for old timeline JSON.
        main_sequence = sorted(main_sequence, key=lambda x: _safe_int(x.get("order"), 0))
        main_sequence = remove_adjacent_guest_overlap(main_sequence, args.guest_overlap_tolerance)

    audio_files = {
        "host": AudioSegment.from_file(args.host),
        "guest": AudioSegment.from_file(args.guest),
    }

    final_audio = AudioSegment.silent(duration=0)
    refined_items = []
    stats = {
        "used": 0,
        "skipped": 0,
        "host_cut_count": 0,
        "host_saved_ms": 0,
        "total_before_ms": 0,
        "total_after_ms": 0,
    }

    print(f"Decision mode: {mode}")
    print(f"Highlights: {len(highlights)}")
    print(f"Main clips: {len(main_sequence)}")

    # Recommended story structure:
    # cold_open_highlights -> opening_music -> story_reordered_main_episode -> ending_music
    if args.opening and (not highlights or args.opening_position == "before_all"):
        final_audio = append_opening_or_ending(final_audio, args.opening, "opening", args)
        final_audio += AudioSegment.silent(duration=args.opening_gap)

    if highlights:
        final_audio = cut_sequence(
            highlights,
            final_audio,
            audio_files,
            args,
            refined_items,
            stats,
            sequence_name="highlight",
        )
        if args.opening and args.opening_position == "after_highlights":
            final_audio += AudioSegment.silent(duration=args.cold_open_to_opening_gap)
            final_audio = append_opening_or_ending(final_audio, args.opening, "opening", args)
            final_audio += AudioSegment.silent(duration=args.opening_gap)

    if main_sequence:
        final_audio = cut_sequence(
            main_sequence,
            final_audio,
            audio_files,
            args,
            refined_items,
            stats,
            sequence_name="main",
        )

    if args.ending:
        final_audio = append_opening_or_ending(final_audio, args.ending, "ending", args)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    final_audio.export(output, format=args.format, bitrate=args.bitrate)

    if args.save_refined_json:
        refined = dict(decision)
        refined["actual_cut_sequence"] = refined_items
        refined["metadata"] = dict(refined.get("metadata", {}))
        refined["metadata"]["story_audio_render"] = {
            "script": "auto_audio_editor_v5_story.py",
            "sequence_mode": mode,
            "opening_position": args.opening_position,
            "highlight_count_used": len(highlights),
            "main_clip_count_used": len(main_sequence),
            "host_end_refinement": {
                "method": "estimated_from_host_text_duration" if args.refine_host_by_text else "disabled",
                "host_cut_count": stats["host_cut_count"],
                "host_saved_minutes": round(stats["host_saved_ms"] / 1000 / 60, 2),
                "chars_per_second": args.host_chars_per_second,
                "host_text_pad_ms": args.host_text_pad_ms,
                "host_max_ms": args.host_max_ms,
            },
        }

        refined_path = output.with_name(output.stem + "_actual_cut_sequence.json")
        with open(refined_path, "w", encoding="utf-8") as f:
            json.dump(refined, f, ensure_ascii=False, indent=2)
        print(f"Actual cut JSON: {refined_path}")

    print("\nDone.")
    print(f"Used clips: {stats['used']}")
    print(f"Skipped clips: {stats['skipped']}")
    print(f"Host clips refined: {stats['host_cut_count']}")
    print(f"Host background/overhang removed: {stats['host_saved_ms']/1000/60:.2f} min")
    print(f"Clip duration before: {stats['total_before_ms']/1000/60:.2f} min")
    print(f"Clip duration after: {stats['total_after_ms']/1000/60:.2f} min")
    print(f"Final duration: {len(final_audio)/1000/60:.2f} min")
    print(f"Output: {output}")


def main():
    parser = argparse.ArgumentParser(
        description="Podcast editor v5 fixed: supports final_sequence JSON and story/highlight JSON."
    )
    parser.add_argument("--decision", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--guest", required=True)
    parser.add_argument("--opening", default=None)
    parser.add_argument("--ending", default=None)
    parser.add_argument("--output", default="final_episode_v5_story.mp3")
    parser.add_argument("--format", default="mp3")
    parser.add_argument("--bitrate", default="192k")
    parser.add_argument("--temp-dir", default=None)

    parser.add_argument(
        "--sequence-mode",
        choices=[
            "auto",
            "final",
            "final_sequence",
            "final-sequence",
            "timeline",
            "story",
            "highlights",
            "story-with-highlights",
        ],
        default="auto",
        help=(
            "auto: detect JSON structure. "
            "final/final_sequence/timeline: read final_sequence. "
            "story-with-highlights: read highlight_sequence + story_sequence, "
            "with automatic fallback to final_sequence if story_sequence is missing."
        ),
    )
    parser.add_argument(
        "--opening-position",
        choices=["after_highlights", "before_all"],
        default="after_highlights",
        help="For story JSON, recommended is after_highlights: cold open first, then opening music.",
    )

    parser.add_argument("--refine-host-by-text", action="store_true")
    parser.add_argument("--host-chars-per-second", type=float, default=5.2)
    parser.add_argument("--host-text-pad-ms", type=int, default=900)
    parser.add_argument("--host-min-ms", type=int, default=1800)
    parser.add_argument("--host-max-ms", type=int, default=45000)

    parser.add_argument("--trim-leading", action="store_true")
    parser.add_argument("--host-leading-thresh", type=int, default=-38)
    parser.add_argument("--guest-leading-thresh", type=int, default=-48)
    parser.add_argument("--leading-silence-len", type=int, default=300)
    parser.add_argument("--leading-pad", type=int, default=120)

    parser.add_argument("--target-dbfs", type=float, default=-19.0)
    parser.add_argument("--host-gain", type=float, default=-2.5)

    parser.add_argument("--gap", type=int, default=550)
    parser.add_argument("--highlight-gap", type=int, default=280)
    parser.add_argument("--transition-gap", type=int, default=900)
    parser.add_argument("--chapter-gap", type=int, default=1200)
    parser.add_argument("--opening-gap", type=int, default=900)
    parser.add_argument("--cold-open-to-opening-gap", type=int, default=700)
    parser.add_argument("--fade-in", type=int, default=20)
    parser.add_argument("--fade-out", type=int, default=45)
    parser.add_argument("--min-clip-ms", type=int, default=500)

    parser.add_argument(
        "--guest-overlap-mode",
        choices=["off", "adjacent", "chronological"],
        default="adjacent",
        help="Use adjacent for story JSON. chronological is only for old timeline final_sequence.",
    )
    parser.add_argument("--guest-overlap-tolerance", type=int, default=200)
    parser.add_argument("--save-refined-json", action="store_true")

    args = parser.parse_args()
    build_episode(args)


if __name__ == "__main__":
    main()
