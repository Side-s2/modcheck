"""验证限速器启动时均匀放行。"""
from fakes import FakeClock
from modcheck.providers.http import RateLimiter


def test_first_window_is_not_a_burst() -> None:
    """首窗不得一次性放行 limit 个：第 2 个请求就要等一个匀速间隔。"""
    limit = 60
    clock = FakeClock()
    limiter = RateLimiter(limit, clock=clock.clock, sleep=clock.sleep)
    limiter.acquire()
    assert clock.sleeps == []          # 第 1 个立即放行
    limiter.acquire()
    assert clock.sleeps, "第 2 个就该等一个 window/limit 的间隔"
    expected = 60.0 / limit
    assert abs(clock.sleeps[0] - expected) < 0.01
