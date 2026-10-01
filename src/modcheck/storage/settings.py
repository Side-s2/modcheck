"""settings.json 的读写（JSON + UTF-8 无 BOM，原子写）。

损坏的配置**绝不**让程序崩：备份成 settings.json.bak-<时间戳> 后重建默认值。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Final

from modcheck.core.models import Loader, Settings
# 代理解析规则只有一份（core/settings_ops.py，裁决 D42），这里复用
from modcheck.core.settings_ops import NULL_WORDS as _CORE_NULL_WORDS
from modcheck.core.settings_ops import parse_proxy as _core_parse_proxy
from modcheck.errors import ConfigError, ModcheckError
from modcheck.i18n import t

#: config set 允许修改的键（点号表示嵌套）
SETTING_KEYS: Final[tuple[str, ...]] = (
    "default_mc_version", "default_loader", "color", "proxy",
    "concurrency", "timeout_seconds", "retries", "cache_ttl_hours",
    "providers.curseforge.api_key",
)


def _defaults() -> Settings:
    return Settings()


def load_settings(path: Path) -> Settings:
    """读取设置；文件不存在时返回默认值（**不写盘**，写盘由调用方决定）。"""
    target = Path(path)
    try:
        with target.open("r", encoding="utf-8-sig") as handle:  # 容忍记事本写的 BOM
            raw = json.load(handle)
    except FileNotFoundError:
        return _defaults()
    except (OSError, ValueError, UnicodeDecodeError):
        _backup(target)
        return _defaults()
    if not isinstance(raw, dict):
        _backup(target)
        return _defaults()
    return Settings.from_dict(raw)


def save_settings(path: Path, settings: Settings) -> None:
    """原子写入设置（先写 .tmp 再 os.replace）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(settings.to_dict(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, target)


def _backup(path: Path) -> None:
    """把损坏的配置改名留档，避免用户数据被静默覆盖。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        os.replace(path, path.with_name(path.name + ".bak-" + stamp))
    except OSError:
        pass


def set_setting(settings: Settings, key: str, raw: str) -> Settings:
    """按命令行键值改设置，返回新的 Settings（不写盘）。

    抛出：
        ConfigError: 键不认识或值不合法。
    """
    normalized = key.strip()
    if normalized not in SETTING_KEYS:
        raise ConfigError(t("config.unknown_key", key=key, keys="、".join(SETTING_KEYS)))
    text = raw.strip()
    if normalized == "default_mc_version":
        settings.default_mc_version = text or None
    elif normalized == "default_loader":
        settings.default_loader = Loader.parse(text)
    elif normalized == "color":
        if text not in ("auto", "always", "never"):
            raise ConfigError(t("config.bad_value", key=key, value=raw))
        settings.color = text
    elif normalized == "proxy":
        settings.proxy = _parse_proxy(text, raw)
    elif normalized == "concurrency":
        settings.concurrency = _as_int(text, key, raw, 1, 8)
    elif normalized == "timeout_seconds":
        settings.timeout_seconds = float(_as_int(text, key, raw, 1, 600))
    elif normalized == "retries":
        settings.retries = _as_int(text, key, raw, 0, 10)
    elif normalized == "cache_ttl_hours":
        hours = float(_as_int(text, key, raw, 0, 24 * 30))
        settings.cache_ttl_hours = {"mojang": max(hours, 1.0), "api": hours}
    elif normalized == "providers.curseforge.api_key":
        settings.providers.setdefault("curseforge", {})
        settings.providers["curseforge"]["api_key"] = text or None
    return settings


#: 表示"清除这一项"的输入（规则定义在 core/settings_ops.py，这里只做别名导出）
NULL_WORDS: Final[tuple[str, ...]] = _CORE_NULL_WORDS


def _parse_proxy(text: str, raw: str) -> str | None:
    """解析代理设置（实现与 core/settings_ops.parse_proxy 共用一份，裁决 D42）。"""
    del text  # 只为兼容旧调用签名，实际用原文解析
    return _core_parse_proxy(raw)


def _as_int(text: str, key: str, raw: str, low: int, high: int) -> int:
    """解析整数并做范围校验。"""
    try:
        value = int(text)
    except ValueError as exc:
        raise ConfigError(t("config.bad_value", key=key, value=raw)) from exc
    if not low <= value <= high:
        raise ConfigError(t("config.bad_value", key=key, value=raw))
    return value


def settings_or_default(path: Path, warnings: list[str] | None = None) -> Settings:
    """读取设置并把失败降级成一句警告（供 CLI 使用）。"""
    try:
        return load_settings(path)
    except ModcheckError as exc:  # 目前 load_settings 不抛，留作防御
        if warnings is not None:
            warnings.append(exc.message)
        return _defaults()


__all__ = ["SETTING_KEYS", "load_settings", "save_settings", "set_setting", "settings_or_default"]
