#!/usr/bin/env python3
"""Get a Spotify refresh token (stdlib only, localhost callback).

Usage:
  SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... python3 scripts/get-spotify-token.py [--port 8888]

Steps:
  1. Create an app at the Spotify developer dashboard, add
     http://localhost:8888/callback (or your --port) as redirect URI.
  2. Run this script; it prints an authorize URL — open it as masu33-music.
  3. Approve the minimal scopes; the script exchanges the code and prints
     the refresh token. Store it in $SPOTIFY_REFRESH (env only, never commit).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from music_catalog.publish_config import SPOTIFY_SCOPES

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8888)
    args = ap.parse_args()
    cid = os.environ.get("SPOTIFY_CLIENT_ID")
    secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not cid or not secret:
        print("error: set SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET in env", file=sys.stderr)
        return 2
    redirect = f"http://localhost:{args.port}/callback"
    params = urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": redirect,
        "scope": SPOTIFY_SCOPES,
    })
    print(f"Open as your music account:\n{AUTH_URL}?{params}\n")
    print(f"Listening on {redirect} ...", flush=True)
    code_box: dict = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("code"):
                code_box["code"] = q["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK - back to terminal")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"missing ?code= (did you deny?)")

        def log_message(self, *a):  # quiet
            pass

    HTTPServer(("127.0.0.1", args.port), H).handle_request()
    if "code" not in code_box:
        print("error: no code received", file=sys.stderr)
        return 1
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": code_box["code"],
        "redirect_uri": redirect,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    print("\nStore in env (never commit):")
    print(f"  export SPOTIFY_REFRESH={data.get('refresh_token', '')}")
    print(f"  (access token, 1h: {str(data.get('access_token', ''))[:12]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
