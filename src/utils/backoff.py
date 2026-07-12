"""
Retry utilities with (optional) jittered exponential backoff.
"""
from __future__ import annotations
import random
import time
from functools import wraps
from typing import Callable, TypeVar, Any, Tuple, Dict

T = TypeVar("T")


def retry(max_tries: int = 5, base: float = 0.2, cap: float = 2.5, jitter: bool = True):
    """A simple retry decorator for transient failures.

    Args:
        max_tries: Maximum attempts before raising.
        base: Base backoff in seconds.
        cap: Maximum sleep between retries.
        jitter: Add random jitter to backoff if True.
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> T:
            attempt = 0
            exc: Exception | None = None
            while attempt < max_tries:
                try:
                    return fn(*args, **kwargs)
                except Exception as e:  # noqa: BLE001
                    exc = e
                    attempt += 1
                    if attempt >= max_tries:
                        break
                    delay = min(cap, base * (2 ** (attempt - 1)))
                    if jitter:
                        delay = delay * (0.5 + random.random())
                    time.sleep(delay)
            assert exc is not None
            raise exc

        return wrapper

    return decorator
