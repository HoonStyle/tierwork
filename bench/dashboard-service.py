#!/usr/bin/env python3
"""Manage the Tierwork dashboard as an optional macOS LaunchAgent.

The LaunchAgent's presence is the auto-start setting: enable installs and starts
it; disable stops and removes it. The dashboard remains bound to 127.0.0.1.
"""

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

LABEL = "com.hoonstyle.tierwork.dashboard"


def paths():
    home = Path.home()
    state = home / ".tierwork"
    return {
        "plist": home / "Library" / "LaunchAgents" / f"{LABEL}.plist",
        "state": state,
        "log": state / "dashboard.log",
        "error_log": state / "dashboard-error.log",
        "dashboard": Path(__file__).resolve().with_name("dashboard.py"),
        "working_directory": Path(__file__).resolve().parent.parent,
    }


def validate_port(value):
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def plist_payload(info, port, python=sys.executable):
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), str(info["dashboard"]), "--port", str(port)],
        "WorkingDirectory": str(info["working_directory"]),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "StandardOutPath": str(info["log"]),
        "StandardErrorPath": str(info["error_log"]),
    }


def write_plist(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            plistlib.dump(payload, handle, sort_keys=True)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def domain():
    return f"gui/{os.getuid()}"


def run_launchctl(*arguments, check=True):
    return subprocess.run(["launchctl", *arguments], text=True, capture_output=True, check=check)


def installed_port(plist_path):
    try:
        with plist_path.open("rb") as handle:
            payload = plistlib.load(handle)
        arguments = payload.get("ProgramArguments", [])
        index = arguments.index("--port")
        return int(arguments[index + 1])
    except (FileNotFoundError, ValueError, IndexError, TypeError, plistlib.InvalidFileException):
        return None


def service_loaded():
    result = run_launchctl("print", f"{domain()}/{LABEL}", check=False)
    return result.returncode == 0


def http_ready(port, timeout=0.5):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def enable(info, port):
    if sys.platform != "darwin":
        raise SystemExit("dashboard auto-start currently supports macOS launchd only")
    if not info["dashboard"].is_file():
        raise SystemExit(f"dashboard not found: {info['dashboard']}")
    info["state"].mkdir(parents=True, exist_ok=True)
    loaded = service_loaded()
    if http_ready(port) and not loaded:
        raise SystemExit(f"port {port} already serves HTTP outside the Tierwork LaunchAgent; stop it before enabling")
    if loaded:
        run_launchctl("bootout", domain(), str(info["plist"]), check=False)
    write_plist(info["plist"], plist_payload(info, port))
    run_launchctl("bootstrap", domain(), str(info["plist"]))
    run_launchctl("enable", f"{domain()}/{LABEL}")
    run_launchctl("kickstart", "-k", f"{domain()}/{LABEL}")
    print(f"enabled: http://127.0.0.1:{port}")


def disable(info):
    if sys.platform != "darwin":
        raise SystemExit("dashboard auto-start currently supports macOS launchd only")
    run_launchctl("bootout", domain(), str(info["plist"]), check=False)
    info["plist"].unlink(missing_ok=True)
    print("disabled")


def start(info):
    if not info["plist"].is_file():
        raise SystemExit("dashboard service is not enabled")
    if service_loaded():
        run_launchctl("kickstart", "-k", f"{domain()}/{LABEL}")
    else:
        run_launchctl("bootstrap", domain(), str(info["plist"]))
        run_launchctl("enable", f"{domain()}/{LABEL}")
    print("started")


def stop(info):
    if not service_loaded():
        print("already stopped")
        return
    run_launchctl("bootout", domain(), str(info["plist"]), check=False)
    print("stopped; auto-start remains enabled for the next login or explicit start")


def status(info):
    port = installed_port(info["plist"]) or 8765
    payload = {
        "enabled": info["plist"].is_file(),
        "loaded": service_loaded() if sys.platform == "darwin" else False,
        "ready": http_ready(port),
        "url": f"http://127.0.0.1:{port}",
        "port": port,
        "plist": str(info["plist"]),
        "log": str(info["log"]),
        "errorLog": str(info["error_log"]),
    }
    print("\n".join(f"{key}: {value}" for key, value in payload.items()))
    return 0 if payload["ready"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("enable", "disable", "start", "stop", "restart", "status"))
    parser.add_argument("--port", type=validate_port, default=8765)
    args = parser.parse_args()
    info = paths()
    if args.action == "enable":
        enable(info, args.port)
    elif args.action == "disable":
        disable(info)
    elif args.action == "start":
        start(info)
    elif args.action == "stop":
        stop(info)
    elif args.action == "restart":
        start(info)
    else:
        return status(info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
