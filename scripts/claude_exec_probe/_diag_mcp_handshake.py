"""Diagnostic: 直接 ping echo server 验证 JSON-RPC 协议层。"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SERVER = Path(__file__).parent / "mcp_echo_server.py"


def send(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def recv(proc, timeout=5):
    # 简单 readline，超时由 subprocess 控制（这里用阻塞读）
    line = proc.stdout.readline()
    return line.strip() if line else ""


def main():
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    try:
        # initialize
        send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "diag", "version": "1.0"},
                "capabilities": {},
            }
        })
        print("initialize resp:", recv(proc))

        # notifications/initialized
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.3)

        # tools/list
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        print("tools/list resp:", recv(proc))

        # tools/call
        send(proc, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "diag-ping", "block_seconds": 0}}
        })
        print("tools/call resp:", recv(proc))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        # 打印 server stderr 看有无错误
        err = proc.stderr.read()
        if err:
            print("--- server stderr ---")
            print(err)


if __name__ == "__main__":
    main()
