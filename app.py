import uuid
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
from moviepy.editor import VideoFileClip
from werkzeug.utils import secure_filename
import subprocess
import os
from flask_cors import CORS
from pytube import YouTube

app = Flask(__name__)
CORS(app)

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

def extract_thumbnails(video_path, interval=1):
    clip = VideoFileClip(video_path)
    thumbnails = []
    for i in range(0, int(clip.duration), interval):
        frame = clip.get_frame(i)
        thumbnail_path = f'thumbnails/frame_{i}.jpg'
        clip.save_frame(thumbnail_path, i)
        thumbnails.append(thumbnail_path)
    return thumbnails


def get_video_format(video_file):
    """
    Get the format of the input video file using ffprobe.
    """
    command = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', video_file]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    if process.returncode == 0:
        return output.decode().strip()
    else:
        print(f"Error: {error.decode().strip()}")
        return None

def convert_video(input_file, output_file, output_format='mp4'):
    """
    Convert the input video file to the specified output format using FFmpeg.
    """
    current_format = get_video_format(input_file)
    print("1", current_format)
    if current_format is None:
        print("Failed to determine current format. Conversion aborted.")
        return
    
    # Check if the input and output formats are the same
    if current_format == output_format:
        print("2", output_format)
        print("Input and output formats are the same. No conversion needed.")
        return

    # Run FFmpeg to convert the video
    command = ['ffmpeg', '-i', input_file, '-c', 'copy', output_file]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, error = process.communicate()
    if process.returncode == 0:
        print("Conversion successful.")
    else:
        print(f"Conversion failed: {error.decode().strip()}")


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'video' not in request.files:
        return 'No video part', 400
    file = request.files['video']
    if file.filename == '':
        return 'No selected video', 400

    if file:
        filename = str(uuid.uuid4()).replace("-", "")[:8] + "." + secure_filename(file.filename).split('.')[-1]
        video_path = os.path.join('uploads', filename)
        file.save(video_path)
        vf = get_video_format(video_path)
        print("==", vf)
        if vf is None:
            return jsonify({'error': 'Failed to determine video format'}), 400
        if vf.lower()!= 'mp4' and vf.lower()!= 'h264':
            input_path = video_path
            filename = filename.split('.')[0] + '.mp4'
            output_path = os.path.join('uploads', filename)
            convert_video(input_path, output_path, output_format='mp4')
            print(input_path, output_path)
            video_path = output_path
        
        thumbnails = extract_thumbnails(video_path)
        # Create a list of thumbnail info
        thumbnail_info = []
        for i, thumbnail_path in enumerate(thumbnails):
            thumbnail_info.append({
                "url": f"{request.host_url}{thumbnail_path}",  # Adjust the URL as per your server setup
                "timestamp": i  # Assuming one thumbnail per second
            })

        return jsonify({'thumbnails': thumbnail_info, 'video_file': filename})
    
@app.route('/trim_video', methods=['POST'])
def trim_video():
    data = request.get_json()
    filename = data['filename']
    start_time = float(data['start_time'])
    end_time = float(data['end_time'])
    crop_x = float(data['crop_x']) if data['crop_x'] != -1 else None
    crop_y = float(data['crop_y']) if data['crop_y']!= -1 else None
    crop_width = float(data['crop_width']) if data['crop_width']!= -1 else None
    crop_height = float(data['crop_height']) if data['crop_height']!= -1 else None


    print(filename, start_time, end_time, crop_x, crop_y, crop_width, crop_height, request.host_url)
    
    source_path = os.path.join('uploads', filename)  # Adjust path as necessary
    if not os.path.exists(source_path):
        return jsonify({'error': 'File not found'}), 404

    with VideoFileClip(source_path) as video:

        cropped_video = video
        if crop_x is not None:
            cropped_video = video.crop(x1=crop_x, y1=crop_y, width=crop_width, height=crop_height)
        
        trimmed = cropped_video.subclip(start_time, end_time)
        output_path = os.path.join('trimmed', filename)
        trimmed.write_videofile(output_path, codec="libx264", audio_codec="aac")

    return send_file(output_path, as_attachment=True)

@app.route('/download_youtube_video', methods=['POST'])
def download_youtube_video():
    try:
        url = request.get_json()['youtube_url']
        yt = YouTube(url, use_oauth=False, allow_oauth_cache=True)
        video = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
        if video:
            rs = video.download("uploads")
            video_name = rs.split("/")[-1]
            print(f"Video downloaded successfully: {video.title}")
            video_path = os.path.join('uploads', video_name)
            thumbnails = extract_thumbnails(video_path)
            # Create a list of thumbnail info
            thumbnail_info = []
            for i, thumbnail_path in enumerate(thumbnails):
                thumbnail_info.append({
                    "url": f"{request.host_url}{thumbnail_path}",  # Adjust the URL as per your server setup
                    "timestamp": i  # Assuming one thumbnail per second
                })

            return jsonify({'thumbnails': thumbnail_info, 'video_file': video_name}), 200
        else:
            print("No video streams available")
            return jsonify({'error': "No video streams available"}), 400
            
    except Exception as e:
        print(f"An error occurred: {e}")
        return jsonify({'error': f"An error occurred: {e}"}), 400


@app.route('/thumbnails/<filename>')
def thumbnails_file(filename):
    return send_from_directory("thumbnails",
                               filename)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory("uploads",
                               filename)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5002, debug=True)
