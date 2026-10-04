"""Routes of this fork, called by server.py (see CONTRACT.md, section 5). Each function answers and returns True,
or returns False and the server goes on to its own routes."""
from __future__ import annotations


def get(h, path: str, q: dict, snap: dict) -> bool:
    return False


def write(h, method: str, path: str, body) -> bool:
    return False
