#!/usr/bin/env python3
"""Dependency-free HTTP build/test/download client. Token comes only from environment."""

import argparse
import hashlib
import io
import json
import os
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "resource_limit_exceeded"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--output", type=Path, default=Path("downloaded-artifacts"))
    args = parser.parse_args()
    base = os.environ.get("GRADLEMCP_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.environ["GRADLEMCP_TOKEN"]

    def request(path, body=None, content_type="application/json"):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        req = urllib.request.Request(
            base + path,
            data=body,
            headers={"Authorization": "Bearer " + token, "Content-Type": content_type},
        )
        return urllib.request.urlopen(req, timeout=30)

    def api(path, body=None, content_type="application/json"):
        with request(path, body, content_type) as response:
            return json.load(response)

    capability = api("/api/v1/capabilities")
    stream = io.BytesIO()
    excluded = {".git", ".gradle", ".venv", "build", "node_modules", "data", "downloaded-artifacts"}
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(args.project.rglob("*")):
            relative = path.relative_to(args.project)
            if path.is_symlink():
                raise ValueError("Remove symbolic links before upload")
            if path.is_file() and not excluded.intersection(relative.parts):
                if path.name.startswith(".env") or path.name.endswith((".local", ".key", ".pem")):
                    raise ValueError("Potential secret file detected; review archive before upload")
                archive.write(path, relative)
    if len(stream.getvalue()) > capability["limits"]["upload_mb"] * 1024**2:
        raise ValueError("Archive exceeds server upload limit")
    uploaded = api("/api/v1/projects", stream.getvalue(), "application/zip")
    print(json.dumps(uploaded["inspection"], indent=2))
    tasks = args.tasks or ["build"]
    key = hashlib.sha256(
        uploaded["project_id"].encode() + stream.getvalue() + json.dumps(tasks).encode()
    ).hexdigest()
    spec = {"project_id": uploaded["project_id"], "tasks": tasks, "idempotency_key": key}
    api("/api/v1/projects/compatibility", spec)
    result = api("/api/v1/builds", spec)
    identifier = result["id"]
    print("Job:", identifier)
    deadline = time.monotonic() + 3600
    while result["state"] not in TERMINAL:
        if time.monotonic() > deadline:
            raise TimeoutError("Client wait ended; job may still be queued/running. Save its ID.")
        print(result["state"])
        time.sleep(3)
        result = api(f"/api/v1/builds/{identifier}")
    offset = 0
    while True:
        log = api(f"/api/v1/builds/{identifier}/logs?offset={offset}")
        print(log["text"], end="")
        offset = log["next_offset"]
        if log["eof"]:
            break
    if result["state"] != "succeeded":
        print(json.dumps(result["diagnostic"], indent=2))
        raise SystemExit(1)
    args.output.mkdir(parents=True, exist_ok=True)
    for artifact in api(f"/api/v1/builds/{identifier}/artifacts"):
        destination = args.output / (artifact["id"] + "-" + Path(artifact["path"]).name)
        with request(f"/api/v1/builds/{identifier}/artifacts/{artifact['id']}") as response:
            with destination.open("wb") as output:
                shutil.copyfileobj(response, output, length=65536)
        with destination.open("rb") as downloaded:
            digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if digest != artifact["sha256"]:
            destination.unlink()
            raise ValueError("Artifact SHA-256 mismatch")
        print("Downloaded", destination)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        print("HTTP error", error.code, error.read(65536).decode(errors="replace"))
        raise SystemExit(1) from None
