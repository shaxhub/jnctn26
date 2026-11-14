"""Run the shared buyer workspace and admin panel on one HTTP server."""

import argparse
from pathlib import Path
import sys

APP_DIR = Path(__file__).resolve().parents[1]


def port_number(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main() -> int:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", "--client-port", dest="port", type=port_number, default=8000)
    args = parser.parse_args()
    sys.path.insert(0, str(APP_DIR))
    print(f"Workspace: http://{args.host}:{args.port}/", flush=True)
    print(f"Admin panel: http://{args.host}:{args.port}/admin/", flush=True)
    print("Press Ctrl+C to stop the server.", flush=True)
    server = uvicorn.Server(uvicorn.Config("gateway.api:app", host=args.host, port=args.port, proxy_headers=False))
    server.run()
    return 0 if server.started else 1


if __name__ == "__main__":
    sys.exit(main())
