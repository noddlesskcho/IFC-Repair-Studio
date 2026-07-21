from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def cancelled(self) -> bool:
        return self._event.is_set()


def run_stage(function: Callable[..., Any], token: CancellationToken, **kwargs: Any) -> Any:
    return function(cancelled=token.cancelled, **kwargs)
