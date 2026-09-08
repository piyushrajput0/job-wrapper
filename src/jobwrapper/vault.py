"""Encrypted credential vault.

Credentials for career-site accounts are the user's own. They are stored AES-256-GCM encrypted
under a scrypt-derived key, never in the SQLite database, never in the config, and never logged.

Passphrase resolution order:
  1. $JOBWRAPPER_VAULT_PASSPHRASE
  2. macOS Keychain item "jobwrapper-vault" (created on first use with `--keychain`)
  3. interactive prompt
"""

from __future__ import annotations

import json
import os
import secrets
import string
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import paths

KEYCHAIN_SERVICE = "jobwrapper-vault"
MAGIC = b"JWV1"


@dataclass
class Credential:
    domain: str
    username: str
    password: str
    notes: str = ""
    created_at: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"domain": self.domain, "username": self.username, "password": self.password,
                "notes": self.notes, "created_at": self.created_at, "extra": self.extra}


def generate_password(length: int = 20, *, require_symbol: bool = True) -> str:
    """A fresh password per site. Never derived from anything the user already uses."""
    alphabet = string.ascii_letters + string.digits
    symbols = "!@#$%^&*-_=+"
    while True:
        pool = alphabet + (symbols if require_symbol else "")
        pw = "".join(secrets.choice(pool) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)
                and (not require_symbol or any(c in symbols for c in pw))):
            return pw


def _keychain_get() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def _keychain_set(passphrase: str) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(
            ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
             "-a", os.environ.get("USER", "jobwrapper"), "-w", passphrase],
            capture_output=True, text=True, timeout=10, check=True)
        return True
    except Exception:
        return False


class Vault:
    def __init__(self, path: Path | None = None, passphrase: str | None = None,
                 interactive: bool = True) -> None:
        self.path = path or paths.ensure_layout()["vault"]
        self._passphrase = passphrase
        self._data: dict[str, dict[str, Any]] | None = None
        # the web server and the apply loop must never block on a terminal prompt
        self.interactive = interactive

    # ------------------------------------------------------------------ crypto
    def _resolve_passphrase(self, *, confirm_new: bool = False) -> str:
        if self._passphrase:
            return self._passphrase
        env = os.environ.get("JOBWRAPPER_VAULT_PASSPHRASE")
        if env:
            self._passphrase = env
            return env
        kc = _keychain_get()
        if kc:
            self._passphrase = kc
            return kc
        if not self.interactive:
            return self._auto_passphrase()

        import getpass

        prompt = "Create a vault passphrase: " if confirm_new else "Vault passphrase: "
        pw = getpass.getpass(prompt)
        if confirm_new:
            again = getpass.getpass("Confirm passphrase: ")
            if pw != again:
                raise ValueError("passphrases did not match")
            _keychain_set(pw)
        self._passphrase = pw
        return pw

    def _auto_passphrase(self) -> str:
        """Machine-generated passphrase, kept in the macOS keychain (or a 0600 file elsewhere).

        This is what lets the UI store an API key without ever prompting. It is still better
        than plaintext: the secret file is encrypted, and on macOS the key lives in the keychain.
        """
        keyfile = self.path.parent / ".vaultkey"
        existing = _keychain_get() or (keyfile.read_text().strip() if keyfile.exists() else "")
        if existing:
            self._passphrase = existing
            return existing
        generated = secrets.token_urlsafe(32)
        if not _keychain_set(generated):
            keyfile.parent.mkdir(parents=True, exist_ok=True)
            keyfile.write_text(generated)
            os.chmod(keyfile, 0o600)
        self._passphrase = generated
        return generated

    # ------------------------------------------------------------------ api keys
    def set_api_key(self, provider: str, key: str) -> None:
        self.put(Credential(domain=f"apikey:{provider}", username=provider, password=key,
                            notes="API key stored by jobwrapper"))

    def get_api_key(self, provider: str) -> str:
        data = self._load()
        entry = data.get(f"apikey:{provider}")
        return entry["password"] if entry else ""

    def clear_api_key(self, provider: str) -> bool:
        return self.delete(f"apikey:{provider}")

    @staticmethod
    def _derive(passphrase: str, salt: bytes) -> bytes:
        kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
        return kdf.derive(passphrase.encode())

    def _encrypt(self, payload: dict[str, Any]) -> bytes:
        passphrase = self._resolve_passphrase(confirm_new=not self.path.exists())
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        key = self._derive(passphrase, salt)
        blob = AESGCM(key).encrypt(nonce, json.dumps(payload).encode(), MAGIC)
        return MAGIC + salt + nonce + blob

    def _decrypt(self, raw: bytes) -> dict[str, Any]:
        if not raw.startswith(MAGIC):
            raise ValueError("vault file is corrupt or not a jobwrapper vault")
        salt, nonce, blob = raw[4:20], raw[20:32], raw[32:]
        key = self._derive(self._resolve_passphrase(), salt)
        return json.loads(AESGCM(key).decrypt(nonce, blob, MAGIC).decode())

    # ------------------------------------------------------------------ api
    def _load(self) -> dict[str, dict[str, Any]]:
        if self._data is not None:
            return self._data
        if not self.path.exists():
            self._data = {}
            return self._data
        self._data = self._decrypt(self.path.read_bytes())
        return self._data

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._encrypt(self._data or {}))
        tmp.replace(self.path)
        os.chmod(self.path, 0o600)

    def exists(self) -> bool:
        return self.path.exists()

    def put(self, cred: Credential) -> None:
        from datetime import datetime

        data = self._load()
        cred.created_at = cred.created_at or datetime.now(UTC).isoformat()
        data[cred.domain.lower()] = cred.to_dict()
        self._flush()

    def get(self, domain: str) -> Credential | None:
        data = self._load()
        key = domain.lower()
        entry = data.get(key)
        if not entry:
            # subdomain match on a dot boundary, so careers.acme.com finds acme.com
            # (but evil-acme.com never matches acme.com)
            for stored, value in data.items():
                if key.endswith(f".{stored}") or stored.endswith(f".{key}"):
                    entry = value
                    break
        return Credential(**entry) if entry else None

    def get_or_create(self, domain: str, username: str) -> tuple[Credential, bool]:
        """Returns (credential, created). Used by the sign-in-else-sign-up flow."""
        existing = self.get(domain)
        if existing:
            return existing, False
        cred = Credential(domain=domain.lower(), username=username,
                          password=generate_password(), notes="auto-generated by jobwrapper")
        self.put(cred)
        return cred, True

    def domains(self) -> list[str]:
        return sorted(self._load().keys())

    def delete(self, domain: str) -> bool:
        data = self._load()
        if domain.lower() in data:
            del data[domain.lower()]
            self._flush()
            return True
        return False
