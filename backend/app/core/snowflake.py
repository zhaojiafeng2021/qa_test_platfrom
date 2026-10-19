"""
Snowflake-like ID generator.

Produces 53-bit positive integers — fits JS Number.MAX_SAFE_INTEGER (2^53-1)
so the frontend can handle IDs as plain numbers without precision loss.

Layout (MSB -> LSB), total 53 bits:
  - 41 bits: milliseconds since custom epoch (2024-01-01) — ~69 years
  -  5 bits: worker id (0-31, from SNOWFLAKE_WORKER_ID env or random)
  -  7 bits: sequence within same millisecond (0-127)

Capacity: 128 IDs per ms per worker = 128,000/s — more than enough for a QA platform.

Usage:
  from app.core.snowflake import generate_id
  new_id = generate_id()
"""

import os
import time
import threading
import random

# Custom epoch: 2024-01-01 00:00:00 UTC in milliseconds
_EPOCH_MS = 1_704_067_200_000

_WORKER_BITS = 5
_SEQUENCE_BITS = 7

_MAX_WORKER_ID = (1 << _WORKER_BITS) - 1   # 31
_MAX_SEQUENCE = (1 << _SEQUENCE_BITS) - 1   # 127

_WORKER_SHIFT = _SEQUENCE_BITS              # 7
_TIMESTAMP_SHIFT = _WORKER_BITS + _SEQUENCE_BITS  # 12

_lock = threading.Lock()
_last_timestamp_ms: int = -1
_sequence: int = 0


def _get_worker_id() -> int:
    raw = os.environ.get("SNOWFLAKE_WORKER_ID")
    if raw is not None:
        wid = int(raw)
        if 0 <= wid <= _MAX_WORKER_ID:
            return wid
    return random.randint(0, _MAX_WORKER_ID)


_worker_id: int = _get_worker_id()


def _current_ms() -> int:
    return int(time.time() * 1000)


def generate_id() -> int:
    """Generate a unique snowflake ID (53-bit positive integer, JS-safe)."""
    global _last_timestamp_ms, _sequence

    with _lock:
        now = _current_ms()

        if now == _last_timestamp_ms:
            _sequence = (_sequence + 1) & _MAX_SEQUENCE
            if _sequence == 0:
                # Sequence exhausted in this ms, wait for next ms
                while now <= _last_timestamp_ms:
                    now = _current_ms()
        elif now < _last_timestamp_ms:
            # Clock moved backwards — use last timestamp + bump sequence
            now = _last_timestamp_ms
            _sequence = (_sequence + 1) & _MAX_SEQUENCE
            if _sequence == 0:
                now = _last_timestamp_ms + 1
        else:
            _sequence = 0

        _last_timestamp_ms = now
        ts = now - _EPOCH_MS

        return (ts << _TIMESTAMP_SHIFT) | (_worker_id << _WORKER_SHIFT) | _sequence
