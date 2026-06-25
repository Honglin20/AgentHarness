#!/usr/bin/env python
"""Training backend abstraction: LocalBackend + SSHBackend.

Adapters (projects/<X>/_nas_adapter.py) call this instead of `subprocess.run`
directly so training can run either locally (CPU/small GPU) or remotely
(AutoDL cloud GPU) without workflow changes.

Backend selection:
    TRAIN_BACKEND env var: "local" (default) | "ssh"

SSHBackend reads connection info from ~/.nas/cloud.yaml:
    ssh:
      host: connect.xxx.autodl.com
      port: 12345
      user: root
      password: "xxx"          # or ssh_key_path
      remote_project_dir: /root/autodl-tmp/AgentHarness
      remote_python: /root/miniconda3/envs/asi/bin/python

Protocol (each backend implements):
    run(train_cmd, worktree, env, timeout, log_path, metrics_path) -> BackendResult
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BackendResult:
    """Result returned by TrainBackend.run()."""
    ok: bool
    exit_code: int
    log_path: Path
    metrics_path: Path | None = None
    error: str = ""
    duration_sec: float = 0.0
    backend: str = "local"
    extra: dict[str, Any] = field(default_factory=dict)


class TrainBackend:
    """Base class. Subclasses implement run()."""

    name: str = "base"

    def run(self, *, train_cmd: list[str], worktree: Path,
            env: dict[str, str] | None = None, timeout: int = 1800,
            log_path: Path, metrics_path: Path | None = None) -> BackendResult:
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════════════
# LocalBackend — wraps existing subprocess.run logic
# ═══════════════════════════════════════════════════════════════════════

class LocalBackend(TrainBackend):
    name = "local"

    def run(self, *, train_cmd, worktree, env=None, timeout=1800,
            log_path, metrics_path=None) -> BackendResult:
        merged_env = os.environ.copy()
        if env:
            merged_env.update({str(k): str(v) for k, v in env.items()})

        log_path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            with open(log_path, "w") as f:
                proc = subprocess.run(
                    train_cmd, cwd=str(worktree), env=merged_env,
                    stdout=f, stderr=subprocess.STDOUT,
                    timeout=timeout,
                )
            return BackendResult(
                ok=proc.returncode == 0,
                exit_code=proc.returncode,
                log_path=log_path,
                metrics_path=metrics_path,
                duration_sec=time.time() - t0,
                backend=self.name,
            )
        except subprocess.TimeoutExpired:
            return BackendResult(
                ok=False, exit_code=124, log_path=log_path,
                metrics_path=metrics_path, duration_sec=time.time() - t0,
                error=f"timeout after {timeout}s", backend=self.name,
            )
        except Exception as e:
            return BackendResult(
                ok=False, exit_code=125, log_path=log_path,
                metrics_path=metrics_path, duration_sec=time.time() - t0,
                error=f"{type(e).__name__}: {e}", backend=self.name,
            )


# ═══════════════════════════════════════════════════════════════════════
# SSHBackend — rsync diff → ssh remote bash → scp log+metrics back
# ═══════════════════════════════════════════════════════════════════════

class SSHBackend(TrainBackend):
    name = "ssh"

    def __init__(self, config: dict | None = None):
        self.config = config or _load_ssh_config()
        self._sshpass = self._find_sshpass()

    def _find_sshpass(self) -> str | None:
        for p in ("/opt/homebrew/bin/sshpass", "/usr/local/bin/sshpass",
                  "/usr/bin/sshpass"):
            if Path(p).exists():
                return p
        # last resort: PATH lookup
        r = subprocess.run(["which", "sshpass"], capture_output=True, text=True)
        return r.stdout.strip() or None

    def _ssh_base(self) -> list[str]:
        """Base ssh command prefix (with auth)."""
        cfg = self.config
        host, port, user = cfg["host"], cfg["port"], cfg["user"]
        if cfg.get("password"):
            if not self._sshpass:
                raise RuntimeError(
                    "ssh password auth requires sshpass; "
                    "brew install hudochenkov/sshpass/sshpass"
                )
            return [
                self._sshpass, "-p", cfg["password"],
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-p", str(port), f"{user}@{host}",
            ]
        elif cfg.get("ssh_key_path"):
            return [
                "ssh", "-i", cfg["ssh_key_path"],
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-p", str(port), f"{user}@{host}",
            ]
        else:
            raise RuntimeError("SSH config needs password or ssh_key_path")

    def _rsync_env(self) -> dict[str, str]:
        """Env for rsync over ssh with same auth."""
        cfg = self.config
        env = os.environ.copy()
        if cfg.get("password") and self._sshpass:
            # rsync -e 'sshpass -p PASS ssh ...'
            env["RSYNC_SSH"] = shlex.join([
                self._sshpass, "-p", cfg["password"],
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
            ])
        return env

    def run(self, *, train_cmd, worktree, env=None, timeout=1800,
            log_path, metrics_path=None) -> BackendResult:
        """Execute train_cmd on remote, then fetch artifacts back.

        Convention (普适，所有 domain 适用):
        - If train_cmd has `--out_dir <path>`, the remote path is rewritten to
          `<remote_dir>/_out` and the whole `_out/` dir is fetched back to the
          LOCAL out_dir (so caller finds metrics.json/ckpt.pt where it expects).
        - If no `--out_dir`, fetch only `train.log` from remote_dir.
        - `metrics_path` (caller-specified local path) is honored IF train_cmd
          also writes to it relatively; otherwise we fallback to local out_dir.

        This avoids hard-coding per-project paths — any train.py that respects
        `--out_dir` works out of the box.
        """
        cfg = self.config
        # Resolve worktree.name — Path('.').name is empty, so use resolved path's
        # final component. This ensures each project gets its own remote subdir.
        worktree_resolved = worktree.resolve() if worktree.is_absolute() else (
            Path.cwd() / worktree).resolve()
        worktree_name = worktree.name or worktree_resolved.name or "worktree"
        remote_dir = Path(cfg["remote_project_dir"]) / worktree_name
        remote_python = cfg.get("remote_python", "python")

        log_path.parent.mkdir(parents=True, exist_ok=True)
        remote_log = remote_dir / "train.log"

        # ── Detect & rewrite --out_dir to remote ──
        local_out_dir = None
        remote_out_dir = remote_dir / "_out"
        rewritten_cmd = []
        i = 0
        while i < len(train_cmd):
            tok = train_cmd[i]
            if tok == "--out_dir" and i + 1 < len(train_cmd):
                local_out_dir = Path(train_cmd[i + 1])
                rewritten_cmd.extend([tok, str(remote_out_dir)])
                i += 2
                continue
            # Also handle --out_dir=PATH form
            if tok.startswith("--out_dir="):
                local_out_dir = Path(tok.split("=", 1)[1])
                rewritten_cmd.append(f"--out_dir={remote_out_dir}")
                i += 1
                continue
            rewritten_cmd.append(tok)
            i += 1
        train_cmd = rewritten_cmd

        # ── Replace any local absolute path with remote equivalent (普适) ──
        # Train scripts often get local paths like
        # /Users/x/projects/foo/train.py or /abs/path/to/configs/x.json.
        # Rewrite them to remote_dir/<relative> since we cd to remote_dir.
        # This handles common patterns: python <abs/train.py>, --config <abs/x.json>,
        # --data_dir <abs/data>, etc.
        worktree_abs = worktree_resolved
        rewritten_cmd = []
        for tok in train_cmd:
            # Replace "python" / sys.executable with remote_python
            if tok in ("python", sys.executable):
                rewritten_cmd.append(remote_python)
                continue
            # If token is a path under worktree, rewrite to relative (since we cd to remote_dir)
            try:
                tok_path = Path(tok)
                if tok_path.is_absolute():
                    try:
                        rel = tok_path.relative_to(worktree_abs)
                        rewritten_cmd.append(str(rel))
                        continue
                    except ValueError:
                        pass
            except Exception:
                pass
            rewritten_cmd.append(tok)
        train_cmd = rewritten_cmd

        # ── Step 1: rsync worktree → remote_dir ──
        rsync_cmd = [
            "rsync", "-az", "--delete",
            "--include=*.py", "--include=*.json", "--include=*.yaml",
            "--include=*.txt", "--include=*.toml", "--include=*.sh",
            "--include=*/",
            "--exclude=*",
            "-e", self._ssh_e(),
            f"{worktree}/",
            f"{cfg['user']}@{cfg['host']}:{remote_dir}/",
        ]
        rc = subprocess.run(rsync_cmd, capture_output=True, text=True,
                            timeout=120)
        if rc.returncode != 0:
            return BackendResult(
                ok=False, exit_code=126, log_path=log_path,
                error=f"rsync failed: {rc.stderr[-1000:]}", backend=self.name,
            )

        # ── Step 2: build remote command + env injection ──
        env_exports = ""
        if env:
            env_exports = " ".join(
                f"{shlex.quote(str(k))}={shlex.quote(str(v))}"
                for k, v in env.items()
            ) + " "

        # train_cmd already has --out_dir rewritten above + python replaced
        remote_cmd_str = shlex.join(train_cmd)
        remote_full = (
            f"mkdir -p {shlex.quote(str(remote_dir))} && "
            f"mkdir -p {shlex.quote(str(remote_out_dir))} && "
            f"cd {shlex.quote(str(remote_dir))} && "
            f"{env_exports}{remote_cmd_str} "
            f"> {shlex.quote(str(remote_log))} 2>&1 ; "
            f"echo EXIT_CODE=$?"
        )

        # ── Step 3: ssh run with retry ──
        t0 = time.time()
        last_err = ""
        exit_code = 125  # default if all retries fail
        for attempt in range(3):
            try:
                ssh_cmd = self._ssh_base() + [remote_full]
                proc = subprocess.run(
                    ssh_cmd, capture_output=True, text=True, timeout=timeout,
                )
                # Parse exit code from trailing "EXIT_CODE=N"
                exit_code = _parse_remote_exit(proc.stdout)
                if exit_code == 0:
                    break
                last_err = (
                    f"attempt {attempt+1} exit={exit_code}; "
                    f"stderr_tail={proc.stderr[-500:]}"
                )
            except subprocess.TimeoutExpired:
                last_err = f"attempt {attempt+1} timeout after {timeout}s"
            except Exception as e:
                last_err = f"attempt {attempt+1} {type(e).__name__}: {e}"

            if attempt < 2:
                time.sleep(2 ** attempt)  # 1s, 2s backoff

        if exit_code != 0:
            return BackendResult(
                ok=False, exit_code=exit_code, log_path=log_path,
                metrics_path=metrics_path,
                duration_sec=time.time() - t0,
                error=f"remote training failed after retries: {last_err}",
                backend=self.name,
            )

        # ── Step 4: scp log + entire out_dir back ──
        scp_cmd = self._scp_base() + [
            f"{cfg['user']}@{cfg['host']}:{remote_log}", str(log_path),
        ]
        subprocess.run(scp_cmd, capture_output=True, text=True, timeout=60)

        # Fetch whole remote_out_dir → local_out_dir (普适；metrics.json + ckpt.pt + ...)
        final_metrics_path = metrics_path
        if local_out_dir:
            local_out_dir.mkdir(parents=True, exist_ok=True)
            # rsync remote _out/ contents INTO local_out_dir (trailing slash =
            # "copy contents, not the dir itself", so files land directly)
            rsync_back = [
                "rsync", "-az",
                "-e", self._ssh_e(),
                f"{cfg['user']}@{cfg['host']}:{remote_out_dir}/",
                str(local_out_dir) + "/",
            ]
            subprocess.run(rsync_back, capture_output=True, text=True, timeout=120)
            # If metrics_path specified, point to fetched file
            fetched_metrics = local_out_dir / "metrics.json"
            if fetched_metrics.exists():
                final_metrics_path = fetched_metrics
                if metrics_path and Path(metrics_path).parent != local_out_dir:
                    # Copy to caller-specified path
                    import shutil
                    shutil.copy2(fetched_metrics, metrics_path)
                    final_metrics_path = metrics_path

        return BackendResult(
            ok=True, exit_code=0, log_path=log_path,
            metrics_path=final_metrics_path,
            duration_sec=time.time() - t0, backend=self.name,
            extra={"local_out_dir": str(local_out_dir) if local_out_dir else None,
                   "remote_out_dir": str(remote_out_dir)},
        )

    def _ssh_e(self) -> str:
        """rsync -e argument (ssh command rsync uses for transport)."""
        cfg = self.config
        port = str(cfg["port"])
        if cfg.get("password") and self._sshpass:
            return shlex.join([
                self._sshpass, "-p", cfg["password"],
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-p", port,
            ])
        return shlex.join([
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-p", port,
        ])

    def _scp_base(self) -> list[str]:
        cfg = self.config
        base = ["scp", "-P", str(cfg["port"]),
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null"]
        if cfg.get("password") and self._sshpass:
            return [self._sshpass, "-p", cfg["password"]] + base
        if cfg.get("ssh_key_path"):
            return base + ["-i", cfg["ssh_key_path"]]
        return base


# ═══════════════════════════════════════════════════════════════════════
# Config + factory
# ═══════════════════════════════════════════════════════════════════════

def _load_ssh_config() -> dict:
    """Load SSH config from ~/.nas/cloud.yaml `ssh` section.

    Also accepts env var overrides:
        SSH_HOST, SSH_PORT, SSH_USER, SSH_PASSWORD, SSH_KEY_PATH,
        REMOTE_PROJECT_DIR, REMOTE_PYTHON
    """
    cfg_path = Path.home() / ".nas" / "cloud.yaml"
    if not cfg_path.exists():
        raise RuntimeError(
            f"~/.nas/cloud.yaml not found. Create it with `ssh:` section, "
            f"or set SSH_HOST/SSH_PORT/SSH_USER/SSH_PASSWORD env vars."
        )
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(cfg_path.read_text()) or {}
        cfg = (data.get("ssh") or {})
    except Exception as e:
        raise RuntimeError(f"failed to parse {cfg_path}: {e}")

    # env override
    cfg["host"] = os.environ.get("SSH_HOST", cfg.get("host", ""))
    cfg["port"] = int(os.environ.get("SSH_PORT", cfg.get("port", 22)))
    cfg["user"] = os.environ.get("SSH_USER", cfg.get("user", "root"))
    cfg["password"] = os.environ.get("SSH_PASSWORD", cfg.get("password"))
    cfg["ssh_key_path"] = os.environ.get(
        "SSH_KEY_PATH", cfg.get("ssh_key_path"))
    cfg["remote_project_dir"] = os.environ.get(
        "REMOTE_PROJECT_DIR",
        cfg.get("remote_project_dir", "/root/autodl-tmp/AgentHarness"))
    cfg["remote_python"] = os.environ.get(
        "REMOTE_PYTHON",
        cfg.get("remote_python", "python"))

    if not cfg["host"]:
        raise RuntimeError(
            "no SSH host configured. Set ssh.host in ~/.nas/cloud.yaml "
            "or SSH_HOST env var"
        )
    return cfg


def get_backend(name: str | None = None) -> TrainBackend:
    """Factory. name=None reads TRAIN_BACKEND env (default 'local')."""
    if name is None:
        name = os.environ.get("TRAIN_BACKEND", "local")
    if name == "local":
        return LocalBackend()
    if name == "ssh":
        return SSHBackend()
    raise ValueError(f"unknown backend: {name!r} (expected 'local' or 'ssh')")


def _parse_remote_exit(stdout: str) -> int:
    """Extract trailing 'EXIT_CODE=N' from remote ssh output."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("EXIT_CODE="):
            try:
                return int(line.split("=", 1)[1])
            except ValueError:
                return 125
    return 125  # unknown — treat as failure


if __name__ == "__main__":
    # Smoke test: backend dispatch
    backend = get_backend()
    print(f"backend = {backend.name}")
