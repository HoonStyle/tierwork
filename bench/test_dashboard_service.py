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
            "mac_plist": root / "Library" / "LaunchAgents" / "service.plist",
            "windows_cmd": root / ".tierwork" / "dashboard.cmd",
            "linux_unit": root / ".config" / "systemd" / "user" / "tierwork-dashboard.service",
            "state": root / ".tierwork",
            "log": root / ".tierwork" / "dashboard.log",
            "error_log": root / ".tierwork" / "dashboard-error.log",
            "dashboard": root / "repo" / "bench" / "dashboard.py",
            "working_directory": root / "repo",
        }

    def test_platform_detection(self):
        self.assertEqual(service.platform_name("darwin"), "macos")
        self.assertEqual(service.platform_name("win32"), "windows")
        self.assertEqual(service.platform_name("linux"), "linux")
        with self.assertRaises(SystemExit):
            service.platform_name("plan9")

    def test_macos_plist_is_local_background_launch_agent(self):
        with tempfile.TemporaryDirectory() as temporary:
            info = self.info(Path(temporary))
            payload = service.mac_plist(info, 8765, python="/usr/local/bin/python3")
            self.assertEqual(payload["Label"], service.LABEL)
            self.assertEqual(payload["ProgramArguments"][-2:], ["--port", "8765"])
            self.assertEqual(payload["KeepAlive"], {"SuccessfulExit": False})
            self.assertTrue(payload["RunAtLoad"])
            service.atomic_write(info["mac_plist"], payload, binary=True)
            with info["mac_plist"].open("rb") as handle:
                self.assertEqual(plistlib.load(handle), payload)
            self.assertEqual(service.installed_port("macos", info), 8765)

    def test_windows_task_script_is_quoted_and_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            info = self.info(Path(temporary))
            script = service.windows_script(info, 9876, python="C:\\Program Files\\Python\\python.exe")
            self.assertIn('"C:\\Program Files\\Python\\python.exe"', script)
            self.assertIn("--port 9876", script)
            self.assertIn("dashboard-error.log", script)
            self.assertNotIn("0.0.0.0", script)
            service.atomic_write(info["windows_cmd"], script)
            self.assertEqual(service.installed_port("windows", info), 9876)

    def test_linux_systemd_unit_restarts_on_failure_and_stays_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            info = self.info(Path(temporary))
            unit = service.systemd_service(info, 7654, python="/usr/bin/python3")
            self.assertIn("Restart=on-failure", unit)
            self.assertIn("--port 7654", unit)
            self.assertIn("WantedBy=default.target", unit)
            self.assertNotIn("0.0.0.0", unit)
            service.atomic_write(info["linux_unit"], unit)
            self.assertEqual(service.installed_port("linux", info), 7654)

    def test_port_validation(self):
        self.assertEqual(service.validate_port("8765"), 8765)
        for value in ("0", "1023", "65536"):
            with self.assertRaises(argparse.ArgumentTypeError):
                service.validate_port(value)


if __name__ == "__main__":
    unittest.main()
