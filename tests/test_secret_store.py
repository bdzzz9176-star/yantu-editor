from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from secret_store import forget_credentials, load_credentials, save_credentials  # noqa: E402


class SecretStoreTests(unittest.TestCase):
    def test_dpapi_roundtrip_has_no_plaintext_secret(self):
        temp_root = PROJECT_ROOT / "tmp" / "secret-tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as folder:
            path = Path(folder) / "credentials.json"
            secret = "sk-test-plaintext-must-not-appear"
            save_credentials(path, secret, "https://api.deepseek.com", "deepseek-v4-flash")
            disk_text = path.read_text(encoding="utf-8")
            self.assertNotIn(secret, disk_text)
            self.assertEqual(load_credentials(path), {
                "api_key": secret,
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
            })
            forget_credentials(path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

