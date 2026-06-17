# AI Audio Editing Pipeline

An AI-assisted podcast audio editing pipeline that automatically transcribes host and guest audio, generates structured editing decisions with a large language model, and renders a final edited episode based on the generated JSON decision file.

This project is designed for interview-style podcast production, especially when the host and guest are recorded on separate audio tracks.

---

## Project Purpose

The goal of this project is to reduce the amount of manual work required in podcast editing.

The pipeline helps with:

* Transcribing long host and guest audio files
* Preparing structured transcript JSON files
* Using a large language model to generate an edit decision file
* Reordering the conversation into a more engaging podcast structure
* Selecting short highlight clips for the cold open
* Rendering the final edited audio automatically
* Preserving an interview-style flow with host questions and guest answers

---

## Project Structure

```text
AI_Audio_Editing/
├── inputs/
│   ├── host.m4a
│   ├── guest.m4a
│   ├── opening.m4a
│   └── ending.m4a
│
├── outputs/
│   ├── host_transcript.json
│   ├── guest_transcript.json
│   └── story_edit_decision.json
│
├── prompts/
│   └── clean_merge_prompt.txt
│
├── step1_whisper_transcribe.py
├── step1_whisper_transcribe_for_large_audio.py
├── step2_audio_render.py
├── config.py
├── main.py
└── README.md
```

---

## Requirements

Before running the project, make sure you have the following installed:

* Python 3.9+
* FFmpeg
* Whisper
* pydub

Install Python dependencies:

```bash
pip install -U openai-whisper pydub
```

FFmpeg is required for reading and exporting audio files such as `.m4a`, `.mp3`, and `.wav`.

You can check whether FFmpeg is installed correctly by running:

```bash
ffmpeg -version
```

---

## Input Files

Place the following files inside the `inputs/` folder:

```text
inputs/
├── host.m4a
├── guest.m4a
├── opening.m4a
└── ending.m4a
```

File descriptions:

| File          | Description                  |
| ------------- | ---------------------------- |
| `host.m4a`    | The full host audio track    |
| `guest.m4a`   | The full guest audio track   |
| `opening.m4a` | Opening music or intro audio |
| `ending.m4a`  | Ending music or outro audio  |

---

## Workflow Overview

The project runs in three main stages:

1. Transcribe host and guest audio with Whisper
2. Generate an edit decision JSON with a large language model
3. Render the final edited podcast audio

---

## Step 1: Transcribe Audio with Whisper

Use the Step 1 scripts to transcribe the host and guest audio into JSON transcript files.

For normal-sized audio files, use:

```bash
python step1_whisper_transcribe.py
```

For large audio files, such as long guest recordings, use:

```bash
python step1_whisper_transcribe_for_large_audio.py
```

The large-audio version is designed to split long audio into smaller chunks before transcription, making it more suitable for long podcast recordings.

Expected output files:

```text
outputs/
├── host_transcript.json
└── guest_transcript.json
```

---

## Step 2: Generate the Edit Decision File

After generating the host and guest transcript JSON files, upload the following files to a large language model such as ChatGPT:

```text
outputs/host_transcript.json
outputs/guest_transcript.json
prompts/clean_merge_prompt.txt
```

The prompt file instructs the model to:

* Match host questions with guest answers
* Remove irrelevant content such as silence, setup, water breaks, device issues, and small talk
* Detect whether host segments contain guest speech
* Adjust suspicious host timestamps when the recorded duration is too long
* Select short highlight clips for the cold open
* Reorder the interview based on story, opinion, and emotion
* Preserve an interview-style structure instead of turning the episode into a guest monologue

The expected output is:

```text
outputs/story_edit_decision.json
```

This JSON file is the main edit decision file used by the rendering script.

---

## Step 3: Render the Final Edited Audio

Run the audio rendering script with the generated edit decision JSON.

Example command:

