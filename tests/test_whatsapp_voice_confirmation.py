import unittest
from core.whatsapp_voice_confirmation import (
    ConfirmationState, WhatsAppConfirmationManager, classify_response,
)


class VoiceConfirmationTests(unittest.TestCase):
    def make(self, transcript=("yes send it", .99), send_result=(True, "verified")):
        spoken, sent, updates = [], [], []
        def send(to, msg):
            sent.append((to, msg))
            return send_result
        manager = WhatsAppConfirmationManager(
            speak=spoken.append,
            listen=lambda: transcript,
            send=send,
            show=lambda *a: None,
            update=lambda *a: updates.append(a),
            timeout_seconds=30,
        )
        return manager, spoken, sent, updates

    def test_phrase_classification(self):
        self.assertEqual(classify_response("Yes, send it", .99), "yes")
        self.assertEqual(classify_response("Don't send", .99), "no")
        self.assertEqual(classify_response("maybe", .99), "unclear")
        self.assertEqual(classify_response("yes", .2), "unclear")

    def test_tts_finishes_before_listening_and_sends_exact_text(self):
        order = []
        tts_finished = {"value": False}
        def speak(t):
            order.append("tts")
            if "Should I send it?" in t:
                tts_finished["value"] = True
        def listen():
            self.assertTrue(tts_finished["value"], "listening started before TTS completed")
            order.append("listen")
            return "Yes, send it", .99
        sent = []
        m = WhatsAppConfirmationManager(speak=speak, listen=listen,
            send=lambda r, t: (sent.append((r,t)) or True, "verified"),
            show=lambda *a: None, update=lambda *a: None)
        token = m.start("Ram", "I will arrive in 10 minutes.")
        self.assertTrue(m.run_voice_confirmation(token)[0])
        self.assertLess(order.index("tts"), order.index("listen"))
        self.assertEqual(sent, [("Ram", "I will arrive in 10 minutes.")])
        self.assertEqual(m.state, ConfirmationState.SENT)

    def test_no_cancels(self):
        m, _, sent, _ = self.make(("No", .99))
        token=m.start("Sita", "Call me")
        self.assertFalse(m.run_voice_confirmation(token)[0])
        self.assertEqual(sent, [])
        self.assertEqual(m.state, ConfirmationState.CANCELLED)

    def test_unclear_never_sends(self):
        m, _, sent, _ = self.make(("maybe", .99))
        token=m.start("Ram", "Hello")
        self.assertFalse(m.run_voice_confirmation(token)[0])
        self.assertEqual(sent, [])

    def test_microphone_failure_never_sends(self):
        m, _, sent, _ = self.make()
        m.listen=lambda: (_ for _ in ()).throw(OSError("mic unavailable"))
        token=m.start("Ram", "Hello")
        self.assertFalse(m.run_voice_confirmation(token)[0])
        self.assertEqual(sent, [])
        self.assertEqual(m.state, ConfirmationState.ERROR)

    def test_single_active_session(self):
        m, _, _, _ = self.make()
        m.start("Ram", "Hello")
        with self.assertRaises(RuntimeError):
            m.start("Sita", "Hi")


if __name__ == "__main__":
    unittest.main()
