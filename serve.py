"""Production server (waitress, works on Windows). Binds to 127.0.0.1 only, so nothing is exposed on your LAN;
a tunnel (Cloudflare / Tailscale) connects to it locally and provides public HTTPS."""
import os

from waitress import serve

from game import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("KINGPIN_PORT", "5000"))
    print(f"Kingpin listening on http://127.0.0.1:{port}  (env={app.config['ENV']}, trusted proxies={app.config['TRUST_PROXY']})")
    serve(app, host="127.0.0.1", port=port, threads=8, max_request_body_size=6 * 1024 * 1024)