```bash
python step2_audio_render.py --decision "./outputs/story_edit_decision.json" --host "./inputs/host.m4a" --guest "./inputs/guest.m4a" --opening "./inputs/opening.m4a" --ending "./inputs/ending.m4a" --output "./final_cutting.m4a" --format ipod --temp-dir "E:\honey\CV_cut1\outputs\temp" --sequence-mode story-with-highlights --opening-position after_highlights --trim-leading --host-text-pad-ms 800 --host-chars-per-second 5.3 --host-gain -4 --gap 550 --highlight-gap 280 --transition-gap 900 --chapter-gap 1200 --fade-in 25 --fade-out 60 --save-refined-json
```

---

## Output

After running the render script, the final edited podcast audio will be generated as:

```text
final_cutting.m4a
```

If `--save-refined-json` is enabled, the script will also generate an actual cut sequence file, which records the final clips used during rendering.

Example:

```text
final_cutting_actual_cut_sequence.json
```

---

## Key Render Parameters

| Parameter                               | Description                                                     |
| --------------------------------------- | --------------------------------------------------------------- |
| `--decision`                            | Path to the edit decision JSON file                             |
| `--host`                                | Path to the host audio file                                     |
| `--guest`                               | Path to the guest audio file                                    |
| `--opening`                             | Path to the opening audio                                       |
| `--ending`                              | Path to the ending audio                                        |
| `--output`                              | Output audio file path                                          |
| `--format ipod`                         | Export format for `.m4a` audio                                  |
| `--sequence-mode story-with-highlights` | Uses both cold open highlights and reordered story sequence     |
| `--opening-position after_highlights`   | Places opening audio after the cold open highlights             |
| `--trim-leading`                        | Trims leading silence from clips                                |
| `--host-text-pad-ms`                    | Adds padding to host clips after text-based duration estimation |
| `--host-chars-per-second`               | Estimates host speech duration based on text length             |
| `--host-gain`                           | Adjusts host volume                                             |
| `--gap`                                 | Default gap between clips                                       |
| `--highlight-gap`                       | Gap between highlight clips                                     |
| `--transition-gap`                      | Gap between topic transitions                                   |
| `--chapter-gap`                         | Gap between larger story chapters                               |
| `--fade-in`                             | Fade-in duration in milliseconds                                |
| `--fade-out`                            | Fade-out duration in milliseconds                               |
| `--save-refined-json`                   | Saves the actual cut sequence used by the script                |

---

## Notes on Host Audio Quality

Host recordings may contain background noise, silence, or guest voice leakage. The prompt and rendering process are designed to handle this by:

* Checking whether a host segment actually contains guest speech
* Removing host segments that are mostly guest leakage
* Flagging suspicious timestamps
* Avoiding unusually long host clips when the host text is short
* Preserving useful host questions, summaries, and transitions

This helps maintain a natural interview flow while reducing unwanted silence and background noise.

---

## Recommended GitHub Usage

Large audio files should not be committed to GitHub.

Recommended files to exclude:

```gitignore
# audio files
*.m4a
*.mp3
*.wav
*.aac

# input audio
inputs/

# temporary outputs
outputs/temp/
outputs/temp*/
outputs/temp_chunks_guest/
outputs/temp_chunks_host/

# generated final outputs
final_cutting*
*_actual_cut_sequence.json

# Visual Studio
.vs/

# Python cache
__pycache__/
*.pyc

# environment
.env
.venv/
venv/
```

Only source code, prompt files, and lightweight example JSON files should be uploaded to the repository.

---

## Current Limitations

This project is designed to assist podcast editing, but it does not fully replace human review.

Manual checking is still recommended for:

* Timestamp accuracy
* Host and guest overlap
* Awkward transitions caused by non-linear story reordering
* Audio quality issues
* Final narrative flow
* Sensitive or private content

---

## Future Improvements

Potential future improvements include:

* Automatic speaker leakage detection
* More accurate voice activity detection
* Better host timestamp correction
* Web UI for uploading audio and generating edit decisions
* Automatic chapter generation
* Automatic subtitle generation
* Integration with cloud storage or audio hosting platforms

---

## License

This project is currently for personal and experimental use.
