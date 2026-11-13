"""Thin client: send one command to the daemon over its Unix socket."""

import json
import socket
import subprocess
import sys
import time

from . import paths


class DaemonNotRunning(Exception):
    pass


def send(command: str, **args) -> dict:
    """Send {"cmd": command, ...args} and return the daemon's JSON reply."""
    path = paths.socket_file()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect(str(path))
            s.sendall((json.dumps({"cmd": command, **args}) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
    except (FileNotFoundError, ConnectionRefusedError) as e:
        raise DaemonNotRunning(str(path)) from e
    return json.loads(data or b"{}")


def is_running() -> bool:
    try:
        send("ping")
        return True
    except (DaemonNotRunning, OSError, json.JSONDecodeError):
        return False


def start_daemon(timeout: float = 15.0) -> bool:
    """Start the daemon in the background and wait until it answers."""
    subprocess.Popen([sys.executable, "-m", "floatnote", "daemon"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running():
            return True
        time.sleep(0.2)
    return False
