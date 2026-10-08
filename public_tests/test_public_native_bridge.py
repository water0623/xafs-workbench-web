import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicNativeBridgeTests(unittest.TestCase):
    def test_public_pages_offer_one_installer_and_detector(self):
        for relative in ("index.html", "v2/index.html"):
            html = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("XAFS-Native-Bridge-Setup.exe", html)
            self.assertIn('id="detect-native-bridge"', html)
            self.assertNotIn('id="open-local-workbench"', html)
            self.assertNotIn('id="download-desktop-workbench"', html)

    def test_browser_client_uses_loopback_bridge_status_and_launch_routes(self):
        source = (ROOT / "v2/static/app.js").read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:8766", source)
        self.assertIn("/api/native-tools/status", source)
        self.assertIn("/api/native-tools/${button.dataset.tool}/launch", source)
        self.assertIn("tool.installed", source)
        self.assertIn("tool.running", source)

    def test_static_javascript_copies_stay_identical(self):
        expected = (ROOT / "v2/static/app.js").read_bytes()
        self.assertEqual(expected, (ROOT / "static/app.js").read_bytes())
        self.assertEqual(expected, (ROOT / "portable/xafs_workbench/static/app.js").read_bytes())


if __name__ == "__main__":
    unittest.main()
