"""Split changes into token-bounded chunks for later AI analysis (used from Phase 3).

Public interface: ``estimate_tokens``, ``Chunk``, ``split_for_analysis``, ``chunk_hunks``.
Rule-based detectors always see every change; ignore globs only affect AI analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

from verifypr.analysis.globs import any_match
from verifypr.models import Hunk


def estimate_tokens(text: str) -> int:
    """Rough, provider-independent estimate (~4 characters per token)."""
    return len(text) // 4 + 1


def _hunk_tokens(hunk: Hunk) -> int:
    return estimate_tokens("\n".join((*hunk.removed, *hunk.added))) + estimate_tokens(
        hunk.file_path
    )


@dataclass(frozen=True)
class Chunk:
    hunks: tuple[Hunk, ...]
    tokens: int
    oversize: bool = False


def split_for_analysis(
    hunks: list[Hunk] | tuple[Hunk, ...], ignore_globs: tuple[str, ...]
) -> tuple[list[Hunk], list[str]]:
    """Return (hunks to analyze, sorted unique paths skipped by ignore globs)."""
    kept: list[Hunk] = []
    skipped: set[str] = set()
    for hunk in hunks:
        if any_match(ignore_globs, hunk.file_path):
            skipped.add(hunk.file_path)
        else:
            kept.append(hunk)
    return kept, sorted(skipped)


def chunk_hunks(hunks: list[Hunk] | tuple[Hunk, ...], max_tokens: int) -> list[Chunk]:
    """Pack hunks in order into chunks of at most ``max_tokens``.

    A single hunk larger than the budget gets its own chunk marked ``oversize`` so the
    caller can report it as skipped or summarize it, instead of failing.
    """
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    chunks: list[Chunk] = []
    current: list[Hunk] = []
    used = 0
    for hunk in hunks:
        size = _hunk_tokens(hunk)
        if size > max_tokens:
            if current:
                chunks.append(Chunk(tuple(current), used))
                current, used = [], 0
            chunks.append(Chunk((hunk,), size, oversize=True))
            continue
        if used + size > max_tokens and current:
            chunks.append(Chunk(tuple(current), used))
            current, used = [], 0
        current.append(hunk)
        used += size
    if current:
        chunks.append(Chunk(tuple(current), used))
    return chunks
