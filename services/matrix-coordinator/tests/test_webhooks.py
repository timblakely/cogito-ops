import unittest

from coordinator.webhooks import verify_internal


class WebhookTests(unittest.TestCase):
    def test_signature(self):
        signature = "sha256=dc46983557fea127b43af721467eb9b3fde2338fe3e14f51952aa8478c13d355"
        self.assertTrue(verify_internal(b"secret", b"body", signature))
        self.assertFalse(verify_internal(b"secret", b"tampered", signature))


if __name__ == "__main__":
    unittest.main()
