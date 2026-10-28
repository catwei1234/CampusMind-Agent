import unittest

from app.services.chunking import chunk_markdown_structured, chunk_plain_text


class ChunkingTests(unittest.TestCase):
    def test_structured_chunks_keep_heading_path(self):
        content = "\n".join([
            "# Sleep",
            "Intro text.",
            "## Hard to fall asleep",
            "Keep a fixed wake-up time.",
            "",
            "- Reduce screen time.",
            "- Try breathing practice.",
        ])

        chunks = chunk_markdown_structured(content, size=160, overlap=20, source="sleep.md")

        self.assertTrue(any("Source: sleep.md" in chunk for chunk in chunks))
        self.assertTrue(any("Section: Sleep > Hard to fall asleep" in chunk for chunk in chunks))
        self.assertTrue(any("breathing practice" in chunk for chunk in chunks))

    def test_structured_chunks_split_large_sections(self):
        paragraph = " ".join(f"word{i}" for i in range(80))
        content = f"# Academic Stress\n{paragraph}"

        chunks = chunk_markdown_structured(content, size=120, overlap=30, source="academic.md")

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all("Section: Academic Stress" in chunk for chunk in chunks))

    def test_plain_text_overlap(self):
        chunks = chunk_plain_text("abcdefghijklmnopqrstuvwxyz", size=10, overlap=3)

        self.assertEqual(chunks[0], "abcdefghij")
        self.assertEqual(chunks[1], "hijklmnopq")


if __name__ == "__main__":
    unittest.main()
