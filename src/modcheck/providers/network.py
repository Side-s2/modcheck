"""网络操作的总时限和协作取消。"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import Future, InvalidStateError, wait
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Iterator, TypeVar

from modcheck.errors import ProviderNetworkError, UserCancelled
from modcheck.i18n import t

T = TypeVar("T")
_POLL_SECONDS = 0.1
# DNS 或证书链查询可能在调用者超时后仍在系统里运行。限制这类后台调用的数量。
_IO_SLOTS = threading.BoundedSemaphore(16)


@dataclass(frozen=True, slots=True)
class _Budget:
    deadline: float
    should_stop: Callable[[], bool] | None
    timeout: float
    cancelled: threading.Event


_budget: ContextVar[_Budget | None] = ContextVar("network_budget", default=None)


@contextmanager
def network_budget(seconds: float, should_stop: Callable[[], bool] | None = None) -> Iterator[None]:
    """为当前线程的请求、重试及限流等待共用一个截止时间。"""
    deadline = time.monotonic() + seconds
    previous = _budget.get()
    if previous is not None:
        if previous.deadline < deadline:
            deadline, seconds = previous.deadline, previous.timeout
        if should_stop is None:
            should_stop = previous.should_stop
    token = _budget.set(_Budget(deadline, should_stop, seconds, threading.Event()))
    try:
        yield
    finally:
        _budget.reset(token)


def remaining_time() -> float:
    budget = _budget.get()
    if budget is None:
        return math.inf
    if budget.cancelled.is_set() or (budget.should_stop is not None and budget.should_stop()):
        budget.cancelled.set()
        raise UserCancelled(t("scan.cancelled"))
    remaining = budget.deadline - time.monotonic()
    if remaining <= 0:
        raise ProviderNetworkError(t("err.network.deadline", timeout=f"{budget.timeout:g}"),
                                   code="DEADLINE", retryable=False)
    return remaining


def network_sleep(seconds: float, sleep: Callable[[float], None]) -> None:
    """在等待退避或限流时检查取消和截止时间。"""
    if _budget.get() is None:
        sleep(seconds)
        return
    while seconds > 0:
        delay = min(remaining_time(), _POLL_SECONDS, seconds)
        sleep(delay)
        seconds -= delay


def timeout_error(timeout: float) -> ProviderNetworkError:
    return ProviderNetworkError(t("err.network.timeout", timeout=f"{timeout:g}"), code="TIMEOUT")


def run_network(action: Callable[[], T], timeout: float, *,
                discard: Callable[[T], None] | None = None) -> T:
    """等待一次阻塞的 HTTP 操作，调用者可以按时退出。"""
    deadline = time.monotonic() + timeout

    def next_wait() -> float:
        available = min(remaining_time(), deadline - time.monotonic())
        if available <= 0:
            raise timeout_error(timeout)
        return min(available, _POLL_SECONDS) if _budget.get() is not None else available

    while not _IO_SLOTS.acquire(timeout=next_wait()):
        pass
    future: Future[T] = Future()

    def perform() -> None:
        try:
            try:
                result = action()
            except BaseException as exc:
                future.set_exception(exc)
            else:
                try:
                    future.set_result(result)
                except InvalidStateError:
                    if discard is not None:
                        discard(result)
        except InvalidStateError:
            pass  # 调用者离开后晚到的异常
        finally:
            _IO_SLOTS.release()

    try:
        next_wait()
        threading.Thread(target=perform, daemon=True, name="modcheck-http").start()
    except BaseException:
        _IO_SLOTS.release()
        raise
    try:
        while not wait((future,), timeout=next_wait()).done:
            pass
        remaining_time()
    except BaseException:
        if not future.cancel() and discard is not None:
            try:
                result = future.result()
            except Exception:
                pass
            else:
                discard(result)
        raise
    return future.result()
