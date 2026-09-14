import unittest

from coordinator.models import PlanVersion, ValidationError, content_hash


class ModelTests(unittest.TestCase):
    def test_plan_hash_normalizes_transport_whitespace(self):
        self.assertEqual(content_hash("# Plan\r\n\r\nText  \r\n"), content_hash("# Plan\n\nText\n"))

    def test_plan_repository_must_be_https_or_ssh(self):
        with self.assertRaises(ValidationError):
            PlanVersion("plan", 1, "# Plan", "!room:x", "$event", "file:///tmp/repo")


if __name__ == "__main__":
    unittest.main()
