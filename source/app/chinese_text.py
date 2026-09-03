from __future__ import annotations

from functools import lru_cache

from opencc import OpenCC


_TO_SIMPLIFIED = OpenCC("t2s")
_TO_TRADITIONAL = OpenCC("s2t")


@lru_cache(maxsize=4096)
def to_simplified(value: str) -> str:
    return _TO_SIMPLIFIED.convert(value or "")


@lru_cache(maxsize=4096)
def command_variants(value: str) -> tuple[str, ...]:
    source = (value or "").strip()
    if not source:
        return ()
    variants = {
        source,
        _TO_SIMPLIFIED.convert(source),
        _TO_TRADITIONAL.convert(source),
    }
    return tuple(sorted((item for item in variants if item), key=len, reverse=True))
