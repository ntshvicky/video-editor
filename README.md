# Video Editor

A Flask-based media editing studio for trimming videos, cropping exports, converting media formats, extracting audio, editing images, and experimenting with AI image/video generation.

The project started as a lightweight video editor prototype and now has a cleaner media-service layer so the heavy FFmpeg/OpenAI work can later move into Django + Celery workers without rewriting the product surface.

## Features

- Upload local videos for editing.
- Download public YouTube videos with `yt-dlp`.
- Generate timeline thumbnails.
- Trim selected time ranges.
- Optional crop with multiple aspect ratios:
  - Free crop
  - Original video
  - Full screen `16:9`
  - Wide `21:9`
  - Reels `9:16`
  - Square `1:1`
  - Portrait `4:5`
  - Classic `4:3`
- Optional reverse video.
- Optional mute audio.
- Convert videos to `mp4`, `webm`, `mov`, `mkv`, or `gif`.
- Convert video to audio: `mp3`, `wav`, `m4a`, or `aac`.
- Convert images to `png`, `jpg`, `webp`, `bmp`, or `tiff`.
- Resize and crop images.
- Generate AI images with OpenAI when an API key is provided.
- Create AI video jobs with Sora-compatible OpenAI video generation.
- Convert generated images into short editable MP4 clips and load them into the main editor.

## Tech Stack

- Python
- Flask
- FFmpeg / FFprobe
- MoviePy
- Pillow
- yt-dlp
- OpenAI Python SDK
- HTML, CSS, JavaScript
- Cropper.js

## Project Structure

```text
.
├── app.py                 # Flask routes and API endpoints
├── media_services.py      # FFmpeg, image, YouTube, and AI service logic
├── convert_video.py       # Compatibility wrapper for video conversion
├── requirements.txt       # Python dependencies
├── static/
│   └── style.css          # Main UI styles
├── templates/
│   ├── index.html         # Main video editor
│   └── tools.html         # Converter and AI tool pages
└── tests/
    └── test_media_services.py
```

## Requirements

Install FFmpeg first.

macOS:

```bash
brew install ffmpeg
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install ffmpeg
```

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

If your Python is externally managed, use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run Locally

```bash
python3 app.py
```

Open:

```text
http://127.0.0.1:5002
```

## Routes

```text
/                       Main trim/crop/reverse/mute editor
/convert_video_ext      Video format conversion and audio extraction
/convert_image_ext      Image conversion, resize, and crop
/generate_ai_images     AI image generation
/generate_ai_video      AI video job creation
```

## AI Setup

The AI pages let users paste their own OpenAI API key directly into the form. The key is sent only with that request and is not stored by the app.

You can also set a local environment variable:

```bash
export OPENAI_API_KEY="your_api_key"
python3 app.py
```

Do not commit API keys to GitHub.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Notes On Media Processing

This app currently performs conversion and rendering from Flask request handlers. That is fine for local development and small clips, but it is not the right production architecture for long videos.

For production, move heavy work into background jobs:

- Django views create edit/render jobs.
- Celery workers run FFmpeg, thumbnail extraction, AI generation, and export tasks.
- MySQL stores assets, edit decisions, render jobs, and AI metadata.
- The frontend polls or subscribes to job progress.

## Security Notes

- Do not store user API keys in source code.
- Keep generated uploads, thumbnails, rendered files, and `.env` files out of Git.
- Validate uploaded files before processing.
- Put render jobs behind authentication and rate limits before deployment.

## Roadmap

- Background render queue with progress updates.
- AI scene detection.
- Beat-sync cuts for music and dance videos.
- Auto-reframe for reels and shorts.
- Sora job polling and automatic import into the editor.
- User projects with saved timelines.
- Django + MySQL migration.

## License

No license has been selected yet.
