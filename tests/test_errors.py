"""errors 层契约测试：继承关系与退出码必须与 PRD §10.4 一致。"""
from __future__ import annotations

import pytest

from modcheck import errors as e


def test_exit_code_constants() -> None:
    """退出码常量取值。"""
    assert (e.EXIT_OK, e.EXIT_BLOCKED, e.EXIT_UNKNOWN) == (0, 1, 2)
    assert (e.EXIT_USAGE, e.EXIT_NO_SOURCE, e.EXIT_INTERRUPTED) == (3, 4, 130)


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (e.ConfigError, e.EXIT_USAGE),
        (e.ProfileError, e.EXIT_USAGE),
        (e.JarReadError, e.EXIT_OK),
        (e.UserCancelled, e.EXIT_INTERRUPTED),
        (e.ProviderUnavailable, e.EXIT_NO_SOURCE),
        (e.ProviderNetworkError, e.EXIT_UNKNOWN),
        (e.ProviderNotFound, e.EXIT_UNKNOWN),
        (e.ProviderParseError, e.EXIT_UNKNOWN),
    ],
)
def test_exit_codes(cls: type[e.ModcheckError], code: int) -> None:
    """每个领域异常的退出码。"""
    assert cls.exit_code == code
    assert issubclass(cls, e.ModcheckError)


def test_http_error_carries_status_and_url() -> None:
    """ProviderHTTPError 必须带 status 与 url，且 hint 可用。"""
    err = e.ProviderHTTPError("boom", status=500, url="https://x/y", hint="later")
    assert (err.status, err.url, err.hint, err.message) == (500, "https://x/y", "later", "boom")
    assert isinstance(err, e.ProviderError)


def test_retryable_flags() -> None:
    """可重试标记：网络错误与限流为真，其余为假。"""
    assert e.ProviderNetworkError.retryable is True
    assert e.ProviderRateLimited.retryable is True
    assert e.ProviderError.retryable is False
    assert e.ProviderNotFound.retryable is False
    assert e.ProviderParseError.retryable is False
