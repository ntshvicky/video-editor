import json
import os
import re
import subprocess
import uuid
import base64
import urllib.error
import urllib.request
from pathlib import Path

try:
    from werkzeug.utils import secure_filename
except ModuleNotFoundError:
    def secure_filename(filename):
        filename = Path(filename or "").name
        filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename).strip("._")
        return filename or "video"


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
THUMBNAIL_DIR = BASE_DIR / "thumbnails"
TRIMMED_DIR = BASE_DIR / "trimmed"
GENERATED_DIR = BASE_DIR / "generated"

ALLOWED_VIDEO_EXTENSIONS = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
VIDEO_OUTPUT_FORMATS = {"mp4", "webm", "mov", "mkv", "gif"}
AUDIO_OUTPUT_FORMATS = {"mp3", "wav", "m4a", "aac"}
IMAGE_OUTPUT_FORMATS = {"png", "jpg", "jpeg", "webp", "bmp", "tiff"}


class MediaProcessingError(RuntimeError):
    """Raised when an uploaded media file cannot be processed safely."""


def ensure_media_dirs():
    for directory in (UPLOAD_DIR, THUMBNAIL_DIR, TRIMMED_DIR, GENERATED_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def build_public_url(host_url, relative_path):
    return f"{host_url.rstrip('/')}/{relative_path.as_posix()}"


def make_unique_filename(original_filename, extension=None):
    cleaned = secure_filename(original_filename or "video")
    suffix = extension or Path(cleaned).suffix.lower()
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    if not suffix:
        suffix = ".mp4"
    return f"{uuid.uuid4().hex[:12]}{suffix.lower()}"


def validate_video_extension(filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_VIDEO_EXTENSIONS:
        raise MediaProcessingError(
            f"Unsupported video extension '{suffix or 'none'}'. Upload a video file."
        )


def validate_image_extension(filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise MediaProcessingError(
            f"Unsupported image extension '{suffix or 'none'}'. Upload an image file."
        )


def resolve_upload_path(filename):
    candidate = (UPLOAD_DIR / Path(filename).name).resolve()
    if UPLOAD_DIR.resolve() not in candidate.parents:
        raise MediaProcessingError("Invalid video filename.")
    return candidate


def run_command(command, timeout=120):
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise MediaProcessingError(f"Missing dependency: {command[0]} is not installed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaProcessingError(f"Media command timed out after {timeout} seconds.") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise MediaProcessingError(detail or "Media command failed.")

    return completed.stdout


def probe_video(video_path):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    raw_output = run_command(command, timeout=30)
    try:
        metadata = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise MediaProcessingError("ffprobe returned invalid metadata.") from exc

    video_stream = next(
        (stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    if not video_stream:
        raise MediaProcessingError("No video stream found in the uploaded file.")

    return {
        "codec": video_stream.get("codec_name"),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "duration": float(metadata.get("format", {}).get("duration") or 0),
        "format": metadata.get("format", {}).get("format_name", ""),
        "has_audio": any(
            stream.get("codec_type") == "audio"
            for stream in metadata.get("streams", [])
        ),
    }


def save_uploaded_video(file_storage):
    ensure_media_dirs()
    if not file_storage or not file_storage.filename:
        raise MediaProcessingError("No video file was selected.")

    validate_video_extension(file_storage.filename)
    filename = make_unique_filename(file_storage.filename)
    destination = UPLOAD_DIR / filename
    file_storage.save(destination)

    try:
        probe_video(destination)
    except MediaProcessingError:
        destination.unlink(missing_ok=True)
        raise

    return normalize_for_browser(destination)


def normalize_for_browser(video_path):
    metadata = probe_video(video_path)
    path = Path(video_path)
    if path.suffix.lower() == ".mp4" and metadata["codec"] == "h264":
        return path.name, path

    output_filename = make_unique_filename(path.stem, ".mp4")
    output_path = UPLOAD_DIR / output_filename
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_command(command, timeout=600)
    return output_filename, output_path


def extract_thumbnails(video_path, interval=1):
    try:
        from moviepy import VideoFileClip
    except ImportError:
        from moviepy.editor import VideoFileClip

    ensure_media_dirs()
    job_id = uuid.uuid4().hex[:12]
    output_dir = THUMBNAIL_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    thumbnails = []
    with VideoFileClip(str(video_path)) as clip:
        duration = int(clip.duration or 0)
        for timestamp in range(0, max(duration, 1), interval):
            thumbnail_path = output_dir / f"frame_{timestamp}.jpg"
            clip.save_frame(str(thumbnail_path), timestamp)
            thumbnails.append(
                {
                    "path": thumbnail_path,
                    "relative_path": Path("thumbnails") / job_id / thumbnail_path.name,
                    "timestamp": timestamp,
                }
            )
    return thumbnails


def build_thumbnail_payload(thumbnails, host_url):
    return [
        {
            "url": build_public_url(host_url, thumbnail["relative_path"]),
            "timestamp": thumbnail["timestamp"],
        }
        for thumbnail in thumbnails
    ]


def validate_trim_request(data):
    try:
        filename = Path(str(data["filename"])).name
        start_time = float(data["start_time"])
        end_time = float(data["end_time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaProcessingError("Trim request must include filename, start_time, and end_time.") from exc

    if start_time < 0 or end_time <= start_time:
        raise MediaProcessingError("End time must be greater than start time.")

    use_crop = parse_bool(data.get("use_crop", False))
    reverse_video = parse_bool(data.get("reverse_video", False))
    mute_audio = parse_bool(data.get("mute_audio", False))

    crop = None
    crop_x = float(data.get("crop_x", -1))
    crop_y = float(data.get("crop_y", -1))
    crop_width = float(data.get("crop_width", -1))
    crop_height = float(data.get("crop_height", -1))
    if use_crop:
        if not all(value >= 0 for value in (crop_x, crop_y, crop_width, crop_height)):
            raise MediaProcessingError("Enable crop only after selecting a crop frame.")
        if crop_width <= 0 or crop_height <= 0:
            raise MediaProcessingError("Crop width and height must be positive.")
        crop = {
            "x": int(round(crop_x)),
            "y": int(round(crop_y)),
            "width": int(round(crop_width)),
            "height": int(round(crop_height)),
        }

    return filename, start_time, end_time, {
        "crop": crop,
        "reverse_video": reverse_video,
        "mute_audio": mute_audio,
    }


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def even_at_least_two(value):
    value = max(2, int(value))
    return value if value % 2 == 0 else value - 1


def clamp_crop(crop, metadata):
    if not crop:
        return None

    source_width = int(metadata.get("width") or 0)
    source_height = int(metadata.get("height") or 0)
    if source_width < 2 or source_height < 2:
        raise MediaProcessingError("Source video dimensions are too small to crop.")

    x = max(0, min(crop["x"], source_width - 2))
    y = max(0, min(crop["y"], source_height - 2))
    width = min(crop["width"], source_width - x)
    height = min(crop["height"], source_height - y)

    return {
        "x": x,
        "y": y,
        "width": even_at_least_two(width),
        "height": even_at_least_two(height),
    }


def build_trim_command(source_path, output_path, start_time, end_time, metadata, options):
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_time:.3f}",
        "-to",
        f"{end_time:.3f}",
        "-i",
        str(source_path),
    ]

    video_filters = []
    crop = clamp_crop(options.get("crop"), metadata)
    if crop:
        video_filters.append(
            f"crop={crop['width']}:{crop['height']}:{crop['x']}:{crop['y']}"
        )
    if options.get("reverse_video"):
        video_filters.append("reverse")
    if video_filters:
        command.extend(["-vf", ",".join(video_filters)])

    if options.get("mute_audio"):
        command.append("-an")
    elif options.get("reverse_video") and metadata.get("has_audio"):
        command.extend(["-af", "areverse"])

    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
        ]
    )
    if not options.get("mute_audio"):
        command.extend(["-c:a", "aac"])
    command.extend(["-movflags", "+faststart", str(output_path)])
    return command


def trim_video(data):
    ensure_media_dirs()
    filename, start_time, end_time, options = validate_trim_request(data)
    source_path = resolve_upload_path(filename)
    if not source_path.exists():
        raise MediaProcessingError("Source video file was not found.")

    metadata = probe_video(source_path)
    duration = metadata["duration"]
    if duration and end_time > duration + 0.25:
        raise MediaProcessingError("Trim range exceeds the video duration.")

    output_filename = make_unique_filename(f"trimmed-{source_path.stem}", ".mp4")
    output_path = TRIMMED_DIR / output_filename
    command = build_trim_command(source_path, output_path, start_time, end_time, metadata, options)
    run_command(command, timeout=600)
    return output_path


def get_youtube_downloader():
    from yt_dlp import YoutubeDL

    return YoutubeDL


def download_youtube_clip(url):
    ensure_media_dirs()
    download_id = uuid.uuid4().hex[:12]
    output_template = str(UPLOAD_DIR / f"{download_id}.%(ext)s")

    try:
        youtube_downloader = get_youtube_downloader()
    except ModuleNotFoundError as exc:
        raise MediaProcessingError(
            "YouTube downloads require yt-dlp. Run: python3 -m pip install -r requirements.txt"
        ) from exc

    options = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
    }

    try:
        with youtube_downloader(options) as ydl:
            ydl.extract_info(url, download=True)
    except Exception as exc:
        message = str(exc)
        if "429" in message or "Too Many Requests" in message:
            raise MediaProcessingError(
                "YouTube is rate-limiting downloads from this network. Try again later, use a different network, or upload the file directly."
            ) from exc
        raise MediaProcessingError(f"YouTube download failed: {message}") from exc

    downloaded_files = sorted(UPLOAD_DIR.glob(f"{download_id}.*"))
    if not downloaded_files:
        raise MediaProcessingError("YouTube download finished but no media file was saved.")

    preferred_file = next(
        (path for path in downloaded_files if path.suffix.lower() == ".mp4"),
        downloaded_files[0],
    )
    return normalize_for_browser(preferred_file)


def register_youtube_download(downloaded_path):
    ensure_media_dirs()
    path = Path(downloaded_path)
    validate_video_extension(path.name)
    safe_name = make_unique_filename(path.name)
    safe_path = UPLOAD_DIR / safe_name
    os.replace(path, safe_path)
    return normalize_for_browser(safe_path)


def save_temp_upload(file_storage, allowed_kind):
    ensure_media_dirs()
    if not file_storage or not file_storage.filename:
        raise MediaProcessingError(f"No {allowed_kind} file was selected.")
    if allowed_kind == "video":
        validate_video_extension(file_storage.filename)
    elif allowed_kind == "image":
        validate_image_extension(file_storage.filename)
    filename = make_unique_filename(file_storage.filename)
    destination = UPLOAD_DIR / filename
    file_storage.save(destination)
    return destination


def convert_video_file(file_storage, output_format, extract_audio=False):
    output_format = (output_format or "").lower().strip(".")
    allowed_formats = AUDIO_OUTPUT_FORMATS if extract_audio else VIDEO_OUTPUT_FORMATS
    if output_format not in allowed_formats:
        raise MediaProcessingError(f"Unsupported output format '{output_format}'.")

    source_path = save_temp_upload(file_storage, "video")
    output_path = TRIMMED_DIR / make_unique_filename(source_path.stem, f".{output_format}")
    command = ["ffmpeg", "-y", "-i", str(source_path)]

    if extract_audio:
        command.extend(["-vn"])
        if output_format == "mp3":
            command.extend(["-codec:a", "libmp3lame", "-q:a", "2"])
        elif output_format == "wav":
            command.extend(["-codec:a", "pcm_s16le"])
        elif output_format in {"m4a", "aac"}:
            command.extend(["-codec:a", "aac", "-b:a", "192k"])
    elif output_format == "gif":
        command.extend([
            "-vf",
            "fps=12,scale=720:-1:flags=lanczos",
            "-loop",
            "0",
        ])
    else:
        command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac"])
        if output_format == "webm":
            command = [
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-c:v",
                "libvpx-vp9",
                "-b:v",
                "0",
                "-crf",
                "32",
                "-c:a",
                "libopus",
            ]

    command.append(str(output_path))
    run_command(command, timeout=900)
    source_path.unlink(missing_ok=True)
    return output_path


def parse_int_or_none(value):
    if value in (None, ""):
        return None
    parsed = int(float(value))
    return parsed if parsed > 0 else None


def convert_image_file(file_storage, output_format, resize_width=None, resize_height=None, crop=None):
    output_format = (output_format or "").lower().strip(".")
    if output_format == "jpeg":
        output_format = "jpg"
    if output_format not in IMAGE_OUTPUT_FORMATS:
        raise MediaProcessingError(f"Unsupported image output format '{output_format}'.")

    source_path = save_temp_upload(file_storage, "image")
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise MediaProcessingError("Image editing requires Pillow. Run: python3 -m pip install -r requirements.txt") from exc

    output_path = TRIMMED_DIR / make_unique_filename(source_path.stem, f".{output_format}")
    with Image.open(source_path) as image:
        image = image.convert("RGBA") if output_format == "png" else image.convert("RGB")
        if crop:
            x = max(0, int(crop.get("x", 0)))
            y = max(0, int(crop.get("y", 0)))
            width = parse_int_or_none(crop.get("width")) or image.width
            height = parse_int_or_none(crop.get("height")) or image.height
            right = min(image.width, x + width)
            lower = min(image.height, y + height)
            if right <= x or lower <= y:
                raise MediaProcessingError("Crop area is outside the image.")
            image = image.crop((x, y, right, lower))

        resize_width = parse_int_or_none(resize_width)
        resize_height = parse_int_or_none(resize_height)
        if resize_width or resize_height:
            if not resize_width:
                resize_width = int(image.width * (resize_height / image.height))
            if not resize_height:
                resize_height = int(image.height * (resize_width / image.width))
            image = image.resize((resize_width, resize_height), Image.Resampling.LANCZOS)

        image.save(output_path)

    source_path.unlink(missing_ok=True)
    return output_path


def generated_file_url(filename):
    return f"/generated/{Path(filename).name}"


def resolve_generated_path(filename):
    candidate = (GENERATED_DIR / Path(filename).name).resolve()
    if GENERATED_DIR.resolve() not in candidate.parents:
        raise MediaProcessingError("Invalid generated filename.")
    return candidate


def image_to_video_clip(filename, duration=5):
    ensure_media_dirs()
    image_path = resolve_generated_path(filename)
    if not image_path.exists():
        raise MediaProcessingError("Generated image was not found.")
    duration = max(1, min(int(float(duration or 5)), 30))
    output_path = UPLOAD_DIR / make_unique_filename(image_path.stem, ".mp4")
    command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-t",
        str(duration),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_command(command, timeout=120)
    return output_path.name, output_path


def get_openai_api_key(api_key=None):
    key = (api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise MediaProcessingError("Enter an OpenAI API key to enable AI generation.")
    return key


def generate_ai_image(prompt, size="1024x1024", output_format="png", quality="medium", api_key=None):
    try:
        key = get_openai_api_key(api_key)
    except MediaProcessingError:
        raise MediaProcessingError("Set OPENAI_API_KEY to enable AI image generation.")
    if not prompt or not prompt.strip():
        raise MediaProcessingError("Enter an image prompt.")

    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise MediaProcessingError("AI image generation requires the openai package. Run: python3 -m pip install -r requirements.txt") from exc

    ensure_media_dirs()
    client = OpenAI(api_key=key)
    try:
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt.strip(),
            size=size,
            quality=quality,
            output_format=output_format,
        )
        image_base64 = response.data[0].b64_json
    except Exception as exc:
        raise MediaProcessingError(f"AI image generation failed: {exc}") from exc
    filename = make_unique_filename("ai-image", f".{output_format}")
    output_path = GENERATED_DIR / filename
    output_path.write_bytes(base64.b64decode(image_base64))
    return output_path


def create_sora_video_job(prompt, size="1280x720", seconds=4, model="sora-2", api_key=None):
    try:
        key = get_openai_api_key(api_key)
    except MediaProcessingError:
        raise MediaProcessingError("Set OPENAI_API_KEY to enable AI video generation.")
    if not prompt or not prompt.strip():
        raise MediaProcessingError("Enter a video prompt.")

    payload = {
        "model": model,
        "prompt": prompt.strip(),
        "size": size,
        "seconds": int(seconds),
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/videos",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise MediaProcessingError(f"AI video generation failed: {detail}") from exc
