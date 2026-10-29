"""In-process lock per idempotency key.

Why not a database lock: the model call can take minutes, and a transaction (and its pooled connection) must not stay
open that long. The lock is held across the whole run instead, so a double submit of the same key in the SAME server
process waits and then replays the stored answer. The unique index on (session_id, idempotency_key) is the backstop
for several processes: the loser gets the stored answer, but its model call may already have happened (documented)."""
import threading
from collections.abc import Iterator
from contextlib import contextmanager


class KeyedLocks:
    def __init__(self):
        self._guard = threading.Lock()
        self._locks: dict[str, list] = {}  # key -> [lock, number of users]

    @contextmanager
    def hold(self, key: str) -> Iterator[None]:
        with self._guard:
            entry = self._locks.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        entry[0].acquire()
        try:
            yield
        finally:
            entry[0].release()
            with self._guard:
                entry[1] -= 1
                if entry[1] == 0:
                    self._locks.pop(key, None)
