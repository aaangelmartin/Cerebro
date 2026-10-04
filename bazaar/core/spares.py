"""Which copies of a card may leave our hand.

control.protected holds card refs ("MAL-06": every copy stays) and asset ids ("147": that copy stays). A spare
shown to the brain, or offered in a team thread, must be a copy the rails will let go: never the protected one.
"""
from __future__ import annotations


def protected_set(control: dict | None) -> set[str]:
    return {str(x) for x in (control or {}).get("protected") or []}


def free_copies(copies: list[dict], protected: set[str] | list | None, ref: str | None = None,
                keep: int = 1) -> list[dict]:
    """The copies of one card that may go: none when the ref is protected by name, never a copy protected by id,
    and `keep` copies always stay (the protected ones count as the ones that stay)."""
    prot = {str(x) for x in protected or []}
    copies = [a for a in copies or [] if isinstance(a, dict)]
    if not copies:
        return []
    ref = ref if ref is not None else copies[0].get("ref")
    if ref is not None and str(ref) in prot:
        return []
    free = [a for a in copies if str(a.get("id")) not in prot]
    stays = len(copies) - len(free)                      # protected copies already stay
    spare = len(free) - max(0, keep - stays)
    return free[len(free) - spare:] if spare > 0 else []
