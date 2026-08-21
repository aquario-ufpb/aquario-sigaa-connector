"""Bounded execution for the synchronous SIGAA client."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from .contracts import SyncResponse
from .errors import ConnectorError, FailureKind
from .service import SyncCommand, _SyncProvider

DEFAULT_MAX_WORKERS = 1
DEFAULT_WAIT_TIMEOUT_SECONDS = 145.0


class BoundedSyncExecutor:
    def __init__(
        self,
        provider: _SyncProvider,
        *,
        max_workers: int = DEFAULT_MAX_WORKERS,
        wait_timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        if wait_timeout_seconds <= 0:
            raise ValueError("wait_timeout_seconds must be positive")
        self.max_workers = max_workers
        self.wait_timeout_seconds = wait_timeout_seconds
        self._provider = provider
        self._permits = BoundedSemaphore(max_workers)
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="sigaa-sync",
        )

    async def execute(self, command: SyncCommand) -> SyncResponse:
        if not self._permits.acquire(blocking=False):
            raise ConnectorError(FailureKind.CONNECTOR_BUSY)

        try:
            concurrent_future = self._pool.submit(self._provider.synchronize, command)
        except Exception as exc:
            self._permits.release()
            raise ConnectorError(FailureKind.INTERNAL_ERROR) from exc

        concurrent_future.add_done_callback(lambda _future: self._permits.release())
        async_future = asyncio.wrap_future(concurrent_future)
        async_future.add_done_callback(_consume_future_exception)
        try:
            return await asyncio.wait_for(
                asyncio.shield(async_future),
                timeout=self.wait_timeout_seconds,
            )
        except TimeoutError as exc:
            raise ConnectorError(FailureKind.CONNECTOR_DEADLINE) from exc

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=False)


def _consume_future_exception(future: asyncio.Future[SyncResponse]) -> None:
    if not future.cancelled():
        future.exception()
