"""R2 修复的回归测试（限速 / 代理）。"""
from __future__ import annotations

import pytest

from fakes import FakeClock
from modcheck.errors import ConfigError, ProviderRateLimited
from modcheck.providers.http import MAX_STALLS, RateLimiter
from modcheck.storage.settings import load_settings, set_setting


# ---------------------------------------------------------------- R2-02 限速
def test_acquire_does_not_spin_when_clock_is_frozen() -> None:
    """死循环回归（P0）：冻结时钟 + 空 sleep 时，acquire 必须有限步内抛异常。

    旧实现（令牌桶）在这里 100% CPU 空转、永不返回 ——
    表现为"测试卡死"而不是"测试失败"，实测烧掉 4.5 分钟 CPU。
    """
    limiter = RateLimiter(1, clock=lambda: 1000.0, sleep=lambda _s: None)
    limiter.acquire()                     # 用掉窗口里唯一的名额
    with pytest.raises(ProviderRateLimited):
        limiter.acquire()                 # 旧实现会永久挂死在这一行
    assert MAX_STALLS > 0


def test_sliding_window_never_exceeds_limit() -> None:
    """任意 60 秒滑动窗口内的放行数不得超过上限。"""
    limit = 60
    clock = FakeClock()
    limiter = RateLimiter(limit, clock=clock.clock, sleep=clock.sleep)
    stamps: list[float] = []
    for _ in range(limit * 2):
        limiter.acquire()
        stamps.append(clock.now)
    worst = max((sum(1 for t in stamps if start <= t < start + 60) for start in stamps),
                default=0)
    assert worst <= limit, f"60 秒窗口内最多 {worst} 次，超过上限 {limit}"


def test_no_burst_at_start() -> None:
    """启动不能有突发：limit 个请求要铺满整个窗口，而不是瞬间放行。

    PM 实测：正是"首个 60 秒窗口一次性放行 limit 个"把 429 打出来的
    （200 个不同项目冷跑出现 18 条限流未判定）。
    """
    limit = 60
    clock = FakeClock()
    limiter = RateLimiter(limit, clock=clock.clock, sleep=clock.sleep)
    limiter.acquire()
    assert clock.now == 0.0            # 第 1 个立即放行
    for _ in range(limit - 1):
        limiter.acquire()
    assert clock.now > 0.0             # 其余按 1 秒间隔铺开，不是瞬时
    assert abs(clock.now - (limit - 1)) < 0.5


# ---------------------------------------------------------------- R2-03 代理
def test_config_set_proxy_null_clears_it(tmp_path) -> None:
    """null / none / - / 空串 一律表示清除，绝不写成字符串 "null"。"""
    settings = load_settings(tmp_path / "settings.json")
    settings.proxy = "http://127.0.0.1:7890"
    for word in ("null", "NULL", "none", "-", ""):
        set_setting(settings, "proxy", word)
        assert settings.proxy is None, word


def test_config_set_proxy_validates_format(tmp_path) -> None:
    """非法代理必须拒绝（不落盘）；合法值原样保存。"""
    settings = load_settings(tmp_path / "settings.json")
    assert set_setting(settings, "proxy", "http://127.0.0.1:7890").proxy == \
        "http://127.0.0.1:7890"
    for bad in ("127.0.0.1:7890", "http://", "://x", "随便写的", "socks5://10.0.0.1:1080"):
        with pytest.raises(ConfigError):
            set_setting(settings, "proxy", bad)
    assert settings.proxy == "http://127.0.0.1:7890"
