"""Serves this folder on http://localhost:8000 with caching switched off, so a normal reload always shows the newest files.

    python serve.py

(`python -m http.server 8000` works too, but browsers may keep old copies of the JavaScript files; then use Ctrl+Shift+R.)
Local development only.
"""
import http.server
import socketserver


class NoStoreHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 8000), NoStoreHandler) as server:
        print("Serving the frontend on http://localhost:8000 (no caching). Press Ctrl+C to stop.")
        server.serve_forever()
