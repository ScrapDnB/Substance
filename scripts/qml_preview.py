"""Run Substance through Qt's QML Live Preview MCP server using its PySide runtime."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


class PreviewServer:
    def __init__(self, executable: Path, environment: dict, log=None):
        self.process = subprocess.Popen(
            [str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=log, env=environment, start_new_session=True,
        )
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.sequence = 0

    def send(self, method, params, request_id=None):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            message["id"] = request_id
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()

    def request(self, method, params, timeout=30):
        self.sequence += 1
        request_id = self.sequence
        self.send(method, params, request_id)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                message = json.loads(line)
                if message.get("id") == request_id:
                    if "error" in message:
                        raise RuntimeError(str(message["error"]))
                    return message["result"]
            if not self.selector.select(min(.25, max(0, deadline - time.monotonic()))):
                continue
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("QML Preview server exited before replying")
            self.buffer += chunk
        raise RuntimeError(f"QML Preview server did not reply to {method} within {timeout}s")

    def close(self):
        # Qt launches the previewed application as a child. Stop the whole
        # session, including that child, when this development command exits.
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait()
        self.selector.close()
        self.process.stdin.close()
        self.process.stdout.close()


def preview_environment():
    import PySide6
    from PySide6.QtCore import qVersion
    if tuple(map(int, qVersion().split(".")[:2])) < (6, 12):
        raise RuntimeError("Install PySide6 6.12 or newer in this Python environment")
    environment = os.environ.copy()
    if sys.platform == "darwin":
        # The separately installed MCP component can lack the Qt frameworks.
        # Use exactly the same Qt libraries as the application being previewed.
        frameworks = str(Path(PySide6.__file__).parent / "Qt" / "lib")
        previous = environment.get("DYLD_FRAMEWORK_PATH")
        environment["DYLD_FRAMEWORK_PATH"] = frameworks + (":" + previous if previous else "")
    environment.setdefault("SUBSTANCE_DATA_DIR", str(ROOT / "local" / "qml-preview-state"))
    return environment


def write_launcher(path: Path, app_arguments: list[str]):
    command = [sys.executable, str(ROOT / "run.py"), "--qml-preview", *app_arguments]
    path.write_text("#!/bin/sh\ncd " + shlex.quote(str(ROOT)) + "\nexec " + shlex.join(command) + ' "$@"\n')
    path.chmod(0o700)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, default=Path.home() / "Qt/6.12.0/macos/bin/QmlPreviewMcpServer")
    parser.add_argument("--check", action="store_true", help="Check server connectivity without opening Substance")
    parser.add_argument("app_arguments", nargs=argparse.REMAINDER, help="Substance arguments after --")
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("This launcher currently supports macOS and Linux")
    if not args.server.is_file():
        parser.error(f"QML Preview MCP server was not found: {args.server}")
    server = None
    log = None
    log_reader = None
    try:
        environment = preview_environment()
        log_path = ROOT / 'local/qml-preview.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open('w')
        log_reader = log_path.open('r')
        server = PreviewServer(args.server.resolve(), environment, log=log)
        server.request("initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "Substance QML Preview", "version": "1.0"},
        })
        server.send("notifications/initialized", {})
        tools = server.request("tools/list", {})
        if not any(tool["name"] == "run_qmlPreview" for tool in tools.get("tools", [])):
            raise RuntimeError("The server does not provide run_qmlPreview")
        if args.check:
            print("Qt 6.12+ and QML Live Preview MCP: OK")
            return 0
        app_arguments = args.app_arguments
        if app_arguments[:1] == ["--"]:
            app_arguments = app_arguments[1:]
        with tempfile.TemporaryDirectory(prefix="substance-qml-preview-") as directory:
            launcher = Path(directory) / "Substance-preview"
            write_launcher(launcher, app_arguments)
            result = server.request("tools/call", {
                "name": "run_qmlPreview", "arguments": {"executable_path": str(launcher)},
            })
            if result.get("isError"):
                raise RuntimeError(str(result.get("content", result)))
            print("Предпросмотр Substance запущен. Сохраняй QML, чтобы увидеть изменения.", flush=True)
            print("Остановить предпросмотр: Ctrl+C в этом окне терминала.", flush=True)
            print(f"Журнал: {log_path}", flush=True)
            log_buffer = ''
            while server.process.poll() is None:
                # The MCP server stays alive after its Qt child exits. Follow
                # that child's status so closing Substance also closes this command.
                log_buffer += log_reader.read()
                exited = re.search(r'Process exited \((-?\d+)\)', log_buffer)
                if exited:
                    return int(exited.group(1))
                if 'Process crashed!' in log_buffer:
                    raise RuntimeError(f'The previewed application crashed. Restart the preview; details: {log_path}')
                log_buffer = log_buffer[-4096:]
                time.sleep(.25)
            return server.process.returncode or 0
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"QML Preview: {error}", file=sys.stderr)
        return 1
    finally:
        if server:
            server.close()
        if log:
            log.close()
        if log_reader:
            log_reader.close()


if __name__ == "__main__":
    raise SystemExit(main())
