#!/usr/bin/env python
"""AutoDL 容器实例 Pro API wrapper.

Thin client over https://api.autodl.com/api/v1/dev/instance/pro/* endpoints.
Token-based auth (Authorization header). Used by train_backend.SSHBackend to
provision / power-on / get SSH credentials / release instances on demand.

Token source (priority):
    1. env var AUTODL_TOKEN
    2. ~/.nas/cloud.yaml under `autodl.token`

This module NEVER raises on HTTP errors — it returns the raw response dict
so callers can branch on `code` field. Network errors raise loud.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import urllib.error
import urllib.request

API_BASE = "https://api.autodl.com"
DEFAULT_TIMEOUT = 30

# 附录 GPU 算力规格 ID（来自 AutoDL 文档）
GPU_SPECS = {
    "3090-48G": "v-48g-350w",   # 最便宜，~¥1.5/h
    "4090-48G": "v-48g",          # ~¥2.5/h
    "PRO6000-96G": "pro6000-p",   # 性能型
    "4080-32G": "v-32g-p",
    "5090-32G": "5090-p",
    "H800-80G": "h800",
}

# 公共基础镜像 UUID
IMAGES = {
    "pytorch-cuda118-torch2.0": "base-image-l2t43iu6uk",
    "miniconda-cuda116": "base-image-mbr2n4urrc",
    "pytorch-cuda113-torch1.11": "base-image-l374uiucui",
}


class AutoDLError(RuntimeError):
    """Raised on network / protocol errors (NOT on API `code != Success`)."""


def _load_token() -> str:
    if token := os.environ.get("AUTODL_TOKEN"):
        return token
    cfg = Path.home() / ".nas" / "cloud.yaml"
    if cfg.exists():
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(cfg.read_text()) or {}
            token = (data.get("autodl") or {}).get("token")
            if token:
                return token
        except Exception as e:
            raise AutoDLError(f"failed to parse {cfg}: {e}")
    raise AutoDLError(
        "no AutoDL token found. Set AUTODL_TOKEN env var or "
        "add `autodl.token` to ~/.nas/cloud.yaml"
    )


def _call(method: str, path: str, body: dict[str, Any] | None = None) -> dict:
    """Call AutoDL API; return parsed JSON dict. Raise on network/protocol error.

    For GET: encode body as URL query string (AutoDL convention — GET endpoints
    refuse bodies but accept query params).
    For POST: encode body as JSON.

    Caller checks `resp["code"] == "Success"`.
    """
    token = _load_token()
    data = json.dumps(body or {}).encode()
    if method.upper() == "GET":
        # Encode body as query string for GET endpoints
        if body:
            from urllib.parse import urlencode
            url = f"{API_BASE}{path}?{urlencode(body)}"
        else:
            url = f"{API_BASE}{path}"
        req = urllib.request.Request(
            url, method="GET",
            headers={"Authorization": token},
        )
    else:
        url = f"{API_BASE}{path}"
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={
                "Authorization": token,
                "Content-Type": "application/json",
            },
        )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            payload = resp.read().decode()
            return json.loads(payload)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        raise AutoDLError(f"HTTP {e.code} on {path}: {body_text}")
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        raise AutoDLError(f"network/parse error on {path}: {e}")


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def create_instance(
    *,
    gpu_spec: str = "3090-48G",
    image: str = "pytorch-cuda118-torch2.0",
    cuda_v: int = 118,
    gpu_count: int = 1,
    name: str = "nas-asi",
    start_command: str = "sleep 1",
    data_centers: list[str] | None = None,
) -> dict:
    """Create a pay-as-you-go instance. Returns API response dict.

    On Success: resp["data"] is the instance UUID (e.g. "pro-xxx").
    On failure: resp["code"] is the error code (e.g. TORealName).
    """
    body: dict[str, Any] = {
        "req_gpu_amount": gpu_count,
        "expand_system_disk_by_gb": 0,
        "gpu_spec_uuid": GPU_SPECS.get(gpu_spec, gpu_spec),
        "image_uuid": IMAGES.get(image, image),
        "cuda_v_from": cuda_v,
        "instance_name": name,
        "start_command": start_command,
    }
    if data_centers:
        body["data_center_list"] = data_centers
    return _call("POST", "/api/v1/dev/instance/pro/create", body)


def power_on(instance_uuid: str, start_command: str | None = None) -> dict:
    body: dict[str, Any] = {"instance_uuid": instance_uuid, "payload": "gpu"}
    if start_command:
        body["start_command"] = start_command
    return _call("POST", "/api/v1/dev/instance/pro/power_on", body)


def power_off(instance_uuid: str) -> dict:
    return _call("POST", "/api/v1/dev/instance/pro/power_off",
                 {"instance_uuid": instance_uuid})


def release(instance_uuid: str) -> dict:
    """Release (destroy) instance. Must power_off first."""
    return _call("POST", "/api/v1/dev/instance/pro/release",
                 {"instance_uuid": instance_uuid})


def status(instance_uuid: str) -> dict:
    """Returns {code, data: "running" | "starting" | "stopped" | ...}"""
    return _call("GET", "/api/v1/dev/instance/pro/status",
                 {"instance_uuid": instance_uuid})


def snapshot(instance_uuid: str) -> dict:
    """Get full instance details incl ssh_command, root_password, ssh_port."""
    return _call("GET", "/api/v1/dev/instance/pro/snapshot",
                 {"instance_uuid": instance_uuid})


def list_instances(page_size: int = 50) -> dict:
    return _call("POST", "/api/v1/dev/instance/pro/list",
                 {"page_index": 1, "page_size": page_size})


def wait_running(instance_uuid: str, timeout_sec: int = 300,
                 poll_interval: int = 10) -> dict:
    """Poll status until running; return snapshot. Raise AutoDLError on timeout."""
    deadline = time.time() + timeout_sec
    last_status = None
    while time.time() < deadline:
        st = status(instance_uuid)
        if st.get("code") != "Success":
            raise AutoDLError(f"status check failed: {st}")
        last_status = st.get("data")
        if last_status == "running":
            snap = snapshot(instance_uuid)
            if snap.get("code") == "Success":
                return snap.get("data") or {}
            raise AutoDLError(f"snapshot failed after running: {snap}")
        time.sleep(poll_interval)
    raise AutoDLError(
        f"timeout after {timeout_sec}s waiting for running (last: {last_status})"
    )


def get_ssh_credentials(instance_uuid: str, wait_sec: int = 300) -> dict:
    """Wait for running + extract ssh_command / root_password / ssh_port.

    Returns:
        {host, port, user, password, ssh_command}
    """
    data = wait_running(instance_uuid, timeout_sec=wait_sec)
    ssh_cmd = data.get("ssh_command") or ""
    # ssh -p PORT root@HOST
    parts = ssh_cmd.split()
    port = None
    host = None
    if len(parts) >= 4 and parts[0] == "ssh":
        for i, tok in enumerate(parts):
            if tok == "-p" and i + 1 < len(parts):
                port = int(parts[i + 1])
            if tok.startswith("root@"):
                host = tok.split("@", 1)[1]
    return {
        "host": host or "",
        "port": port or 0,
        "user": "root",
        "password": data.get("root_password") or "",
        "ssh_command": ssh_cmd,
        "instance_uuid": instance_uuid,
    }


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="AutoDL instance manager")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=lambda a: list_instances())
    c = sub.add_parser("create")
    c.add_argument("--gpu", default="3090-48G")
    c.add_argument("--image", default="pytorch-cuda118-torch2.0")
    c.add_argument("--name", default="nas-asi")
    s = sub.add_parser("status"); s.add_argument("uuid")
    on = sub.add_parser("power_on"); on.add_argument("uuid")
    off = sub.add_parser("power_off"); off.add_argument("uuid")
    rel = sub.add_parser("release"); rel.add_argument("uuid")
    snap = sub.add_parser("snapshot"); snap.add_argument("uuid")
    cred = sub.add_parser("credentials"); cred.add_argument("uuid")
    args = p.parse_args()

    if args.cmd == "create":
        r = create_instance(gpu_spec=args.gpu, image=args.image, name=args.name)
    elif args.cmd == "list":
        r = list_instances()
    elif args.cmd == "status":
        r = status(args.uuid)
    elif args.cmd == "power_on":
        r = power_on(args.uuid)
    elif args.cmd == "power_off":
        r = power_off(args.uuid)
    elif args.cmd == "release":
        r = release(args.uuid)
    elif args.cmd == "snapshot":
        r = snapshot(args.uuid)
    elif args.cmd == "credentials":
        r = get_ssh_credentials(args.uuid)
    else:
        p.print_help(); return

    print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
