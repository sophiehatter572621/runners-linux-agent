#!/usr/bin/env python3
"""Run one verified native fleet agent on a standard Linux Actions runner."""

import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request

MAX_BUNDLE_BYTES = 64 * 1024 * 1024
STOPPING = False


def configuration(env):
    origin = env.get("CONTROL_URL", "").rstrip("/")
    url = urllib.parse.urlsplit(origin)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.path or url.query or url.fragment):
        raise ValueError("CONTROL_URL must be an HTTPS origin")
    if not env.get("JOIN_TOKEN"):
        raise ValueError("Set the JOIN_TOKEN repository secret")
    minutes = int(env.get("MAX_RUNTIME_MINUTES", "345"))
    if not 30 <= minutes <= 345:
        raise ValueError("MAX_RUNTIME_MINUTES must be between 30 and 345")
    tag = env.get("SERVER_TAG", "github-linux")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,29}", tag):
        raise ValueError("Invalid SERVER_TAG")
    slot = env.get("WORKER_SLOT", "1")
    if slot not in {"1", "2", "3"}:
        raise ValueError("WORKER_SLOT must be 1, 2 or 3")
    label = "GitHub Linux " + env.get("GITHUB_REPOSITORY", "local")
    if slot != "1":
        label += " worker " + slot
    label += " #" + env.get("GITHUB_RUN_ID", "manual")
    return origin, env["JOIN_TOKEN"], minutes, tag, label


def download(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "runner-agent-bootstrap"})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Agent download exceeded its size limit")
    return body


def extract_binary(archive, digest):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid agent bundle digest")
    if hashlib.sha256(archive).hexdigest() != digest:
        raise ValueError("Agent bundle checksum did not match")
    allowed = {"Dockerfile", "bin/runner-agent-linux-amd64", "bin/runner-agent-linux-arm64"}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as bundle:
        members = bundle.getmembers()
        names = [item.name for item in members]
        if (set(names) != allowed or len(names) != len(allowed)
                or any(not item.isfile() for item in members)):
            raise ValueError("Unexpected files in agent bundle")
        return bundle.extractfile("bin/runner-agent-linux-amd64").read()


def agent_environment(origin, token, tag, label, lifetime, binary, data_dir, source_env):
    # Do not give workloads GitHub's job/session credentials.
    values = {key: source_env[key] for key in
              ("PATH", "HOME", "LANG", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR")
              if key in source_env}
    values.update({
        "CONTROL_URL": origin,
        "AGENT_URL": origin + "/agent",
        "JOIN_TOKEN": token,
        "SERVER_TAG": tag,
        "LABEL": label,
        "RUNNER_DATA": str(data_dir),
        "RUNNER_CODE_MANAGED": "1",
        "RUNNER_INSTALL_REVISION": hashlib.sha256(binary).hexdigest(),
        "LIFETIME_MIN": str(lifetime),
    })
    return values


def control_request(origin, path, token=None, payload=None):
    headers = {"User-Agent": "runner-agent-bootstrap"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = urllib.request.Request(origin + path, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def find_run(status, label):
    return next((run for run in status.get("runs", [])
                 if run.get("label") == label and run.get("live")), None)


def log(message):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), message, flush=True)


def stop_requested(signum, frame):
    global STOPPING
    STOPPING = True


def main():
    origin, token, minutes, tag, label = configuration(os.environ)
    if "--check" in sys.argv:
        log("Configuration is valid; the workflow permits one Linux runner")
        return 0
    if sys.platform != "linux":
        raise ValueError("This supervisor must run on the Linux workflow runner")
    started = float(os.environ.get("JOB_STARTED_AT", time.time()))
    deadline = started + minutes * 60
    process = None
    joined = None
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop_requested)
    try:
        subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True, timeout=60)
        subprocess.run(["docker", "compose", "version"], check=True, timeout=60)
        log("Downloading and verifying the control plane's current native agent")
        digest = download(origin + "/agent/rust/bundle.sha256", 256).decode().strip()
        binary = extract_binary(download(origin + "/agent/rust/bundle.tar", MAX_BUNDLE_BYTES), digest)
        if STOPPING:
            return 0
        data_dir = Path(os.environ["RUNNER_TEMP"]) / "runners-agent"
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        binary_path = data_dir / "native-agent"
        binary_path.write_bytes(binary)
        binary_path.chmod(0o700)
        lifetime = math.floor((deadline - time.time()) / 60)
        if lifetime < 15:
            raise RuntimeError("Insufficient job time left after startup")
        log("Starting the fleet agent with a " + str(lifetime) + " minute lifetime")
        process = subprocess.Popen([str(binary_path)], start_new_session=True,
            env=agent_environment(origin, token, tag, label, lifetime, binary, data_dir, os.environ))
        join_deadline = min(time.time() + 600, deadline)
        last_check = 0
        while not STOPPING and time.time() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Agent exited with code " + str(process.returncode))
            if not joined and time.time() - last_check >= 10:
                last_check = time.time()
                try:
                    joined = find_run(control_request(origin, "/api/status"), label)
                except Exception:
                    log("Waiting for the control plane to confirm this agent")
                if joined:
                    log("Agent connected on fleet machine " + str(joined["machine"]))
            if not joined and time.time() >= join_deadline:
                raise RuntimeError("Agent did not join the fleet within ten minutes")
            time.sleep(2)
        log("Ending this runner's lease; its waiting replacement can start next")
        return 0
    finally:
        if joined:
            try:
                control_request(origin, "/api/drain", token, {"run": joined["id"]})
                log("Requested a drain for this agent")
            except Exception:
                log("Drain request failed; the controller will detect the agent's departure")
        if process is not None:
            try:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            except ProcessLookupError:
                process.wait(timeout=10)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        # HTTP and subprocess exception strings can include unexpected data.
        log("Agent supervisor failed (" + type(error).__name__ + ")")
        sys.exit(1)
