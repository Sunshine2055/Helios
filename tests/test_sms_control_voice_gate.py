import threading
import unittest
from unittest.mock import patch

from core import confirm
from plugins.sms_control import sms_control


_SID = "AC" + "1" * 32


class _AccountResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return ('{"sid":"' + _SID + '","status":"active"}').encode()


class SmsVoiceGateTests(unittest.TestCase):
    def setUp(self):
        confirm.bind(show=lambda *_args: None, hide=lambda: None, log=lambda _msg: None)

    def tearDown(self):
        if confirm.pending_title():
            confirm.resolve(False)

    def test_missing_twilio_credentials_are_reported(self):
        with patch.dict("os.environ", {}, clear=True):
            result = sms_control({"action": "status"})

        self.assertIn("TWILIO_ACCOUNT_SID", result)
        self.assertTrue(result.startswith("status=failed"))

    def test_status_checks_twilio_account_before_claiming_connection(self):
        with (
            patch.dict("os.environ", {
                "TWILIO_ACCOUNT_SID": _SID,
                "TWILIO_AUTH_TOKEN": "test-token",
                "TWILIO_FROM_NUMBER": "+15551234567",
            }),
            patch("plugins.sms_control.urlopen", return_value=_AccountResponse()) as urlopen,
        ):
            result = sms_control({"action": "status"})

        self.assertIn("connected=true", result)
        self.assertIn("account_status=active", result)
        self.assertIn(_SID, urlopen.call_args.args[0].full_url)

    def test_sms_send_waits_for_voice_confirmation(self):
        completed = threading.Event()
        with patch.dict("os.environ", {
            "TWILIO_ACCOUNT_SID": _SID,
            "TWILIO_AUTH_TOKEN": "test-token",
            "TWILIO_FROM_NUMBER": "+15551234567",
        }):
            with patch(
                "plugins.sms_control._send_confirmed",
                side_effect=lambda *_args: completed.set() or "accepted",
            ) as send:
                pending = sms_control({
                    "action": "send",
                    "to": "+15557654321",
                    "text": "I will call later.",
                })
                self.assertIn("CONFIRMATION_PENDING", pending)
                self.assertIn("[OUTBOUND_MESSAGE_REVIEW]", pending)
                self.assertIn("To: +15557654321", pending)
                self.assertIn("Message:\nI will call later.", pending)
                send.assert_not_called()

                self.assertTrue(confirm.resolve_from_voice("हुन्छ पठाइदिनुहोस्"))
                self.assertTrue(completed.wait(1))

        send.assert_called_once_with(
            _SID, "+15557654321", "I will call later.",
        )


if __name__ == "__main__":
    unittest.main()
