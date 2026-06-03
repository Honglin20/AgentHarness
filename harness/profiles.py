"""Multi-profile LLM configuration management.

Stores multiple API configurations in ``profiles.json`` at the project root.
Activating a profile writes its values into ``os.environ`` and ``.env``,
so downstream consumers (LLMClient) work unchanged.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from harness.config import configure, mask_key
from harness.paths import get_profiles_file


_MASK_RE = re.compile(r"^\*+$")
_MASKED_KEY_RE = re.compile(r"^.{0,4}\*{3,}.{0,4}$")


class ProfileManager:
    """CRUD + activation for LLM API profiles."""

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path else get_profiles_file()

    # ── internal I/O ────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self._path.exists():
            self._migrate_from_env()
        return json.loads(self._path.read_text())

    def _save(self, data: dict) -> None:
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def _migrate_from_env(self) -> None:
        """Create initial ``profiles.json`` from current env vars."""
        proxy = os.environ.get("HARNESS_PROXY", "")
        profile = {
            "name": "Default",
            "model": os.environ.get("HARNESS_MODEL", ""),
            "api_key": os.environ.get("HARNESS_API_KEY", ""),
            "api_url": os.environ.get("HARNESS_API_URL", ""),
            "proxy": proxy,
            "proxy_enabled": bool(proxy),
            "ssl_verify": os.environ.get("HARNESS_SSL_VERIFY", "true").lower() != "false",
        }
        self._save({"profiles": [profile], "active": "Default"})

    # ── public API ──────────────────────────────────────────────────

    def list_profiles(self) -> list[dict]:
        """Return all profiles with masked keys and ``is_active`` flag."""
        data = self._load()
        active = data.get("active", "")
        results: list[dict] = []
        for p in data["profiles"]:
            out = {**p}
            out["api_key_masked"] = mask_key(p.get("api_key", ""))
            del out["api_key"]
            out["proxy_masked"] = mask_key(p.get("proxy", ""))
            del out["proxy"]
            out["is_active"] = p["name"] == active
            results.append(out)
        return results

    def get_profile(self, name: str) -> dict | None:
        """Return a single profile with full (unmasked) key, or None."""
        data = self._load()
        for p in data["profiles"]:
            if p["name"] == name:
                return {**p}
        return None

    def save_profile(self, profile: dict) -> dict:
        """Create or update a profile. Returns the saved profile (masked key).

        If ``api_key`` is a mask pattern (all ``*``), the existing key is kept.
        """
        name = profile.get("name", "").strip()
        if not name:
            raise ValueError("Profile name is required")

        data = self._load()
        profiles = data["profiles"]

        incoming_key = profile.get("api_key", "")

        existing = next((p for p in profiles if p["name"] == name), None)
        if existing:
            # Preserve sensitive fields if incoming values are masked or empty
            if _MASKED_KEY_RE.match(incoming_key) or _MASK_RE.match(incoming_key) or not incoming_key:
                profile["api_key"] = existing.get("api_key", "")
            incoming_proxy = profile.get("proxy", "")
            if _MASKED_KEY_RE.match(incoming_proxy) or _MASK_RE.match(incoming_proxy) or not incoming_proxy:
                profile["proxy"] = existing.get("proxy", "")
            existing.update(profile)
            saved = existing
        else:
            # New profile — check for case-insensitive name collision
            conflict = next(
                (p for p in profiles if p["name"].lower() == name.lower()),
                None,
            )
            if conflict:
                raise ValueError(
                    f"Profile name conflicts with existing '{conflict['name']}'"
                )
            saved = {**profile}
            profiles.append(saved)

        self._save(data)

        out = {**saved}
        out["api_key_masked"] = mask_key(saved.get("api_key", ""))
        del out["api_key"]
        out["proxy_masked"] = mask_key(saved.get("proxy", ""))
        del out["proxy"]
        out["is_active"] = saved["name"] == data.get("active", "")
        return out

    def delete_profile(self, name: str) -> None:
        """Delete a profile. Raises ValueError if it is the active profile."""
        data = self._load()
        if data.get("active") == name:
            raise ValueError("Cannot delete the active profile")
        data["profiles"] = [p for p in data["profiles"] if p["name"] != name]
        self._save(data)

    def activate_profile(self, name: str) -> dict:
        """Activate a profile — writes its values to env vars and .env.

        Returns the current config dict after activation.
        """
        data = self._load()
        target = next((p for p in data["profiles"] if p["name"] == name), None)
        if not target:
            raise ValueError(f"Profile '{name}' not found")

        proxy_val = target.get("proxy", "") if target.get("proxy_enabled", False) else ""

        # Clear env vars that configure() skips on empty/falsy values
        for key in ("HARNESS_API_KEY", "HARNESS_MODEL", "HARNESS_API_URL"):
            os.environ.pop(key, None)

        configure(
            api_key=target.get("api_key", "") or None,
            model=target.get("model", "") or None,
            api_url=target.get("api_url", "") or None,
            proxy=proxy_val or None,
            ssl_verify="true" if target.get("ssl_verify", True) else "false",
        )

        data["active"] = name
        self._save(data)

        from harness.config import get_config
        return get_config()

    def rename_profile(self, old_name: str, new_name: str) -> dict:
        """Rename a profile. Updates the active reference if needed."""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("New name is required")

        data = self._load()
        profiles = data["profiles"]

        target = next((p for p in profiles if p["name"] == old_name), None)
        if not target:
            raise ValueError(f"Profile '{old_name}' not found")

        conflict = next(
            (p for p in profiles if p["name"].lower() == new_name.lower() and p is not target),
            None,
        )
        if conflict:
            raise ValueError(f"Name conflicts with existing '{conflict['name']}'")

        target["name"] = new_name

        if data.get("active") == old_name:
            data["active"] = new_name

        self._save(data)

        out = {**target}
        out["api_key_masked"] = mask_key(target.get("api_key", ""))
        del out["api_key"]
        out["proxy_masked"] = mask_key(target.get("proxy", ""))
        del out["proxy"]
        out["is_active"] = target["name"] == data.get("active", "")
        return out

    def get_active_name(self) -> str | None:
        data = self._load()
        return data.get("active") or None
