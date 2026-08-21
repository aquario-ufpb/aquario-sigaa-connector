from __future__ import annotations

import asyncio
from threading import Event

import pytest
from pydantic import SecretStr

from aquario_sigaa_connector.errors import ConnectorError, FailureKind
from aquario_sigaa_connector.execution import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    BoundedSyncExecutor,
)
from aquario_sigaa_connector.service import SyncCommand


class BlockingProvider:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def synchronize(self, _command: SyncCommand):
        self.started.set()
        self.release.wait(timeout=1)
        return None


class FailingAfterReleaseProvider(BlockingProvider):
    def synchronize(self, command: SyncCommand):
        super().synchronize(command)
        raise RuntimeError("raw private response")


def _command() -> SyncCommand:
    return SyncCommand(
        username="20260000001",
        password=SecretStr("private-password"),
        expected_matricula=None,
    )


def test_executor_defaults_to_one_worker_and_145_second_wait():
    provider = BlockingProvider()
    executor = BoundedSyncExecutor(provider)

    assert DEFAULT_MAX_WORKERS == 1
    assert DEFAULT_WAIT_TIMEOUT_SECONDS == 145.0
    assert executor.max_workers == 1
    assert executor.wait_timeout_seconds == 145.0
    executor.shutdown()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_workers": 0},
        {"wait_timeout_seconds": 0},
    ],
)
def test_executor_rejects_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        BoundedSyncExecutor(BlockingProvider(), **kwargs)


def test_caller_cancellation_does_not_release_running_worker_permit():
    async def scenario() -> None:
        provider = BlockingProvider()
        executor = BoundedSyncExecutor(provider)
        task = asyncio.create_task(executor.execute(_command()))
        assert await asyncio.to_thread(provider.started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        with pytest.raises(ConnectorError) as error:
            await executor.execute(_command())
        assert error.value.kind is FailureKind.CONNECTOR_BUSY

        provider.release.set()
        await asyncio.sleep(0.02)
        executor.shutdown()

    asyncio.run(scenario())


def test_timeout_consumes_late_worker_exception_without_loop_logging():
    async def scenario() -> None:
        provider = FailingAfterReleaseProvider()
        executor = BoundedSyncExecutor(provider, wait_timeout_seconds=0.01)
        contexts: list[dict] = []
        asyncio.get_running_loop().set_exception_handler(
            lambda _loop, context: contexts.append(context)
        )

        with pytest.raises(ConnectorError) as error:
            await executor.execute(_command())
        assert error.value.kind is FailureKind.CONNECTOR_DEADLINE

        provider.release.set()
        await asyncio.sleep(0.05)
        assert contexts == []
        executor.shutdown()

    asyncio.run(scenario())
