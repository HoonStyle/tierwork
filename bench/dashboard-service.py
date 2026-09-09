#!/usr/bin/env python3
"""Manage optional Tierwork dashboard auto-start on macOS, Windows, and Linux."""

import argparse
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

LABEL = "com.hoonstyle.tierwork.dashboard"
WINDOWS_TASK = "Tierwork Dashboard"
SYSTEMD_UNIT = "tierwork-dashboard.service"


def platform_name(value=None):
    value = value or sys.platform
    if value == "darwin":
        return "macos"
    if value == "win32":
        return "windows"
    if value.startswith("linux"):
        return "linux"
    raise SystemExit(f"unsupported platform: {value}")


def paths(home=None):
    home = Path(home) if home else Path.home()
    state = home / ".tierwork"
    return {
        "mac_plist": home / "Library" / "LaunchAgents" / f"{LABEL}.plist",
        "windows_cmd": state / "dashboard.cmd",
        "linux_unit": home / ".config" / "systemd" / "user" / SYSTEMD_UNIT,
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


def mac_plist(info, port, python=sys.executable):
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


def windows_script(info, port, python=sys.executable):
    def quote(value):
        return f'"{str(value).replace(chr(34), chr(34) * 2)}"'
    return (
        "@echo off\r\n"
        f"cd /d {quote(info['working_directory'])}\r\n"
        f"{quote(python)} {quote(info['dashboard'])} --port {port} "
        f">>{quote(info['log'])} 2>>{quote(info['error_log'])}\r\n"
    )


def systemd_service(info, port, python=sys.executable):
    command = " ".join(shlex.quote(str(value)) for value in (python, info["dashboard"], "--port", port))
    return "\n".join([
        "[Unit]",
        "Description=Tierwork local dashboard",
        "After=default.target",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={info['working_directory']}",
        f"ExecStart={command}",
        "Restart=on-failure",
        "RestartSec=10",
        f"StandardOutput=append:{info['log']}",
        f"StandardError=append:{info['error_log']}",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def atomic_write(path, content, mode=0o644, binary=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if binary:
            with os.fdopen(fd, "wb") as handle:
                plistlib.dump(content, handle, sort_keys=True)
        else:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def run(command, check=True):
    return subprocess.run(command, text=True, capture_output=True, check=check)


def mac_domain():
    return f"gui/{os.getuid()}"


def service_loaded(kind):
    if kind == "macos":
        return run(["launchctl", "print", f"{mac_domain()}/{LABEL}"], check=False).returncode == 0
    if kind == "windows":
        return run(["schtasks.exe", "/Query", "/TN", WINDOWS_TASK], check=False).returncode == 0
    return run(["systemctl", "--user", "is-active", "--quiet", SYSTEMD_UNIT], check=False).returncode == 0


def installed(kind, info):
    if kind == "macos":
        return info["mac_plist"].is_file()
    if kind == "windows":
        return info["windows_cmd"].is_file() and service_loaded(kind)
    return info["linux_unit"].is_file()


def installed_port(kind, info):
    try:
        if kind == "macos":
            with info["mac_plist"].open("rb") as handle:
                arguments = plistlib.load(handle).get("ProgramArguments", [])
            return int(arguments[arguments.index("--port") + 1])
        if kind == "windows":
            text = info["windows_cmd"].read_text(encoding="utf-8")
        else:
            text = info["linux_unit"].read_text(encoding="utf-8")
        marker = "--port "
        return int(text.split(marker, 1)[1].split()[0])
    except (FileNotFoundError, ValueError, IndexError, TypeError, plistlib.InvalidFileException):
        return None


def http_ready(port, timeout=0.5):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def enable(kind, info, port):
    if not info["dashboard"].is_file():
        raise SystemExit(f"dashboard not found: {info['dashboard']}")
    info["state"].mkdir(parents=True, exist_ok=True)
    loaded = service_loaded(kind)
    if http_ready(port) and not loaded:
        raise SystemExit(f"port {port} already serves HTTP outside the Tierwork service; stop it before enabling")
    if kind == "macos":
        if loaded:
            run(["launchctl", "bootout", mac_domain(), str(info["mac_plist"])], check=False)
        atomic_write(info["mac_plist"], mac_plist(info, port), binary=True)
        run(["launchctl", "bootstrap", mac_domain(), str(info["mac_plist"])])
        run(["launchctl", "enable", f"{mac_domain()}/{LABEL}"])
        run(["launchctl", "kickstart", "-k", f"{mac_domain()}/{LABEL}"])
    elif kind == "windows":
        atomic_write(info["windows_cmd"], windows_script(info, port))
        action = f'cmd.exe /d /c ""{info["windows_cmd"]}""'
        run(["schtasks.exe", "/Create", "/F", "/TN", WINDOWS_TASK, "/SC", "ONLOGON", "/RL", "LIMITED", "/TR", action])
        run(["schtasks.exe", "/Run", "/TN", WINDOWS_TASK])
    else:
        atomic_write(info["linux_unit"], systemd_service(info, port))
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT])
    print(f"enabled ({kind}): http://127.0.0.1:{port}")


def disable(kind, info):
    if kind == "macos":
        run(["launchctl", "bootout", mac_domain(), str(info["mac_plist"])], check=False)
        info["mac_plist"].unlink(missing_ok=True)
    elif kind == "windows":
        run(["schtasks.exe", "/End", "/TN", WINDOWS_TASK], check=False)
        run(["schtasks.exe", "/Delete", "/F", "/TN", WINDOWS_TASK], check=False)
        info["windows_cmd"].unlink(missing_ok=True)
    else:
        run(["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT], check=False)
        info["linux_unit"].unlink(missing_ok=True)
        run(["systemctl", "--user", "daemon-reload"])
    print(f"disabled ({kind})")


def start(kind, info):
    if not installed(kind, info):
        raise SystemExit("dashboard service is not enabled")
    if kind == "macos":
        if service_loaded(kind):
            run(["launchctl", "kickstart", "-k", f"{mac_domain()}/{LABEL}"])
        else:
            run(["launchctl", "bootstrap", mac_domain(), str(info["mac_plist"])])
    elif kind == "windows":
        run(["schtasks.exe", "/Run", "/TN", WINDOWS_TASK])
    else:
        run(["systemctl", "--user", "start", SYSTEMD_UNIT])
    print(f"started ({kind})")


def stop(kind, info):
    if kind == "macos":
        run(["launchctl", "bootout", mac_domain(), str(info["mac_plist"])], check=False)
    elif kind == "windows":
        run(["schtasks.exe", "/End", "/TN", WINDOWS_TASK], check=False)
    else:
        run(["systemctl", "--user", "stop", SYSTEMD_UNIT], check=False)
    print(f"stopped ({kind}); auto-start remains enabled")


def status(kind, info):
    port = installed_port(kind, info) or 8765
    payload = {
        "platform": kind,
        "enabled": installed(kind, info),
        "loaded": service_loaded(kind),
        "ready": http_ready(port),
        "url": f"http://127.0.0.1:{port}",
        "port": port,
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
    kind, info = platform_name(), paths()
    if args.action == "enable":
        enable(kind, info, args.port)
    elif args.action == "disable":
        disable(kind, info)
    elif args.action == "start":
        start(kind, info)
    elif args.action == "stop":
        stop(kind, info)
    elif args.action == "restart":
        stop(kind, info)
        start(kind, info)
    else:
        return status(kind, info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
