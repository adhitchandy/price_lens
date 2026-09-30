"""Start the web app:  python -m price_lens.webapp  [--port 8765] [--no-browser]"""
from __future__ import annotations

import argparse
import threading
import webbrowser

from .server import make_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Price Lens web app")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args()
    try:
        server = make_server(args.port, args.verbose)
    except OSError:
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Port {args.port} is in use; the app is probably already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Price Lens is running at {url}  (close this window to stop it)")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
