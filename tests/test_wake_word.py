import unittest

from core.wake_word import _is_wake_phrase


class HelloWakePhraseTests(unittest.TestCase):
    def test_hello_is_the_only_accepted_wake_phrase(self):
        self.assertTrue(_is_wake_phrase("Hello"))
        self.assertTrue(_is_wake_phrase("HELLO!"))
        self.assertFalse(_is_wake_phrase("Hey assistant"))
        self.assertFalse(_is_wake_phrase("hello there"))
        self.assertFalse(_is_wake_phrase(""))


if __name__ == "__main__":
    unittest.main()
