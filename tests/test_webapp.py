from pathlib import Path
import unittest


WORKSPACE = Path(__file__).resolve().parents[1]


class WebAppTests(unittest.TestCase):
    def test_location_is_explicit_and_sent_only_with_answers(self) -> None:
        html = (WORKSPACE / "webapp" / "index.html").read_text(encoding="utf-8")
        script = (WORKSPACE / "webapp" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="detect-place"', html)
        self.assertIn("navigator.geolocation.getCurrentPosition", script)
        self.assertIn('api("/api/locate"', script)
        self.assertIn("latitude: state.location?.latitude", script)
        self.assertIn("if (!preserveLocation) state.location = null", script)
        self.assertIn('data-location-choice="true"', script)
        self.assertNotIn("localStorage.setItem(\"comesibutta.location", script)

    def test_territorial_views_share_one_verified_api(self) -> None:
        html = (WORKSPACE / "webapp" / "index.html").read_text(encoding="utf-8")
        script = (WORKSPACE / "webapp" / "app.js").read_text(encoding="utf-8")
        for view in ("search", "rules", "centres"):
            self.assertIn(f'data-view="{view}"', html)
        self.assertIn('id="rules-zone"', html)
        self.assertIn('id="rules-stream"', html)
        self.assertIn('id="rules-preparation"', html)
        self.assertIn('data-service-view="facilities"', html)
        self.assertIn('api("/api/territory"', script)
        self.assertIn("body: JSON.stringify", script)
        self.assertNotIn("/api/territory?", script)
        self.assertIn("accepted_waste", script)


if __name__ == "__main__":
    unittest.main()
