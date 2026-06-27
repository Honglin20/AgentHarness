#!/usr/bin/env python
"""parse_train_log.py — extract metrics from training log via declared regex rules.

Input:
  --log <path>          training log file (stdout/stderr capture from train.py)
  --rules <path>        log_parse_rules.json (written by metric_align agent)
  --out <path>          output metrics JSON path

Output (stdout JSON):
  {"metrics": {name: value, ...}, "missing": [name, ...]}

Rules format (log_parse_rules.json):
  {
    "rules": [
      {"name": "acc", "regex": "acc=([0-9.]+)", "type": "float", "direction": "higher"},
      {"name": "loss", "regex": "loss=([0-9.]+)", "type": "float", "direction": "lower"}
    ]
  }

Behavior:
  - For each rule, find ALL matches in log, take the LAST one (final value).
    Training logs often print metrics per epoch; the final value is what we want.
  - Type conversion: float / int / str (default float).
  - If no match: add name to "missing" list, omit from metrics.
  - Multi-group regex: take group(1) only.

This is the single source of truth for metric extraction — metric_align,
trainer/optimizer eval, judger/collector fitness all call this helper.
Once rules are written in SETUP, the entire cycle reuses them verbatim.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def parse_log(log_text: str, rules: list[dict]) -> tuple[dict[str, Any], list[str]]:
    """Pure function — extract metrics from log text using declared rules.

    Args:
        log_text: Full training log content.
        rules: List of rule dicts, each with keys: name, regex, type, direction.

    Returns:
        (metrics_dict, missing_list)
        metrics_dict: {name: converted_value} for matched rules.
        missing_list: [name] for rules with no match.
    """
    metrics: dict[str, Any] = {}
    missing: list[str] = []

    for rule in rules:
        name = rule.get("name", "")
        pattern = rule.get("regex", "")
        value_type = rule.get("type", "float")

        if not name or not pattern:
            missing.append(name or "<unnamed>")
            continue

        try:
            matches = re.findall(pattern, log_text)
        except re.error as e:
            print(
                f"[parse_train_log] invalid regex for {name!r}: {e}",
                file=sys.stderr,
            )
            missing.append(name)
            continue

        if not matches:
            missing.append(name)
            continue

        # Take last match (final value across epochs).
        last = matches[-1]
        # Multi-group regex → list/tuple; we want group(1) equivalent.
        if isinstance(last, (list, tuple)):
            last = last[0] if last else ""

        try:
            if value_type == "int":
                metrics[name] = int(float(last))
            elif value_type == "str":
                metrics[name] = str(last).strip()
            else:  # float (default)
                metrics[name] = float(last)
        except (ValueError, TypeError) as e:
            print(
                f"[parse_train_log] failed to convert {name}={last!r} to {value_type}: {e}",
                file=sys.stderr,
            )
            missing.append(name)

    return metrics, missing


def main() -> None:
    p = argparse.ArgumentParser(description="Extract metrics from training log")
    p.add_argument("--log", required=True, help="Training log file path")
    p.add_argument("--rules", required=True, help="log_parse_rules.json path")
    p.add_argument("--out", required=True, help="Output JSON path")
    args = p.parse_args()

    log_path = Path(args.log)
    rules_path = Path(args.rules)

    if not log_path.exists():
        print(json.dumps({"error": f"log not found: {log_path}"}))
        sys.exit(1)
    if not rules_path.exists():
        print(json.dumps({"error": f"rules not found: {rules_path}"}))
        sys.exit(1)

    log_text = log_path.read_text(errors="replace")
    rules_blob = json.loads(rules_path.read_text())

    # Accept either {"rules": [...]} or bare [...].
    if isinstance(rules_blob, dict):
        rules = rules_blob.get("rules", [])
    elif isinstance(rules_blob, list):
        rules = rules_blob
    else:
        print(json.dumps({"error": "rules file must be list or {rules: [...]}"}))
        sys.exit(1)

    metrics, missing = parse_log(log_text, rules)
    result = {"metrics": metrics, "missing": missing}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
