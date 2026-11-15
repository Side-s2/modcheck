"""将 GUI 请求交给流程层，并将结果转换为界面数据。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from modcheck.core.models import Loader, ProjectInfo, Settings
from modcheck.core.profile_ops import add_mod, remove_mods, set_ignored, set_source
from modcheck.core.report import Report, ReportItem, reason_text, version_cell
from modcheck.errors import ConfigError
from modcheck.flows import (default_filename, export_json,
                            load_profile_entries, looks_like_mods_dir, prepare_download,
                            run_check_flow, run_download_flow, scan_dirs)
# 直接从子模块导入：flows/__init__ 的导出清单仍在变动，走包级导入容易被子代理的在途改动卡住
from modcheck.flows.export import export_modlist, import_modlist, read_modlist
from modcheck.flows.scan_flow import save_scan_result
from modcheck.flows.runtime import Runtime, build_runtime
from modcheck.gui.main_window import Row
from modcheck.providers.mojang import MojangVersions
from modcheck.providers.modrinth import ModrinthProvider
from modcheck.providers.network import network_budget
from modcheck.providers.registry import ProviderRegistry
from modcheck.storage.profiles import (delete_profile, list_profiles, load_profile, new_profile,
                                       profile_path, rename_profile, save_profile,
                                       validate_profile_name)
from modcheck.storage.settings import load_settings, save_settings

#: 与 CLI 的 --window 默认值保持一致；**不得为了省流量调小**（会漏掉真正可用的版本）
DEFAULT_WINDOW = 25
CHECK_NETWORK_TIMEOUT = 300.0


def _short_date(raw: str | None) -> str:
    """ISO 时间取到日；取不到就留空（不显示 None）。"""
    text = (raw or "").strip()
    return text[:10] if len(text) >= 10 and text[4] == "-" else ""


def _mod_name(item) -> str:
    """模组显示名：优先中文名/展示名，退到文件名，最后才用 key。"""
    mod = item.mod
    for attr in ("display_name", "cn_name", "file_name", "key"):
        value = getattr(mod, attr, "") or ""
        if value:
            return str(value)
    return "（未知）"


def _to_row(item: ReportItem, report: Report) -> Row:
    """把 core 的 ReportItem 转成界面用的行（纯搬运，不做判断）。"""
    latest = item.latest_compat or item.latest_for_loader or item.latest_any
    available = ""
    if item.status.value in ("degraded", "prerelease"):
        if item.latest_compat is not None:
            available = f"{item.latest_compat.version_number}（{_short_date(item.latest_compat.date_published)}）"
        elif item.latest_any is not None:
            available = f"{item.latest_any.version_number}（{item.latest_any.version_type} 通道）"
    reason = reason_text(item, report)
    return Row(name=_mod_name(item), status=item.status.value, version=version_cell(item),
               date=_short_date(latest.date_published if latest else None),
               reason=reason, available=available, mod_ids=tuple(item.mod.detected.mod_ids))


class GuiBackend:
    """界面与核心流程之间的适配器。"""

    def __init__(self, config_dir: str | Path | None = None, *, runtime: Runtime | None = None) -> None:
        self.runtime = runtime if runtime is not None else build_runtime(config_dir=config_dir)
        self.last_report: Report | None = None

    # ---------------------------------------------------------------- 清单
    def profiles(self) -> Sequence[tuple[str, int]]:
        """用文件名标识清单，以便打开手工改过文件名的 JSON。"""
        return [(summary.path.stem, summary.mod_count)
                for summary in list_profiles(self.runtime.profiles_dir)]

    # ---------------------------------------------------------------- 版本
    def versions(self, should_stop: Callable[[], bool] | None = None) -> Sequence[str]:
        """读取官方正式版列表，供后台线程调用。"""
        runtime = self.runtime
        ttl = runtime.settings.cache_ttl_hours["mojang"] * 3600
        with network_budget(20.0, should_stop):
            releases = MojangVersions(runtime.client, ttl=ttl).list_releases()
        return [release.version_id for release in releases if release.version_id]

    # ---------------------------------------------------------------- 检查
    def run(self, profile: str, mc: str, loader: str,
            on_progress: Callable[[int, int, str], None],
            should_stop: Callable[[], bool], *, window: int = DEFAULT_WINDOW,
            prerelease: bool = False, refresh: bool = False) -> list[Row]:
        """跑一次检查。**任何判定都不在这里发生** —— 全部来自 flows/core。

        window/prerelease 与 CLI 的同名参数**默认值必须一致**（25 / False）：
        它们是判定口径的一部分，两边不一致就会出现"同一个模组在 CLI 与 GUI 里结论不同"。
        """
        self.last_report = None
        runtime = self.runtime
        settings = runtime.settings
        client = runtime.client.for_operation(read_cache=settings.check_cache and not refresh)
        provider = ProviderRegistry.from_settings(settings, client).primary()
        loaded = load_profile_entries(profiles_dir=runtime.profiles_dir,
                                      profile=profile, provider=provider,
                                      on_progress=on_progress, should_stop=should_stop)
        with network_budget(CHECK_NETWORK_TIMEOUT, should_stop):
            outcome = run_check_flow(
                loaded.entries, provider=provider,
                loader=Loader.parse(loader.strip().lower()), mc_version=mc,
                window=int(window), prerelease=bool(prerelease),
                jobs=int(settings.concurrency), on_progress=on_progress,
                should_stop=should_stop, stats_source=client,
                profile_name=profile, profile_saved=loaded.saved)
        report = outcome.report
        rows = [_to_row(item, report) for item in report.iter_items()]
        self.last_report = report
        return rows

    # ---------------------------------------------------------------- 导出
    def export_default_name(self) -> str:
        """生成本次检查报告的 JSON 文件名。"""
        report = self.last_report
        if report is None:
            return "report.json"
        return default_filename(report.profile_name, report.mc_version, report.loader)

    def export_to(self, path: str | Path) -> Path:
        """导出 JSON 报告。"""
        if self.last_report is None:
            raise RuntimeError("还没有可导出的报告")
        target = self._export_path(path)
        export_json(self.last_report, target)
        return target

    def _export_path(self, path: str | Path) -> Path:
        target = Path(path)
        if target.suffix.lower() != ".json":
            raise ConfigError("请使用 .json 扩展名保存文件。")
        existing = target.resolve()
        if (existing.parent == self.runtime.profiles_dir.resolve()
                or existing == self.runtime.settings_path.resolve()):
            raise ConfigError("请另选保存位置，以免覆盖程序正在使用的清单或设置。")
        return target

    # ---------------------------------------------------------------- 清单管理（二期）
    # 所有"怎么改"的规则都在 core/profile_ops.py 里；这里只负责"读进来、改、写回去"。
    def load_profile(self, name: str):
        """读一份清单。"""
        profile = load_profile(profile_path(self.runtime.profiles_dir, name))
        profile.name = name
        return profile

    def save_profile(self, profile) -> None:
        """写回清单（原子写盘由 storage 负责，失败会抛领域异常）。"""
        save_profile(profile, profile_path(self.runtime.profiles_dir, profile.name))

    def create_profile(self, name: str):
        """新建空清单（重名会抛错，由界面提示）。"""
        validate_profile_name(name)
        if profile_path(self.runtime.profiles_dir, name).exists():
            raise ValueError(f"清单「{name}」已存在")
        profile = new_profile(name)
        self.save_profile(profile)
        return profile

    def rename_profile_file(self, old: str, new: str) -> None:
        """重命名（同时改文件名与 profile.name，由 storage 保证一致）。"""
        validate_profile_name(new)
        source = profile_path(self.runtime.profiles_dir, old)
        target = profile_path(self.runtime.profiles_dir, new)
        if target.exists():
            raise ValueError(f"清单「{new}」已存在")
        rename_profile(source, target)

    def delete_profile_file(self, name: str) -> None:
        """删除清单 —— 唯一不可撤销的操作，界面必须二次确认。"""
        delete_profile(profile_path(self.runtime.profiles_dir, name))

    # 模组级操作：一律走 core/profile_ops，界面不自己判断"改哪个"
    def remove_mods(self, profile, selectors):
        return remove_mods(profile, list(selectors))

    def verify_project(self, slug: str, should_stop: Callable[[], bool]) -> ProjectInfo:
        """通过实时请求确认 Modrinth 上存在这个模组。"""
        client = self.runtime.client.for_operation(read_cache=False)
        with network_budget(20.0, should_stop):
            project = ModrinthProvider(client).get_project(slug)
        if project is None:
            raise ConfigError(f"Modrinth 上找不到项目「{slug}」。请检查链接或项目标识。")
        if not project.slug or not project.project_id:
            raise ConfigError("Modrinth 返回的项目信息不完整，请稍后重试。")
        if project.project_type != "mod":
            raise ConfigError(f"「{project.title or project.slug}」在 Modrinth 上不是模组项目。")
        return project

    def set_source(self, profile, selector, *, project: ProjectInfo):
        return set_source(profile, selector, provider="modrinth", slug=project.slug,
                          title=project.title)

    def set_ignored(self, profile, selector, ignored):
        return set_ignored(profile, selector, ignored)

    def add_mod(self, profile, **kwargs):
        return add_mod(profile, **kwargs)

    # ---------------------------------------------------------------- 设置（二期）
    def load_settings(self) -> Settings:
        """当前设置（GUI 直接改它的副本再存回）。"""
        return load_settings(self.runtime.settings_path)

    def save_settings(self, settings) -> None:
        """写回设置。非法值由 core/settings_ops 的 setter 拦在前面，不该走到这里。"""
        # ⚠️ 参数顺序是 (path, settings)，不是 (settings, path) ——
        # 写反了会报 "TypeError: expected str, bytes or os.PathLike object, not Settings"
        save_settings(self.runtime.settings_path, settings)
        self.runtime = build_runtime(resolved_directory=self.runtime.config_dir)

    def settings_ops(self):
        """把 core.settings_ops 整个暴露给设置对话框 —— 校验规则只有一份实现。"""
        from modcheck.core import settings_ops

        return settings_ops


    # ---------------------------------------------------------------- 导入清单
    def import_modlist_file(self, path) -> object:
        """导入别人导出的 JSON 清单。

        先 read_modlist **严格校验**（缺字段/类型不对/版本不符都会给出中文说明），
        校验通过再交给 import_modlist 合并 —— 合并逻辑与扫描落盘**是同一段代码**，
        不存在"导入一套规则、扫描另一套规则"的漂移。
        目标清单名取 JSON 里的 name（与 CLI 语义一致：同名即合并）。
        """
        profile = read_modlist(Path(path))
        return import_modlist(profile, profiles_dir=self.runtime.profiles_dir,
                              profile_name=profile.name)

    def export_modlist_file(self, name: str, path: str | Path) -> Path:
        target = self._export_path(path)
        export_modlist(self.load_profile(name), target)
        return target

    # ---------------------------------------------------------------- 扫描（三期）
    def scan(self, folders, on_progress=None, should_stop=None, on_network_progress=None):
        """扫描若干文件夹并返回 ScanReport（识别规则全在 flows/core 里）。"""
        return scan_dirs([Path(f) for f in folders],
                         provider=self.runtime.registry.primary(),
                         on_progress=on_progress, should_stop=should_stop,
                         on_network_progress=on_network_progress)

    def save_scan(self, scan_report, profile_name: str, *, new: bool = False):
        """把扫描结果合并进清单并原子写盘。"""
        return save_scan_result(scan_report, profiles_dir=self.runtime.profiles_dir,
                                profile_name=profile_name, new=new)

    # ---------------------------------------------------------------- 下载（三期）
    def prepare_download(self, report, target_dir, *, include_prerelease: bool = False):
        """只做选品与同名冲突检测，**不写盘、不建目录** —— 先让用户看清楚要下什么。

        include_prerelease=True 时把 🟠 仅存测试版也纳入计划（默认 False：
        默认把测试版下给用户等于替他做危险决定）。
        """
        return prepare_download(report, Path(target_dir),
                                include_prerelease=bool(include_prerelease))

    def looks_like_mods_dir(self, target_dir) -> bool:
        """目标目录看起来是"正在用的 mods 文件夹"吗（要额外提醒一次）。"""
        return looks_like_mods_dir(Path(target_dir))

    def run_download(self, prep, *, selected=None, overwrite=None, on_progress=None,
                     on_item=None, should_stop=None):
        """真正下载。复用同一个 HttpClient（下载与 API 共用限速器，裁决 D45）。

        ⚠️ on_progress 的签名是 (DownloadItem, 已下载字节, 文件总字节) ——
        **不是**检查流程那种 (已完成, 总数, 名称)。GUI 侧踩过一次这个坑。
        """
        return run_download_flow(prep, self.runtime.client, overwrite=overwrite,
                                 selected=selected if selected is not None else {},
                                 on_progress=on_progress, on_item=on_item,
                                 should_stop=should_stop)


__all__ = ["GuiBackend"]
