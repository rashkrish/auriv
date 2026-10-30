"""Single entry point for the Personal Capability Agent.

    main.py  ->  server.py (web routes)
             ->  orchestrator.py (routing, safety gates, skills)
             ->  app.py (model client, search, prompt loading, logging)

Run locally:
    python main.py
Then open http://127.0.0.1:5000

On a hosting platform, the platform sets PORT and the server listens on all interfaces.
"""

import os
import sys

REQUIRED_KEYS = ["NEBIUS_API_KEY", "TAVILY_API_KEY"]


def check_environment():
    missing = [name for name in REQUIRED_KEYS if not os.environ.get(name)]
    if missing:
        print("Missing environment variables:", ", ".join(missing))
        print("Set them in this window first, for example:")
        print("  set NEBIUS_API_KEY=your-key")
        print("  set TAVILY_API_KEY=your-key")
        sys.exit(1)


def main():
    check_environment()

    # Imported after the check, because app.py creates its API clients on import.
    import server

    hosted_port = os.environ.get("PORT")
    if hosted_port:
        host, port = "0.0.0.0", int(hosted_port)
    else:
        host, port = "127.0.0.1", 5000

    print(f"Personal Capability Agent running on http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.web.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
