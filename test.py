import subprocess
import os

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
    if current_format is None:
        print("Failed to determine current format. Conversion aborted.")
        return
    
    # Check if the input and output formats are the same
    if current_format == output_format:
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

# Example usage
input_file = 'uploads/Dubai_Video_5.avi'
output_file = 'output_video.mp4'
requested_format = 'mp4'

if not os.path.isfile(input_file):
    print("Input file does not exist.")
else:
    convert_video(input_file, output_file, requested_format)
