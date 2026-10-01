"""设置项的纯函数操作 + 取值校验（PRD §13.1 / §13.3，R3-A02）。

约束与 core/profile_ops.py 相同：不 import storage、不写盘、不 print / input；
每个 setter 都返回**新的** Settings（dict 字段深拷贝），非法值抛 ConfigError。
文案一律复用 §13.3 的 key，绝不在 core 里现编中文。
"""
from __future__ import annotations

from typing import Collection, Final

from modcheck.core.mcversion import validate_target_version
from modcheck.core.models import Loader, Settings
from modcheck.errors import ConfigError
from modcheck.i18n import t

#: 表示「清除这一项」的输入（与 storage/settings.py 语义相同，裁决 D42）
NULL_WORDS: Final[tuple[str, ...]] = ("", "null", "none", "-", "nil")

#: 并发数范围（PRD §13.3 [5]）
JOBS_LOW: Final[int] = 1
JOBS_HIGH: Final[int] = 8
#: 缓存有效期范围（小时，PRD §13.3 [6]）
TTL_LOW: Final[float] = 1.0
TTL_HIGH: Final[float] = 168.0
#: 缓存有效期的两个键（与 settings.json 的 cache_ttl_hours 一致）
TTL_KEYS: Final[tuple[str, ...]] = ("mojang", "api")
#: 颜色模式（PRD §13.3 [4]）
COLORS: Final[tuple[str, ...]] = ("auto", "always", "never")


def clone(settings: Settings) -> Settings:
    """深拷贝一份 Settings（cache_ttl_hours / providers 不共享）。"""
    return Settings(
        schema_version=settings.schema_version,
        default_mc_version=settings.default_mc_version,
        default_loader=settings.default_loader,
        color=settings.color,
        proxy=settings.proxy,
        concurrency=int(settings.concurrency),
        timeout_seconds=float(settings.timeout_seconds),
        retries=int(settings.retries),
        cache_ttl_hours={str(k): float(v) for k, v in settings.cache_ttl_hours.items()},
        providers={str(k): dict(v) for k, v in settings.providers.items()},
    )


def is_null_word(value: str | None) -> bool:
    """是否是「清除」语义的输入（大小写不敏感）。"""
    return (value or "").strip().lower() in NULL_WORDS


def set_default_mc(settings: Settings, value: str | None, *,
                   known: Collection[str]) -> Settings:
    """设置默认游戏版本；None / 空串 / null 表示清除。

    参数：
        settings: 原设置（不被修改）。
        value: 版本号或清除标记。
        known: 官方正式版清单；为空时跳过「是否存在」检查（没联网时）。

    抛出：
        ConfigError: 格式非法、是快照版、或不在官方清单里（PRD E07/E08/E09）。
    """
    new = clone(settings)
    if value is None or is_null_word(value):
        new.default_mc_version = None
        return new
    text = str(value).strip()
    validate_target_version(text, known)
    new.default_mc_version = text
    return new


def set_default_loader(settings: Settings, value: str | None) -> Settings:
    """设置默认加载器；None / 空串表示恢复默认（Fabric）。

    PRD §13.3 [2] 有 [c] 清除：加载器没有「未设置」态，清除即恢复默认值。

    抛出：
        ConfigError: 不认识的加载器。
    """
    new = clone(settings)
    if value is None or is_null_word(value):
        new.default_loader = Loader.FABRIC
        return new
    new.default_loader = Loader.parse(str(value))
    return new


def set_color(settings: Settings, value: str) -> Settings:
    """设置颜色模式（auto / always / never）。

    抛出：
        ConfigError: 不是三种模式之一。
    """
    text = (value or "").strip().lower()
    if text not in COLORS:
        raise ConfigError(t("settings.color.bad", value=value))
    new = clone(settings)
    new.color = text
    return new


def parse_proxy(raw: str) -> str | None:
    """解析代理地址：null/none/-/空串 = 清除；其余必须是 scheme://host[:port]。

    实测教训（D42）：config set proxy null 会把字符串 null 写进配置，
    此后所有网络请求永久失败，而 config show 显示「代理：null」看起来像没设。
    所以既支持「清除」语义，也拒绝非法值。

    抛出：
        ConfigError: 不满足 scheme://host 形式。
    """
    text = (raw or "").strip()
    if text.lower() in NULL_WORDS:
        return None
    scheme, sep, rest = text.partition("://")
    if not sep or not scheme.isalnum() or not rest:   # socks5 这类 scheme 含数字
        raise ConfigError(t("config.bad_proxy", value=raw))
    if not rest.split("/", 1)[0]:                     # http:///x 这类没有主机名
        raise ConfigError(t("config.bad_proxy", value=raw))
    return text


def set_proxy(settings: Settings, value: str | None) -> Settings:
    """设置代理（见 parse_proxy）。

    抛出：
        ConfigError: 代理地址非法。
    """
    new = clone(settings)
    new.proxy = parse_proxy("" if value is None else str(value))
    return new


def set_concurrency(settings: Settings, value: int) -> Settings:
    """设置并发数（1-8，PRD §13.3 [5]）。

    抛出：
        ConfigError: 不是整数或超出范围。
    """
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(t("settings.jobs.range", value=value)) from None
    if not JOBS_LOW <= number <= JOBS_HIGH:
        raise ConfigError(t("settings.jobs.range", value=value))
    new = clone(settings)
    new.concurrency = number
    return new


def set_cache_ttl(settings: Settings, key: str, hours: float) -> Settings:
    """设置某一类缓存的有效期（小时，1-168）。

    参数：
        key: mojang（官方版本清单）或 api（Modrinth）。
        hours: 小时数。

    抛出：
        ConfigError: 键不认识，或小时数超范围。
    """
    name = (key or "").strip()
    if name not in TTL_KEYS:
        raise ConfigError(t("config.unknown_key", key=key, keys="、".join(TTL_KEYS)))
    try:
        number = float(str(hours).strip())
    except (TypeError, ValueError):
        raise ConfigError(t("settings.cache.range", value=hours)) from None
    if not TTL_LOW <= number <= TTL_HIGH:
        raise ConfigError(t("settings.cache.range", value=hours))
    new = clone(settings)
    new.cache_ttl_hours[name] = number
    return new


def set_curseforge_key(settings: Settings, value: str | None) -> Settings:
    """设置 CurseForge API Key；null 系列输入表示清除。"""
    new = clone(settings)
    text = (value or "").strip()
    new.providers.setdefault("curseforge", {})
    new.providers["curseforge"]["api_key"] = None if text.lower() in NULL_WORDS else text
    return new


def mask_secret(value: str | None) -> str:
    """回显用：只露出后 4 位（PRD §13.3 [7]）。"""
    text = (value or "").strip()
    if not text:
        return ""
    return "****" + text[-4:]


def reset_settings() -> Settings:
    """出厂默认设置（等价于 load_settings 在没有文件时给出的默认值）。"""
    return Settings()


__all__ = [
    "NULL_WORDS", "JOBS_LOW", "JOBS_HIGH", "TTL_LOW", "TTL_HIGH", "TTL_KEYS", "COLORS",
    "clone", "is_null_word", "set_default_mc", "set_default_loader", "set_color",
    "parse_proxy", "set_proxy", "set_concurrency", "set_cache_ttl",
    "set_curseforge_key", "mask_secret", "reset_settings",
]
