"""
keybank.py — a small local, encrypted secret store for API keys.

Why this exists
----------------
Config files like config.yaml get read constantly by editors, linters, and
AI coding assistants. Anything stored there in plain text is effectively
public to every tool that touches the repo. keybank keeps your actual key
values out of every file that gets read as "code" — they only ever exist
in decrypted form in the memory of a process you explicitly unlocked with
your master password.

Vault format (stored at .keybank/vault.json, gitignored):
    {
        "kdf_salt": "<base64>",
        "kdf_iterations": 600000,
        "check": "<fernet token of a known plaintext, proves the password>",
        "secrets": {"name": "<fernet token>", ...}
    }

Nothing in the vault file is readable without the master password. The
password itself is never written to disk; it is supplied at unlock time
via the KEYBANK_PASSWORD environment variable or an interactive, masked
getpass() prompt.

CLI usage (run this yourself, in your own terminal — see README.md for why):
    python keybank.py init
    python keybank.py set rapidapi_key
    python keybank.py list
    python keybank.py get rapidapi_key
    python keybank.py delete rapidapi_key
    python keybank.py rotate-password

Library usage (e.g. from scraper.py):
    from keybank import get_secret
    api_key = get_secret("rapidapi_key")
"""
import argparse
import base64
import getpass
import json
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

VAULT_DIR = Path(os.environ.get("KEYBANK_DIR", Path.home() / ".keybank"))
VAULT_PATH = VAULT_DIR / "vault.json"
KDF_ITERATIONS = 600_000
CHECK_PLAINTEXT = b"keybank-vault-ok"


class KeyBankError(Exception):
    pass


def _derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


