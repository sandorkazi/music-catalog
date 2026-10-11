#!/usr/bin/env python3
"""Get a YouTube refresh token (stdlib only, localhost callback).

Usage:
  YOUTUBE_CLIENT_ID=... YOUTUBE_CLIENT_SECRET=... python3 scripts/get-youtube-token.py [--port 8899]

Steps:
  1. Google Cloud Console: new project -> enable YouTube Data API v3.
  2. OAuth consent (External) -> add masu33-music@proton.me as test user.
  3. Credentials -> OAuth client ID (Desktop) -> set env vars from it.
  4. Run this script, open the printed URL as the music account, approve
     the youtube.force-ssl scope only. Store $YOUTUBE_REFRESH (env only).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from music_catalog.publish_config import YOUTUBE_SCOPES

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    args = ap.parse_args()
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    if not cid or not secret:
        print("error: set YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET in env", file=sys.stderr)
        return 2
    redirect = f"http://localhost:{args.port}/callback"
    params = urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": redirect,
        "scope": YOUTUBE_SCOPES, "access_type": "offline", "prompt": "consent",
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
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": code_box["code"],
        "client_id": cid, "client_secret": secret, "redirect_uri": redirect,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    print("\nStore in env (never commit):")
    print(f"  export YOUTUBE_REFRESH={data.get('refresh_token', '')}")
    print(f"  (access token, 1h: {str(data.get('access_token', ''))[:12]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
