import threading
import unittest
from unittest.mock import patch

from core import confirm
from plugins.whatsapp_control import whatsapp_control


class _Transport:
    def __init__(self):
        self.sent = []
        self.sent_event = threading.Event()

    def prepare_message(self, contact):
        return {"state": "opened", "name": contact}

    def send_message_to(self, contact, text):
        self.sent.append((contact, text))
        self.sent_event.set()
        return True, contact


class _Player:
    def request_say(self, _message):
        pass


class WhatsAppVoiceGateTests(unittest.TestCase):
    def setUp(self):
        confirm.bind(show=lambda *_args: None, hide=lambda: None, log=lambda _msg: None)

    def tearDown(self):
        if confirm.pending_title():
            confirm.resolve(False)

    def _compose(self):
        return whatsapp_control(
            {"action": "send", "contact": "Asha", "text": "I will call you."},
            player=_Player(),
        )

    def test_exact_voice_yes_sends_prepared_whatsapp_message(self):
        transport = _Transport()
        with patch("plugins.whatsapp_control.wa.get", return_value=(transport, "")):
            pending = self._compose()
            self.assertIn("[CONFIRMATION_PENDING]", pending)
            self.assertIn("[OUTBOUND_MESSAGE_REVIEW]", pending)
            self.assertIn("To: Asha", pending)
            self.assertIn("Message:\nI will call you.", pending)
            self.assertEqual(transport.sent, [])

            self.assertTrue(confirm.resolve_from_voice("पठाइदिनुहोस्"))
            self.assertTrue(transport.sent_event.wait(1))

        self.assertEqual(transport.sent, [("Asha", "I will call you.")])

    def test_voice_no_cancels_without_sending(self):
        transport = _Transport()
        with patch("plugins.whatsapp_control.wa.get", return_value=(transport, "")):
            pending = self._compose()
            self.assertIn("[CONFIRMATION_PENDING]", pending)
            self.assertIn("[OUTBOUND_MESSAGE_REVIEW]", pending)
            self.assertTrue(confirm.resolve_from_voice("रद्द गर्नुहोस्"))

        self.assertEqual(transport.sent, [])


if __name__ == "__main__":
    unittest.main()
