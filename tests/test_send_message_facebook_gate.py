import threading
import unittest
from unittest.mock import patch

from core import confirm, outcome
from actions.send_message import send_message


class MessengerSendGateTests(unittest.TestCase):
    def setUp(self):
        confirm.bind(show=lambda *_args: None, hide=lambda: None, log=lambda _msg: None)

    def tearDown(self):
        if confirm.pending_title():
            confirm.resolve(False)

    def test_generic_messenger_send_uses_verified_preflight_and_voice_gate(self):
        completed = threading.Event()
        with (
            patch("actions.send_message._PYAUTOGUI", False),
            patch(
                "plugins._facebook_core.prepare_message",
                return_value={"state": "prepared", "name": "Asha"},
            ) as prepare,
            patch(
                "plugins._facebook_core.send_prepared",
                side_effect=lambda *_args: (
                    completed.set()
                    or outcome.done("facebook_send", verified=True)
                ),
            ) as send,
        ):
            pending = send_message({
                "platform": "messenger",
                "receiver": "Asha",
                "message_text": "I will call later.",
            })
            self.assertIn("CONFIRMATION_PENDING", pending)
            prepare.assert_called_once_with("Asha", "I will call later.")
            send.assert_not_called()

            self.assertTrue(confirm.resolve_from_voice("yes send it"))
            self.assertTrue(completed.wait(1))

        send.assert_called_once_with("Asha", "I will call later.")


if __name__ == "__main__":
    unittest.main()
