#!/usr/bin/env python3
"""Manage an explicitly selected batch through the authenticated website API."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "detail", "review", "publish", "download", "authorize"))
    parser.add_argument("--base", default="https://study-hub.cn")
    parser.add_argument("--batch", type=int)
    parser.add_argument("--item", type=int)
    parser.add_argument("--payload", type=Path, help="JSON file for review/publish; price is in cents")
    parser.add_argument("--output", type=Path, help="Private output file; existing files are never overwritten")
    args = parser.parse_args()
    base = urlsplit(args.base)
    if base.scheme != "https" or not base.hostname or base.username or base.password or base.query or base.fragment:
        parser.error("--base must be an HTTPS origin")
    token = os.environ.get("STUDYHUB_ADMIN_TOKEN", "")
    if not token:
        parser.error("Set STUDYHUB_ADMIN_TOKEN to an existing administrator session token")
    if args.command != "list" and not args.batch:
        parser.error("--batch is required")
    endpoint = "/api/admin/batch-submissions"
    if args.batch:
        endpoint += f"/{args.batch}"
    payload = None
    if args.command in {"review", "publish", "authorize"}:
        if not args.payload:
            parser.error("--payload is required; this command changes the selected batch")
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        endpoint += "/access-token" if args.command == "authorize" else f"/{args.command}"
    if args.command == "download":
        if not args.item or not args.output:
            parser.error("download requires --item and --output")
        endpoint += f"/items/{args.item}/file"
    # Never send the administrator credential to redirected URLs.
    with httpx.Client(base_url=args.base.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                      timeout=300, follow_redirects=False) as client:
        if args.command == "download":
            with client.stream("GET", endpoint) as response:
                response.raise_for_status()
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(fd, "wb") as output:
                        for chunk in response.iter_bytes():
                            output.write(chunk)
                except BaseException:
                    args.output.unlink(missing_ok=True)
                    raise
            print("Downloaded selected file")
            return 0
        response = client.post(endpoint, json=payload) if payload is not None else client.get(endpoint)
        response.raise_for_status()
        result = json.dumps(response.json(), ensure_ascii=False, indent=2)
        if args.output:
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(result + "\n")
        else:
            print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
