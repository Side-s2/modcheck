"""领域异常定义。

全项目的异常都集中在这里，禁止在其它模块裸抛系统异常给用户看。
每条异常自带可读的中文信息（message）与可选的下一步建议（hint），
以及供 CLI 使用的退出码（exit_code，取值见 PRD §10.4）。
"""
from __future__ import annotations

EXIT_OK: int = 0
EXIT_BLOCKED: int = 1
EXIT_UNKNOWN: int = 2
EXIT_USAGE: int = 3
EXIT_NO_SOURCE: int = 4
EXIT_INTERRUPTED: int = 130
EXIT_INTERNAL: int = 70


class ModcheckError(Exception):
    """所有领域异常的基类。

    参数：
        message: 面向用户的中文说明。
        hint: 可选的下一步建议（CLI 会另起一行打印）。
        code: 可选的稳定错误码（只出现在 --debug / 导出里）。
    """

    exit_code: int = 1

    def __init__(self, message: str, *, hint: str = "", code: str = "") -> None:
        super().__init__(message)
        self._message = message
        self._hint = hint
        self.code = code

    @property
    def message(self) -> str:
        """面向用户的说明文本。"""
        return self._message

    @property
    def hint(self) -> str:
        """面向用户的下一步建议；没有则为空串。"""
        return self._hint


class ConfigError(ModcheckError):
    """配置 / 命令行参数错误。"""

    exit_code = EXIT_USAGE


class ProfileError(ModcheckError):
    """模组清单（profile）读写错误。"""

    exit_code = EXIT_USAGE


class JarReadError(ModcheckError):
    """单个 jar 读取失败；不致命，只影响这一条记录。"""

    exit_code = EXIT_OK


class UserCancelled(ModcheckError):
    """用户主动取消（例如交互里选择退出）。"""

    exit_code = EXIT_INTERRUPTED


class ProviderError(ModcheckError):
    """数据源错误基类；只由 providers/http.py 与各 Provider 抛出。"""

    retryable: bool = False


class ProviderUnavailable(ProviderError):
    """数据源未配置或整体不可用。"""

    exit_code = EXIT_NO_SOURCE


class ProviderNetworkError(ProviderError):
    """网络层错误（连不上、超时、证书问题）。"""

    retryable = True
    exit_code = EXIT_UNKNOWN


class ProviderHTTPError(ProviderError):
    """HTTP 状态码非 2xx。"""

    exit_code = EXIT_UNKNOWN

    def __init__(self, message: str, *, status: int, url: str, hint: str = "") -> None:
        super().__init__(message, hint=hint)
        self.status = status
        self.url = url


class ProviderRateLimited(ProviderHTTPError):
    """被限流（429）；可退避重试。"""

    retryable = True


class ProviderNotFound(ProviderError):
    """项目不存在（404）；不重试。"""

    exit_code = EXIT_UNKNOWN


class ProviderParseError(ProviderError):
    """响应体不是预期结构（改版、坏 JSON、体过大）。"""

    exit_code = EXIT_UNKNOWN


__all__ = [
    "EXIT_OK", "EXIT_BLOCKED", "EXIT_UNKNOWN", "EXIT_USAGE",
    "EXIT_NO_SOURCE", "EXIT_INTERRUPTED", "EXIT_INTERNAL",
    "ModcheckError", "ConfigError", "ProfileError", "JarReadError", "UserCancelled",
    "ProviderError", "ProviderUnavailable", "ProviderNetworkError",
    "ProviderHTTPError", "ProviderRateLimited", "ProviderNotFound", "ProviderParseError",
]
