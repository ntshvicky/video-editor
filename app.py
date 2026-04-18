from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
from flask_cors import CORS

from media_services import (
    MediaProcessingError,
    build_thumbnail_payload,
    convert_image_file,
    convert_video_file,
    create_sora_video_job,
    download_youtube_clip,
    ensure_media_dirs,
    extract_thumbnails,
    generate_ai_image,
    generated_file_url,
    image_to_video_clip,
    resolve_upload_path,
    save_uploaded_video,
    trim_video,
)


app = Flask(__name__)
CORS(app)
ensure_media_dirs()


def json_error(message, status_code=400):
    return jsonify({"error": message}), status_code


def video_response(filename, video_path):
    thumbnails = extract_thumbnails(video_path)
    return jsonify(
        {
            "thumbnails": build_thumbnail_payload(thumbnails, request.host_url),
            "video_file": filename,
        }
    )


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/convert_video_ext", methods=["GET"])
def convert_video_page():
    return render_template("tools.html", active_tool="video")


@app.route("/convert_image_ext", methods=["GET"])
def convert_image_page():
    return render_template("tools.html", active_tool="image")


@app.route("/generate_ai_images", methods=["GET"])
def ai_images_page():
    return render_template("tools.html", active_tool="ai_image")


@app.route("/generate_ai_video", methods=["GET"])
def ai_video_page():
    return render_template("tools.html", active_tool="ai_video")


@app.route("/upload", methods=["POST"])
def upload_file():
    try:
        filename, video_path = save_uploaded_video(request.files.get("video"))
        return video_response(filename, video_path)
    except MediaProcessingError as exc:
        return json_error(str(exc), 400)


@app.route("/api/load_video/<path:filename>", methods=["GET"])
def load_video_api(filename):
    try:
        video_path = resolve_upload_path(filename)
        if not video_path.exists():
            return json_error("Video file was not found.", 404)
        return video_response(video_path.name, video_path)
    except MediaProcessingError as exc:
        return json_error(str(exc), 400)


@app.route("/trim_video", methods=["POST"])
def trim_video_route():
    try:
        output_path = trim_video(request.get_json(silent=True) or {})
        return send_file(output_path, as_attachment=True, download_name="trimmed_video.mp4")
    except MediaProcessingError as exc:
        return json_error(str(exc), 400)


@app.route("/download_youtube_video", methods=["POST"])
def download_youtube_video():
    data = request.get_json(silent=True) or {}
    url = data.get("youtube_url", "").strip()
    if not url:
        return json_error("Enter a YouTube URL.", 400)

    try:
        filename, video_path = download_youtube_clip(url)
        return video_response(filename, video_path)
    except MediaProcessingError as exc:
        return json_error(str(exc), 400)


@app.route("/api/convert_video", methods=["POST"])
def convert_video_api():
    try:
        output_path = convert_video_file(
            request.files.get("video"),
            request.form.get("output_format"),
            extract_audio=request.form.get("mode") == "audio",
        )
        return send_file(output_path, as_attachment=True, download_name=output_path.name)
    except MediaProcessingError as exc:
        return json_error(str(exc), 400)


@app.route("/api/convert_image", methods=["POST"])
def convert_image_api():
    try:
        crop = None
        if request.form.get("use_crop") == "true":
            crop = {
                "x": request.form.get("crop_x"),
                "y": request.form.get("crop_y"),
                "width": request.form.get("crop_width"),
                "height": request.form.get("crop_height"),
            }
        output_path = convert_image_file(
            request.files.get("image"),
            request.form.get("output_format"),
            resize_width=request.form.get("resize_width"),
            resize_height=request.form.get("resize_height"),
            crop=crop,
        )
        return send_file(output_path, as_attachment=True, download_name=output_path.name)
    except MediaProcessingError as exc:
        return json_error(str(exc), 400)


@app.route("/api/generate_ai_image", methods=["POST"])
def generate_ai_image_api():
    data = request.get_json(silent=True) or {}
    try:
        output_path = generate_ai_image(
            data.get("prompt"),
            size=data.get("size", "1024x1024"),
            output_format=data.get("format", "png"),
            quality=data.get("quality", "medium"),
            api_key=data.get("api_key"),
        )
        return jsonify({"url": generated_file_url(output_path.name), "filename": output_path.name})
    except MediaProcessingError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(f"AI image generation failed: {exc}", 500)


@app.route("/api/generated_image_to_video", methods=["POST"])
def generated_image_to_video_api():
    data = request.get_json(silent=True) or {}
    try:
        filename, video_path = image_to_video_clip(data.get("filename"), data.get("duration", 5))
        return jsonify({"video_file": filename, "editor_url": "/"})
    except MediaProcessingError as exc:
        return json_error(str(exc), 400)


@app.route("/api/generate_ai_video", methods=["POST"])
def generate_ai_video_api():
    data = request.get_json(silent=True) or {}
    try:
        job = create_sora_video_job(
            data.get("prompt"),
            size=data.get("size", "1280x720"),
            seconds=data.get("seconds", 4),
            model=data.get("model", "sora-2"),
            api_key=data.get("api_key"),
        )
        return jsonify(job)
    except MediaProcessingError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(f"AI video generation failed: {exc}", 500)


@app.route("/thumbnails/<path:filename>")
def thumbnails_file(filename):
    return send_from_directory("thumbnails", filename)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory("uploads", filename)


@app.route("/generated/<path:filename>")
def generated_file(filename):
    return send_from_directory("generated", filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
