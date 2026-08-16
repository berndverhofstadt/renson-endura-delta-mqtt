import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthMonitor:
    def __init__(self, interval_seconds):
        self.interval_seconds = interval_seconds
        self.lock = threading.Lock()
        self.last_success_epoch = 0.0

    def record_success(self):
        with self.lock:
            self.last_success_epoch = time.monotonic()

    def is_healthy(self):
        with self.lock:
            return (time.monotonic() - self.last_success_epoch) <= (3 * self.interval_seconds)

    def start_http_server(self, host, port):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path not in ("/health", "/healthz"):
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"not found\n")
                    return
                if self.server.health_monitor.is_healthy():
                    self.send_response(200)
                    body = b"ok\n"
                else:
                    self.send_response(503)
                    body = b"unhealthy\n"
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer((host, port), Handler)
        server.health_monitor = self
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server
