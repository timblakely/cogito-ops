import io
import json
import unittest
from unittest.mock import patch

from coordinator.image import ImageClient


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class ImageClientTests(unittest.TestCase):
    @patch("coordinator.image.urlopen")
    def test_muse_receives_data_url_and_returns_bounded_description(self, open_url):
        open_url.return_value = Response(json.dumps({"choices": [{"message": {
            "content": "A red error banner is visible."
        }}]}).encode())
        client = ImageClient("test-key", "http://litellm.test/v1", "image")
        result = client.describe("image/png", b"pixels", "error.png", "What failed?")
        self.assertEqual(result, "A red error banner is visible.")
        request = open_url.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "image")
        self.assertIn("Owner caption: What failed?", payload["messages"][0]["content"][0]["text"])
        self.assertEqual(payload["messages"][0]["content"][1]["type"], "image_url")
        self.assertTrue(payload["messages"][0]["content"][1]["image_url"]["url"].startswith(
            "data:image/png;base64,"))

    @patch("coordinator.image.urlopen")
    def test_empty_model_response_is_rejected(self, open_url):
        open_url.return_value = Response(json.dumps({"choices": [{"message": {
            "content": ""
        }}]}).encode())
        with self.assertRaisesRegex(ValueError, "no description"):
            ImageClient("test").describe("image/jpeg", b"pixels", "x.jpg", "")


if __name__ == "__main__": unittest.main()
