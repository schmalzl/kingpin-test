"""Entry point. Usage: python run.py  (init-db happens automatically on first start)."""
import os
from game import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("KINGPIN_HOST", "127.0.0.1")
    port = int(os.environ.get("KINGPIN_PORT", "5000"))
    # debug is deliberately off; use a production WSGI server (e.g. waitress) when exposing publicly.
    app.run(host=host, port=port, debug=False)