class KeyBank:
    def __init__(self, path: Path = VAULT_PATH):
        self.path = path
        self._fernet = None

    # -- vault lifecycle -------------------------------------------------

    def exists(self) -> bool:
        return self.path.exists()

    def init(self, password: str):
        if self.exists():
            raise KeyBankError(f"Vault already exists at {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        salt = os.urandom(16)
        fernet = Fernet(_derive_key(password, salt, KDF_ITERATIONS))
        data = {
            "kdf_salt": base64.b64encode(salt).decode("ascii"),
            "kdf_iterations": KDF_ITERATIONS,
            "check": fernet.encrypt(CHECK_PLAINTEXT).decode("ascii"),
            "secrets": {},
        }
        self._write(data)
        self.path.chmod(0o600)

    def unlock(self, password: str):
        if not self.exists():
            raise KeyBankError(
                f"No vault found at {self.path}. Run 'python keybank.py init' first."
            )
        data = self._read()
        salt = base64.b64decode(data["kdf_salt"])
        fernet = Fernet(_derive_key(password, salt, data["kdf_iterations"]))
        try:
            if fernet.decrypt(data["check"].encode("ascii")) != CHECK_PLAINTEXT:
                raise InvalidToken()
        except InvalidToken:
            raise KeyBankError("Incorrect master password.")
        self._fernet = fernet
        self._data = data

    def _require_unlocked(self):
        if self._fernet is None:
            raise KeyBankError("Vault is locked. Call unlock() first.")

    # -- secret operations -------------------------------------------------

    def set(self, name: str, value: str):
        self._require_unlocked()
        token = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        self._data["secrets"][name] = token
        self._write(self._data)

    def get(self, name: str) -> str:
        self._require_unlocked()
        token = self._data["secrets"].get(name)
        if token is None:
            raise KeyBankError(f"No secret named '{name}' in the vault.")
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")

    def delete(self, name: str):
        self._require_unlocked()
        if name not in self._data["secrets"]:
            raise KeyBankError(f"No secret named '{name}' in the vault.")
        del self._data["secrets"][name]
        self._write(self._data)

    def list_names(self):
        self._require_unlocked()
        return sorted(self._data["secrets"].keys())

    def rotate_password(self, new_password: str):
        self._require_unlocked()
        salt = os.urandom(16)
        new_fernet = Fernet(_derive_key(new_password, salt, KDF_ITERATIONS))
        plaintext_secrets = {
            name: self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
            for name, token in self._data["secrets"].items()
        }
        new_data = {
            "kdf_salt": base64.b64encode(salt).decode("ascii"),
            "kdf_iterations": KDF_ITERATIONS,
            "check": new_fernet.encrypt(CHECK_PLAINTEXT).decode("ascii"),
            "secrets": {
                name: new_fernet.encrypt(value.encode("utf-8")).decode("ascii")
                for name, value in plaintext_secrets.items()
            },
        }
        self._write(new_data)
        self._fernet = new_fernet
        self._data = new_data

    # -- disk io -------------------------------------------------

    def _read(self) -> dict:
        with open(self.path) as f:
            return json.load(f)

    def _write(self, data: dict):
        tmp_path = self.path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        tmp_path.replace(self.path)
        self.path.chmod(0o600)


# -- convenience helpers for scripts (scraper.py, dashboard.py, ...) -------


def _resolve_password(prompt_if_missing: bool = True) -> str:
    password = os.environ.get("KEYBANK_PASSWORD")
    if password:
        return password
    if not prompt_if_missing or not sys.stdin.isatty():
        raise KeyBankError(
            "KEYBANK_PASSWORD is not set and no interactive terminal is "
            "available to prompt for it."
        )
    return getpass.getpass("keybank master password: ")


def get_secret(name: str, default: str = None) -> str:
    """Unlock the vault (prompting/using KEYBANK_PASSWORD) and return a secret.

    Falls back to `default` only if the vault or the named secret doesn't
    exist, so existing config.yaml-style fallbacks keep working during
    migration.
    """
    kb = KeyBank()
    if not kb.exists():
        if default is not None:
            return default
        raise KeyBankError(
            f"No keybank vault found and no fallback given for '{name}'. "
            f"Run 'python keybank.py init' then 'python keybank.py set {name}'."
        )
    kb.unlock(_resolve_password())
    try:
        return kb.get(name)
    except KeyBankError:
        if default is not None:
            return default
        raise


# -- CLI -------------------------------------------------


def _cmd_init(args):
    kb = KeyBank()
    password = getpass.getpass("Set a new master password: ")
    confirm = getpass.getpass("Confirm master password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        sys.exit(1)
    kb.init(password)
    print(f"Vault created at {kb.path}")


def _cmd_set(args):
    kb = KeyBank()
    kb.unlock(_resolve_password())
    if args.stdin:
        value = sys.stdin.readline().rstrip("\n")
    else:
        value = getpass.getpass(f"Value for '{args.name}': ")
    kb.set(args.name, value)
    print(f"Stored '{args.name}'.")


def _cmd_get(args):
    kb = KeyBank()
    kb.unlock(_resolve_password())
    print(kb.get(args.name))


def _cmd_list(args):
    kb = KeyBank()
    kb.unlock(_resolve_password())
    names = kb.list_names()
    if not names:
        print("(vault is empty)")
    for name in names:
        print(name)


def _cmd_delete(args):
    kb = KeyBank()
    kb.unlock(_resolve_password())
    kb.delete(args.name)
    print(f"Deleted '{args.name}'.")


def _cmd_rotate_password(args):
    kb = KeyBank()
    kb.unlock(_resolve_password())
    new_password = getpass.getpass("New master password: ")
    confirm = getpass.getpass("Confirm new master password: ")
    if new_password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        sys.exit(1)
    kb.rotate_password(new_password)
    print("Password rotated.")


def main():
    parser = argparse.ArgumentParser(description="Local encrypted API key bank.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create a new vault.")

    p_set = sub.add_parser("set", help="Store a secret (prompts, hidden input).")
    p_set.add_argument("name")
    p_set.add_argument(
        "--stdin", action="store_true",
        help="Read the value from stdin instead of an interactive prompt.",
    )
    p_set.set_defaults(func=_cmd_set)

    p_get = sub.add_parser("get", help="Print a decrypted secret to stdout.")
    p_get.add_argument("name")
    p_get.set_defaults(func=_cmd_get)

    p_list = sub.add_parser("list", help="List stored secret names (not values).")
    p_list.set_defaults(func=_cmd_list)

    p_delete = sub.add_parser("delete", help="Remove a secret from the vault.")
    p_delete.add_argument("name")
    p_delete.set_defaults(func=_cmd_delete)

    p_init = sub.choices["init"]
    p_init.set_defaults(func=_cmd_init)

    p_rotate = sub.add_parser("rotate-password", help="Re-encrypt the vault under a new password.")
    p_rotate.set_defaults(func=_cmd_rotate_password)

    args = parser.parse_args()
    try:
        args.func(args)
    except KeyBankError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
