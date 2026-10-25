#!/usr/bin/env python3
"""Local CONNECT forwarder so Playwright/Chromium can use the egress proxy.

Problem: Chromium on this VM cannot do proxy-auth against hatch-egress-proxy
(ERR_TUNNEL_CONNECTION_FAILED), and the proxy hostname resolves IPv6 first,
which hangs. This forwarder listens on 127.0.0.1:8888 (no auth needed) and,
for each CONNECT request, dials the upstream proxy at its IPv4 address
explicitly, injecting `Proxy-Authorization: Basic` from the $https_proxy
credentials. Credentials are read from the environment only and never written.

Usage:
    python3 proxy_fwd.py            # foreground
    # then point Chromium/Playwright at: --proxy-server=http://127.0.0.1:8888
"""

import base64
import os
import socket
import threading
import urllib.parse

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8888


def parse_upstream():
    raw = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or ""
    u = urllib.parse.urlparse(raw)
    if not u.hostname:
        raise RuntimeError("https_proxy env var is not set or has no hostname")
    creds = ""
    if u.username:
        creds = urllib.parse.unquote(u.username)
        if u.password:
            creds += ":" + urllib.parse.unquote(u.password)
    auth = ""
    if creds:
        auth = "Basic " + base64.b64encode(creds.encode()).decode()
    port = u.port or 3128
    # Resolve IPv4 EXPLICITLY: the hostname's AAAA record hangs from this VM.
    infos = socket.getaddrinfo(u.hostname, port, socket.AF_INET, socket.SOCK_STREAM)
    if not infos:
        raise RuntimeError(f"no IPv4 address for proxy host {u.hostname}")
    sockaddr = infos[0][4]
    return sockaddr, auth


def relay(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass


def read_headers(sock):
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        buf += chunk
        if len(buf) > 65536:
            return None
    return buf


def handle(client, upstream_sockaddr, proxy_auth):
    upstream = None
    try:
        buf = read_headers(client)
        if buf is None:
            return
        request_line = buf.split(b"\r\n", 1)[0].decode("latin1")
        parts = request_line.split(" ")
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        target = parts[1]

        upstream = socket.create_connection(upstream_sockaddr, timeout=30)
        req = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
        if proxy_auth:
            req += f"Proxy-Authorization: {proxy_auth}\r\n"
        req += "\r\n"
        upstream.sendall(req.encode("latin1"))

        rbuf = read_headers(upstream)
        if rbuf is None:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        status_line = rbuf.split(b"\r\n", 1)[0].decode("latin1")
        code = status_line.split(" ")[1] if len(status_line.split(" ")) > 1 else ""
        if code != "200":
            # Pass the upstream rejection through so the client sees the reason.
            client.sendall(rbuf)
            return
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

        t1 = threading.Thread(target=relay, args=(client, upstream), daemon=True)
        t2 = threading.Thread(target=relay, args=(upstream, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception:
        pass
    finally:
        for s in (client, upstream):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


def main():
    upstream_sockaddr, proxy_auth = parse_upstream()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(64)
    print(
        f"proxy_fwd listening on {LISTEN_HOST}:{LISTEN_PORT} "
        f"-> upstream {upstream_sockaddr[0]}:{upstream_sockaddr[1]} "
        f"(auth {'present' if proxy_auth else 'absent'})",
        flush=True,
    )
    while True:
        client, _ = srv.accept()
        threading.Thread(
            target=handle, args=(client, upstream_sockaddr, proxy_auth), daemon=True
        ).start()


if __name__ == "__main__":
    main()
