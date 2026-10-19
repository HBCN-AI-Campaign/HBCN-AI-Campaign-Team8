import unittest

from app.ocr import OCRClient


class HTMLTextExtractionTests(unittest.TestCase):
    def test_extracts_visible_text_without_markup_or_hidden_content(self):
        html = b"""<!doctype html><html><head><title>Loan review</title>
        <style>.hidden { display: none }</style><script>secret()</script></head>
        <body><nav>Navigation</nav><h1>Loan&nbsp;review</h1><p>Applicant name</p>
        <button>Copy source</button><details><summary>Complete source</summary>
        <pre>sequenceDiagram</pre></details>
        <svg><text>hidden diagram text</text></svg><footer>Footer note</footer></body></html>"""

        result = OCRClient().extract("review.html", html)

        self.assertIsNone(result["error"])
        self.assertIn("Loan\xa0review", result["text"])
        self.assertIn("Applicant name", result["text"])
        self.assertNotIn("<h1>", result["text"])
        self.assertNotIn("secret()", result["text"])
        self.assertNotIn("hidden diagram text", result["text"])
        self.assertNotIn("Navigation", result["text"])
        self.assertNotIn("Copy source", result["text"])
        self.assertNotIn("sequenceDiagram", result["text"])
        self.assertNotIn("Complete source", result["text"])
        self.assertNotIn("Footer note", result["text"])


if __name__ == "__main__":
    unittest.main()
