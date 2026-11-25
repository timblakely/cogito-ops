#!/usr/bin/env python3
"""Repository-scoped Git HTTPS credential helper for Cogito OpenCode.

Reads the projected GitHub token fresh on every ``get`` request and emits
it only for the single authorized repository over https://github.com.
"""
import sys

TOKEN_PATH = "/var/run/secrets/github/token"
PROTOCOL = "https"
HOST = "github.com"
REPO_PATHS = frozenset({"timblakely/cogito-ops", "timblakely/cogito-ops.git"})
USERNAME = "x-access-token"
SECURITY_KEYS = frozenset({"protocol", "host", "path", "username"})
ERROR = "github-credential-helper: credential unavailable\n"


def parse_attrs(stdin):
    """Parse key=value lines (git sends these to helpers), blank-line ended."""
    attrs = {}
    for raw in stdin:
        line = raw.rstrip("\n").rstrip("\r")
        if not line:
            break
        key, sep, value = line.partition("=")
        if not sep or not key:
            return None
        if key in SECURITY_KEYS and key in attrs:
            return None
        attrs[key] = value
    return attrs


def parse_request(stdin):
    """Parse the in-band form used by tests: action line first, then attrs."""
    first = next(stdin, None)
    if first is None:
        return None
    action = first.rstrip("\n").rstrip("\r")
    if not action or "=" in action:
        return None
    attrs = parse_attrs(stdin)
    if attrs is None:
        return None
    return action, attrs


def in_scope(attrs):
    return (attrs.get("protocol") == PROTOCOL
            and attrs.get("host") == HOST
            and attrs.get("path") in REPO_PATHS
            and attrs.get("username", "") in ("", USERNAME))


def read_token(token_path):
    """Return the token, or None unless the file holds exactly one clean line."""
    try:
        with open(token_path, "rb") as handle:
            raw = handle.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if raw.endswith("\n"):
        raw = raw[:-1]
    if not raw or any(ord(char) <= 0x20 or ord(char) >= 0x7F for char in raw):
        return None
    return raw


def run(stdin, stdout, stderr, token_path=TOKEN_PATH, action=None):
    if action is None:
        parsed = parse_request(stdin)
        if parsed is None:
            return 1
        action, attrs = parsed
    else:
        attrs = parse_attrs(stdin)
        if attrs is None:
            return 1
    if action in ("store", "erase"):
        return 0
    if action != "get" or not in_scope(attrs):
        return 1
    token = read_token(token_path)
    if token is None:
        stdout.write("quit=true\n\n")
        stderr.write(ERROR)
        return 1
    stdout.write(f"username={USERNAME}\npassword={token}\n\n")
    return 0


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(run(sys.stdin, sys.stdout, sys.stderr, action=action))


if __name__ == "__main__":
    main()
