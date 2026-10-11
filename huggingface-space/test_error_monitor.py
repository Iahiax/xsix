import unittest

from error_monitor import get_error_snapshot, record_error


class ErrorMonitorTests(unittest.TestCase):
    def test_tracks_only_sanitized_server_error_metadata(self):
        before = get_error_snapshot()["errorCount"]
        record_error(503, "get", "/model/123?token=do-not-store")
        snapshot = get_error_snapshot()

        self.assertEqual(snapshot["state"], "attention")
        self.assertEqual(snapshot["errorCount"], before + 1)
        event = snapshot["recentErrors"][0]
        self.assertEqual(event["statusCode"], 503)
        self.assertEqual(event["method"], "GET")
        self.assertEqual(event["path"], "/model/:segment")
        self.assertNotIn("token", str(snapshot))
        self.assertNotIn("do-not-store", str(snapshot))

    def test_ignores_non_server_errors(self):
        before = get_error_snapshot()["errorCount"]
        record_error(401, "post", "/v1/chat/completions")
        self.assertEqual(get_error_snapshot()["errorCount"], before)


if __name__ == "__main__":
    unittest.main()
