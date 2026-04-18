from pathlib import Path

from media_services import normalize_for_browser, probe_video


def get_video_format(video_file):
    return probe_video(video_file)["codec"]


def convert_video(input_file, output_file=None, output_format="mp4"):
    if output_format != "mp4":
        raise ValueError("Only MP4 browser normalization is currently supported.")

    filename, path = normalize_for_browser(Path(input_file))
    if output_file and Path(output_file) != path:
        Path(path).replace(output_file)
        return output_file

    return filename
