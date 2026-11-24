import unittest

from plugins._whatsapp_core import fold, unique_match


class WhatsAppNameMatchingTests(unittest.TestCase):
    def test_fold_handles_case_marks_and_unicode(self):
        self.assertEqual(fold("  Café—Group "), "cafegroup")
        self.assertEqual(fold("नेपाली"), "नेपाली")
        self.assertEqual(fold("Rahul 👋"), "rahul")

    def test_unique_match_requires_exactly_one_match(self):
        self.assertEqual(
            unique_match("Rahul", ["Rahul", "Rahul K."]),
            ("Rahul", ""),
        )

    def test_duplicate_names_are_rejected(self):
        name, reason = unique_match("Rahul", ["Rahul", "RAHUL"])
        self.assertIsNone(name)
        self.assertIn("More than one", reason)

    def test_partial_name_is_not_treated_as_exact(self):
        name, reason = unique_match("Rah", ["Rahul"])
        self.assertIsNone(name)
        self.assertIn("No exact", reason)

    def test_empty_query_is_rejected(self):
        name, reason = unique_match("  ", ["Rahul"])
        self.assertIsNone(name)
        self.assertIn("required", reason)


if __name__ == "__main__":
    unittest.main()
