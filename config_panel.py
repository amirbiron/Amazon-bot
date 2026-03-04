"""
Launch the secure settings web panel.

Usage:
    python config_panel.py              # http://localhost:5000
    python config_panel.py --port 8080  # custom port
"""
import argparse

from app.web.server import app


def main():
    parser = argparse.ArgumentParser(description="Secure settings panel")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    print(f"\n🔐  פאנל הגדרות פועל על http://localhost:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
