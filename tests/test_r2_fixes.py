"""R2 修复的回归测试（限速 / 代理 / 非 TTY / 中文报错）。"""
from __future__ import annotations

import pytest

from fakes import FakeClock
from modcheck.cli.main import main
from modcheck.errors import EXIT_USAGE, ConfigError, ProviderRateLimited
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
    """启动不能有突发：第 limit+1 个请求必须等到窗口滑动。"""
    limit = 60
    clock = FakeClock()
    limiter = RateLimiter(limit, clock=clock.clock, sleep=clock.sleep)
    for _ in range(limit):
        limiter.acquire()
    assert clock.now == 0.0
    limiter.acquire()
    assert clock.now > 0.0


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
    assert set_setting(settings, "proxy", "socks5://10.0.0.1:1080").proxy == \
        "socks5://10.0.0.1:1080"
    for bad in ("127.0.0.1:7890", "http://", "://x", "随便写的"):
        with pytest.raises(ConfigError):
            set_setting(settings, "proxy", bad)


def test_cli_config_set_proxy_null_shows_unset(tmp_path, capsys) -> None:
    """端到端：设了代理再清掉，config show 显示「未设置」。"""
    assert main(["--config-dir", str(tmp_path), "config", "set", "proxy",
                 "http://127.0.0.1:7890"]) == 0
    assert main(["--config-dir", str(tmp_path), "config", "set", "proxy", "null"]) == 0
    main(["--config-dir", str(tmp_path), "config", "show"])
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if "代理" in line]
    assert lines and "未设置" in lines[0]
    assert "null" not in lines[0]


# ---------------------------------------------------------------- R2-05/06
def test_noninteractive_does_not_enter_menu(tmp_path, capsys) -> None:
    """重定向/管道下不进菜单（否则用户看到一堆提问后卡死）。"""
    code = main(["--config-dir", str(tmp_path), "--no-color"])
    captured = capsys.readouterr()
    assert code == EXIT_USAGE
    assert "无法进入菜单" in captured.out
    assert "请选择 >" not in captured.out


def test_invalid_loader_is_chinese_and_exit_three(capsys) -> None:
    """非法 --loader：中文提示 + 退出码 3，且不再吐英文 usage。"""
    assert main(["check", "--loader", "quilt"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "暂不支持加载器「quilt」" in err
    assert "usage:" not in err
    assert "invalid choice" not in err


def test_unknown_argument_is_chinese(capsys) -> None:
    """R2-4/X2：未知参数的提示里不允许出现 argparse 的英文原文。"""
    assert main(["--bogus"]) == EXIT_USAGE
    err = capsys.readouterr().err
    for banned in ("unrecognized", "invalid choice", "usage:", "expected one"):
        assert banned not in err, err
    assert "不认识的参数" in err


@pytest.mark.parametrize("value", ["quilt", "paper", "bukkit"])
def test_all_invalid_loaders(value: str, capsys) -> None:
    """所有非法加载器取值都返回 3 且带中文提示。"""
    assert main(["check", "--loader", value]) == EXIT_USAGE
    assert "✗" in capsys.readouterr().err
