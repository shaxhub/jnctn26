"""Run both local Agent Dairy servers under one foreground supervisor."""

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


APP_DIR = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
APPS = (
    ("Client workspace", "gateway.api:app"),
    ("Aimo operations", "gateway.admin_app:app"),
)


def port_number(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def serve(app: str, host: str, port: int) -> int:
    import uvicorn

    sys.path.insert(0, str(APP_DIR))
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, proxy_headers=False))

    def watch_supervisor() -> None:
        # EOF also arrives if the supervisor exits unexpectedly.
        sys.stdin.buffer.read(1)
        server.should_exit = True

    threading.Thread(target=watch_supervisor, daemon=True).start()
    server.run()
    return 0 if server.started else 1


def stop_children(children: list[subprocess.Popen]) -> None:
    for child in children:
        child.stdin.close()
    deadline = time.monotonic() + 8
    for child in children:
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def run_pair(client_port: int, admin_port: int, host: str) -> int:
    stopping = threading.Event()
    signals = [signal.SIGINT, signal.SIGTERM]
    if os.name == "nt":
        signals.append(signal.SIGBREAK)
    previous = {sig: signal.signal(sig, lambda *_: stopping.set()) for sig in signals}
    children = []
    process_group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                     if os.name == "nt" else {"start_new_session": True})
    try:
        for (label, app), port in zip(APPS, (client_port, admin_port)):
            print(f"{label} will listen on http://{host}:{port}/", flush=True)
            child = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--serve", app, host, str(port)],
                cwd=APP_DIR, stdin=subprocess.PIPE, **process_group,
            )
            children.append(child)
        print("Press Ctrl+C to stop both servers.", flush=True)
        while not stopping.wait(0.15):
            for child, (label, _) in zip(children, APPS):
                if child.poll() is not None:
                    print(f"{label} exited (code {child.returncode}). Stopping both servers.", file=sys.stderr)
                    return 1
        return 0
    except OSError as exc:
        print(f"Could not start Agent Dairy: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            stop_children(children)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--serve":
        return serve(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=HOST, help="Bind address for both portals")
    parser.add_argument("--client-port", type=port_number, default=8000)
    parser.add_argument("--admin-port", type=port_number, default=8001)
    args = parser.parse_args()
    if args.client_port == args.admin_port:
        parser.error("the client and admin ports must be different")
    return run_pair(args.client_port, args.admin_port, args.host)


if __name__ == "__main__":
    sys.exit(main())
