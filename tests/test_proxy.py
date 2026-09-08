from __future__ import annotations

import unittest

from profile_manager.proxy import mask_proxy, normalize_proxy, redact_proxy_in_text


class ProxyTests(unittest.TestCase):
    def test_normalizes_and_masks_proxy(self) -> None:
        proxy = normalize_proxy("http://alice:secret@127.0.0.1:8080")
        self.assertEqual(proxy, "http://alice:secret@127.0.0.1:8080")
        self.assertEqual(mask_proxy(proxy), "http://alice:***@127.0.0.1:8080")

    def test_empty_proxy_is_none(self) -> None:
        self.assertIsNone(normalize_proxy("  "))
        self.assertEqual(mask_proxy(None), "—")

    def test_redacts_error_text(self) -> None:
        proxy = "socks5://user:password@localhost:1080"
        text = redact_proxy_in_text(f"Failed using {proxy}", proxy)
        self.assertNotIn("password", text)
        self.assertIn("***", text)


if __name__ == "__main__":
    unittest.main()
