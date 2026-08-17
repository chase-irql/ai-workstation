import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from notifications import send_email, send_sms


class NotificationTests(unittest.TestCase):
    def test_email_normalizes_recipient(self):
        self.assertEqual(send_email("  User@Example.COM ", "hello")["recipient"], "user@example.com")

    def test_sms_normalizes_recipient(self):
        self.assertEqual(send_sms("  +1-555-AbC ", "hello")["recipient"], "+1-555-abc")

    def test_empty_recipient_is_rejected_by_both_channels(self):
        for sender in (send_email, send_sms):
            with self.subTest(sender=sender.__name__):
                with self.assertRaisesRegex(ValueError, "recipient cannot be empty"):
                    sender("  ", "hello")


if __name__ == "__main__":
    unittest.main()
