import unittest
from unittest.mock import patch

from media_services import (
    MediaProcessingError,
    build_trim_command,
    clamp_crop,
    convert_video_file,
    download_youtube_clip,
    generate_ai_image,
    get_openai_api_key,
    image_to_video_clip,
    make_unique_filename,
    resolve_upload_path,
    run_command,
    validate_trim_request,
    validate_video_extension,
)


class MediaServicesTest(unittest.TestCase):
    def test_rejects_unsupported_video_extension(self):
        with self.assertRaises(MediaProcessingError):
            validate_video_extension("payload.txt")

    def test_unique_filename_keeps_safe_extension(self):
        filename = make_unique_filename("../../Summer Cut.MOV")

        self.assertTrue(filename.endswith(".mov"))
        self.assertNotIn("/", filename)
        self.assertGreaterEqual(len(filename), len("000000000000.mov"))

    def test_upload_path_uses_basename_only(self):
        path = resolve_upload_path("../../escape.mp4")

        self.assertEqual(path.name, "escape.mp4")
        self.assertTrue(str(path).endswith("uploads/escape.mp4"))

    def test_trim_request_requires_end_after_start(self):
        payload = {
            "filename": "clip.mp4",
            "start_time": 9,
            "end_time": 3,
        }

        with self.assertRaises(MediaProcessingError):
            validate_trim_request(payload)

    def test_trim_request_rounds_valid_crop(self):
        payload = {
            "filename": "clip.mp4",
            "start_time": 1,
            "end_time": 3,
            "use_crop": True,
            "crop_x": 10.2,
            "crop_y": 20.7,
            "crop_width": 300.4,
            "crop_height": 200.5,
        }

        filename, start_time, end_time, options = validate_trim_request(payload)

        self.assertEqual(filename, "clip.mp4")
        self.assertEqual(start_time, 1.0)
        self.assertEqual(end_time, 3.0)
        self.assertEqual(options["crop"], {"x": 10, "y": 21, "width": 300, "height": 200})

    def test_crop_is_optional_when_crop_values_are_present(self):
        payload = {
            "filename": "clip.mp4",
            "start_time": 1,
            "end_time": 3,
            "use_crop": False,
            "crop_x": 10,
            "crop_y": 20,
            "crop_width": 300,
            "crop_height": 200,
        }

        _, _, _, options = validate_trim_request(payload)

        self.assertIsNone(options["crop"])

    def test_clamps_crop_to_source_dimensions(self):
        crop = {"x": 90, "y": 40, "width": 80, "height": 40}
        metadata = {"width": 100, "height": 50}

        self.assertEqual(
            clamp_crop(crop, metadata),
            {"x": 90, "y": 40, "width": 10, "height": 10},
        )

    def test_trim_command_supports_reverse_and_mute(self):
        command = build_trim_command(
            "input.mp4",
            "output.mp4",
            0,
            4,
            {"width": 1920, "height": 1080, "has_audio": True},
            {
                "crop": {"x": 0, "y": 0, "width": 1080, "height": 1080},
                "reverse_video": True,
                "mute_audio": True,
            },
        )

        self.assertIn("crop=1080:1080:0:0,reverse", command)
        self.assertIn("-an", command)
        self.assertNotIn("-c:a", command)

    def test_video_converter_rejects_unsupported_output_format(self):
        with self.assertRaisesRegex(MediaProcessingError, "Unsupported output format"):
            convert_video_file(None, "exe")

    @patch.dict("media_services.os.environ", {}, clear=True)
    def test_ai_image_requires_api_key(self):
        with self.assertRaisesRegex(MediaProcessingError, "OPENAI_API_KEY"):
            generate_ai_image("make a poster")

    @patch.dict("media_services.os.environ", {}, clear=True)
    def test_request_api_key_can_be_used_without_env_key(self):
        self.assertEqual(get_openai_api_key("sk-test"), "sk-test")

    def test_image_to_video_rejects_missing_generated_file(self):
        with self.assertRaisesRegex(MediaProcessingError, "not found"):
            image_to_video_clip("missing.png")

    @patch("media_services.subprocess.run")
    def test_run_command_surfaces_stderr(self, mocked_run):
        mocked_run.return_value.returncode = 1
        mocked_run.return_value.stderr = "broken codec"
        mocked_run.return_value.stdout = ""

        with self.assertRaisesRegex(MediaProcessingError, "broken codec"):
            run_command(["ffmpeg", "-version"])

    @patch("media_services.UPLOAD_DIR")
    @patch("media_services.get_youtube_downloader")
    def test_youtube_429_gets_actionable_error(self, mocked_downloader, mocked_upload_dir):
        mocked_instance = mocked_downloader.return_value.return_value.__enter__.return_value
        mocked_instance.extract_info.side_effect = Exception("HTTP Error 429: Too Many Requests")
        mocked_upload_dir.glob.return_value = []

        with self.assertRaisesRegex(MediaProcessingError, "rate-limiting"):
            download_youtube_clip("https://www.youtube.com/watch?v=example")


if __name__ == "__main__":
    unittest.main()
