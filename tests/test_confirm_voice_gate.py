import threading
import unittest

from core import confirm


class VoiceGateTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.logs = []
        self.hidden = threading.Event()
        confirm.bind(
            show=lambda *_args: None,
            hide=self.hidden.set,
            log=self.logs.append,
        )

    def tearDown(self):
        if confirm.pending_title():
            confirm.resolve(False)

    def _request(self):
        sent = threading.Event()

        def run():
            self.sent.append("sent")
            sent.set()
            return "sent"

        confirm.request("test-send", "Send test?", "Recipient: A\nMessage: B", run)
        return sent

    def test_exact_voice_yes_runs_pending_action_once(self):
        sent = self._request()

        self.assertTrue(confirm.resolve_from_voice("Yes, send it"))
        self.assertTrue(sent.wait(1))
        self.assertEqual(self.sent, ["sent"])
        self.assertEqual(confirm.pending_title(), "")

    def test_nepali_voice_no_cancels_without_running_action(self):
        self._request()

        self.assertTrue(confirm.resolve_from_voice("पठाउन पर्दैन"))
        self.assertEqual(self.sent, [])
        self.assertEqual(confirm.pending_title(), "")
        self.assertIn("Cancelled", self.logs[-1])

    def test_confirmation_request_returns_review_data_for_speech(self):
        response = confirm.request(
            "test-send",
            "Send test?",
            "Recipient: A\nMessage: B",
            lambda: "sent",
            read_aloud=True,
        )

        self.assertIn("[OUTBOUND_MESSAGE_REVIEW]", response)
        self.assertIn("Recipient: A\nMessage: B", response)
        self.assertIn("<<<UNTRUSTED source=outbound_message_review>>>", response)
        self.assertIn("<<<END UNTRUSTED>>>", response)

    def test_voice_revision_cancels_old_draft(self):
        self._request()

        self.assertTrue(
            confirm.resolve_from_voice("No, change it to I will call tomorrow")
        )
        self.assertEqual(self.sent, [])
        self.assertEqual(confirm.pending_title(), "")

    def test_unclear_phrase_does_not_resolve_confirmation(self):
        self._request()

        self.assertFalse(confirm.resolve_from_voice("I think maybe"))
        self.assertEqual(confirm.pending_title(), "Send test?")
        self.assertEqual(self.sent, [])

    def test_voice_phrase_without_pending_confirmation_is_ignored(self):
        self.assertFalse(confirm.resolve_from_voice("yes send it"))
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
