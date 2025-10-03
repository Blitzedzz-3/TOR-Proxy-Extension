#!/usr/bin/env python3
import argparse
import socket
import threading
import select
import http.server
import urllib.parse
import requests
import socks
from socketserver import ThreadingMixIn, TCPServer
import os
import subprocess
import time
import traceback
import sys

parser = argparse.ArgumentParser(description="HTTP -> SOCKS5 proxy")
parser.add_argument("--listen", default="127.0.0.1:8080")
parser.add_argument("--socks", default="127.0.0.1:9050")
parser.add_argument("--verbose", action="store_true")
args = parser.parse_args()

LISTEN_HOST, LISTEN_PORT = args.listen.split(":")
LISTEN_PORT = int(LISTEN_PORT)
SOCKS_HOST, SOCKS_PORT = args.socks.split(":")
SOCKS_PORT = int(SOCKS_PORT)
PROXY_URI = f"socks5h://{SOCKS_HOST}:{SOCKS_PORT}"

VERBOSE = args.verbose

session = requests.Session()
session.proxies.update({"http": PROXY_URI, "https": PROXY_URI})

def main():

    def log(*a, **k):
        if VERBOSE:
            print(*a, **k)

    def log_error(e):
        with open("log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {str(e)}\n")
            f.write(traceback.format_exc() + "\n")

    def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    def is_tor_process_running() -> bool:
        try:
            import psutil
            for p in psutil.process_iter(['name']):
                name = (p.info.get('name') or "").lower()
                if name in ('tor.exe', 'tor'):
                    return True
        except Exception:
            pass
        if os.name == 'nt':
            try:
                out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq tor.exe"], stderr=subprocess.DEVNULL, text=True)
                return 'tor.exe' in out.lower()
            except Exception:
                return False
        else:
            try:
                subprocess.check_output(["pgrep", "-f", "tor"], stderr=subprocess.DEVNULL)
                return True
            except Exception:
                return False

    def start_tor_exe_in_cwd(verbose=False) -> bool:
        tor_path = os.path.join(os.getcwd(), "tor.exe")
        if not os.path.isfile(tor_path):
            if verbose: print("[tor] tor.exe not found in cwd")
            return False
        if os.name == 'nt':
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            DETACHED_PROCESS = 0x00000008
            flags = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
            try:
                subprocess.Popen([tor_path], cwd=os.getcwd(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=flags)
                return True
            except Exception:
                try:
                    subprocess.Popen([tor_path], cwd=os.getcwd())
                    return True
                except Exception:
                    return False
        else:
            try:
                subprocess.Popen([tor_path], cwd=os.getcwd(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                return True
            except Exception:
                return False

    def ensure_tor_running(verbose: bool = False):
        if VERBOSE: print("[tor] ensuring tor is running...")
        while True:
            if is_port_open(SOCKS_HOST, SOCKS_PORT, timeout=1.0):
                if verbose: print(f"[tor] SOCKS {SOCKS_HOST}:{SOCKS_PORT} reachable")
                break
            if not is_tor_process_running():
                start_tor_exe_in_cwd(verbose=verbose)
            elapsed = int(time.time() % 1000000)
            print(f"\rStill loading... Proxy may not work until this is over ({elapsed}s)", end="")
            time.sleep(1)
        print()

    def pipe_sockets(a: socket.socket, b: socket.socket):
        a.setblocking(False)
        b.setblocking(False)
        sockets = [a, b]
        try:
            while True:
                r, _, _ = select.select(sockets, [], [], 10)
                if not r: continue
                for s in r:
                    try:
                        data = s.recv(8192)
                    except (BlockingIOError, InterruptedError):
                        continue
                    if not data: return
                    other = b if s is a else a
                    try:
                        other.sendall(data)
                    except BrokenPipeError:
                        return
        finally:
            try: a.close()
            except Exception: pass
            try: b.close()
            except Exception: pass

    class ProxyHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_CONNECT(self):
            hostport = self.path
            log(f"[CONNECT] {hostport} from {self.client_address}")
            try:
                host, port = hostport.split(":")
                port = int(port)
                remote = socks.socksocket()
                remote.set_proxy(socks.SOCKS5, SOCKS_HOST, SOCKS_PORT)
                remote.connect((host, port))
                self.send_response(200, "Connection Established")
                self.send_header("Proxy-agent", "python-http-to-socks/1.0")
                self.end_headers()
                pipe_sockets(self.connection, remote)
            except Exception as e:
                log_error(e)

        def _is_absolute_url(self, url_text):
            return urllib.parse.urlsplit(url_text).scheme != ""

        def _forward_via_requests(self):
            try:
                if self._is_absolute_url(self.path):
                    target_url = self.path
                else:
                    host = self.headers.get("Host")
                    if not host:
                        self.send_error(400, "Missing Host header")
                        return
                    target_url = f"http://{host}{self.path}"
                log(f"[HTTP] {self.command} {target_url} from {self.client_address}")
                excluded_headers = [
                    "Proxy-Connection", "Connection", "Keep-Alive", "Proxy-Authenticate",
                    "Proxy-Authorization", "TE", "Trailers", "Transfer-Encoding", "Upgrade"
                ]
                headers = {k: v for k, v in self.headers.items() if k not in excluded_headers}
                body = None
                if "Content-Length" in self.headers:
                    try:
                        length = int(self.headers["Content-Length"])
                        body = self.rfile.read(length)
                    except Exception:
                        body = None
                resp = session.request(
                    method=self.command,
                    url=target_url,
                    headers=headers,
                    data=body,
                    allow_redirects=False,
                    timeout=30,
                    stream=False
                )
                self.send_response(resp.status_code)
                for key, value in resp.headers.items():
                    if key in excluded_headers: continue
                    self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                if resp.content: self.wfile.write(resp.content)
            except Exception as e:
                log_error(e)

        do_GET = _forward_via_requests
        do_POST = _forward_via_requests
        do_PUT = _forward_via_requests
        do_DELETE = _forward_via_requests
        do_OPTIONS = _forward_via_requests
        do_HEAD = _forward_via_requests
        do_PATCH = _forward_via_requests
        do_TRACE = _forward_via_requests

        def log_message(self, format, *args):
            pass  # silence default server messages

    class ThreadingHTTPServer(ThreadingMixIn, TCPServer):
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            exc_type, exc_value, exc_traceback = sys.exc_info()
            if exc_value:
                log_error(exc_value)

    ensure_tor_running(verbose=VERBOSE)
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ProxyHTTPRequestHandler)
    print(f"HTTP->SOCKS proxy listening on {LISTEN_HOST}:{LISTEN_PORT} -> SOCKS5 {SOCKS_HOST}:{SOCKS_PORT}")
    print("Verbose:", VERBOSE)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
