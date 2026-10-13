"""python -m webapp  ->  start the server and open a browser."""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

# allow `python -m webapp` from anywhere / from a frozen bundle
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import uvicorn


def main():
    ap = argparse.ArgumentParser(prog="webapp", description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    url = f"http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"\n  STL -> CAD Converter  —  {url}\n  (Ctrl+C to stop)\n")
    uvicorn.run("webapp.server:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
