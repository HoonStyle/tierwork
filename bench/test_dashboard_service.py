import argparse
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("dashboard-service.py")
SPEC = importlib.util.spec_from_file_location("dashboard_service", MODULE_PATH)
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


class DashboardServiceTest(unittest.TestCase):
    def info(self, root):
        return {
            "plist": root / "Library" / "LaunchAgents" / "service.plist",
            "state": root / ".tierwork",
            "log": root / ".tierwork" / "dashboard.log",
            "error_log": root / ".tierwork" / "dashboard-error.log",
            "dashboard": root / "repo" / "bench" / "dashboard.py",
            "working_directory": root / "repo",
        }

    def test_plist_is_local_background_launch_agent(self):
        with tempfile.TemporaryDirectory() as temporary:
            info = self.info(Path(temporary))
            payload = service.plist_payload(info, 8765, python="/usr/local/bin/python3")
            self.assertEqual(payload["Label"], service.LABEL)
            self.assertEqual(payload["ProgramArguments"][-2:], ["--port", "8765"])
            self.assertEqual(payload["KeepAlive"], {"SuccessfulExit": False})
            self.assertTrue(payload["RunAtLoad"])
            self.assertNotIn("0.0.0.0", " ".join(payload["ProgramArguments"]))

    def test_atomic_write_and_installed_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            info = self.info(Path(temporary))
            payload = service.plist_payload(info, 9876)
            service.write_plist(info["plist"], payload)
            with info["plist"].open("rb") as handle:
                self.assertEqual(plistlib.load(handle), payload)
            self.assertEqual(service.installed_port(info["plist"]), 9876)
            self.assertEqual(info["plist"].stat().st_mode & 0o777, 0o644)

    def test_port_validation(self):
        self.assertEqual(service.validate_port("8765"), 8765)
        for value in ("0", "1023", "65536"):
            with self.assertRaises(argparse.ArgumentTypeError):
                service.validate_port(value)


if __name__ == "__main__":
    unittest.main()
