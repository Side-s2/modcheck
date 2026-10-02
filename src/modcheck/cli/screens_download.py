"""菜单 [5]：检查并下载模组（PRD §14.4，R3-B04 ~ R3-B09）。

分层（本文件只做两件事）：
    ① **问**：要不要下载 / 选哪个文件夹 / 同名文件怎么办 / 要不要开跑；
    ② **画**：进度行、取消语、汇总屏。
选品、冲突判断、并发下载、重试、取消清理、汇总数字全部来自
flows/download_flow.py 与 core/downloader.py —— 这里一句业务判断都不写，
否则 GUI 三期就得再实现一遍（那正是"同一个 bug 只在一边复现"的来源）。

Ctrl+C 的处理：下载跑在工作线程里，主线程只等它。收到 Ctrl+C 时置取消事件，
再等流程自己收尾 —— 这样"没下完的临时文件已清理"是真的，
而不是把线程池连同 .part 一起丢在那里。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Final

from modcheck.cli.context import AppContext
from modcheck.cli.folderpicker import (FOLDER_CANCELLED, FOLDER_OK, FOLDER_UNAVAILABLE,
                                       pick_folder_ex)
from modcheck.cli.prompts import KIND_BACK, KIND_QUIT, read_line
from modcheck.core.downloader import (SKIP_NO_JAR, SKIP_NO_VERSION, DownloadItem,
                                      overwrite_key)
from modcheck.core.report import Report
from modcheck.flows.download_flow import (TARGET_MISSING, DownloadOutcome, DownloadPrep,
                                          check_target_dir, ensure_target_dir,
                                          prepare_download, run_download_flow)
from modcheck.i18n import t

#: TTY 进度行的最小刷新间隔（秒）：每秒刷十几次既看不出区别又白费 CPU
PROGRESS_INTERVAL: Final[float] = 0.2
#: 进度条格子数
BAR_WIDTH: Final[int] = 10


def format_mb(size: int | float | None) -> str:
    """把字节数变成 MB 文本（一位小数）。"""
    return "%.1f" % (float(size or 0) / (1024 * 1024))


def download_nothing_line(report: Report) -> str:
    """一个模组都没得下时的结论（PRD §14.4）。"""
    data = report.summary
    return t("download.nothing", blocked=data.get("blocked", 0),
             prerelease=data.get("prerelease", 0), unknown=data.get("unknown", 0))


def nothing_lines(report: Report, prep: DownloadPrep) -> list[str]:
    """没有可下载文件时要说的行。

    两种完全不同的情况不能共用一句话（PRD §14.4 那句里写死了「🟢 0」）：
      * 检查结果里本来就没有 🟢/🟡 -> 用 PRD 那句，逐字、且句句属实；
      * 有 🟢/🟡、但它们的版本里没有可下载的主文件 -> 逐条列出原因，
        否则用户看到"没有需要下载的模组（🟢 0）"会以为程序没认出他的模组。
    """
    reasons = [(entry, key) for entry, key in prep.plan.skipped
               if key in (SKIP_NO_JAR, SKIP_NO_VERSION)]
    if not reasons:
        return [download_nothing_line(report)]
    lines = [t("download.nothing.skipped")]
    lines += [t("download.nothing.item", name=entry.file_name or entry.best_name or entry.key,
                reason=t(key)) for entry, key in reasons]
    return lines


def ask_download(ctx: AppContext) -> bool:
    """检查结束后问"要不要下载"（默认 N，绝不默认替用户做决定）。"""
    console = ctx.console
    for key in ("download.ask.note1", "download.ask.note2", "download.ask.note3"):
        console.line(t(key))
    return ctx.prompter.confirm(t("download.ask.prompt"), default=False)


def ask_prerelease(ctx: AppContext) -> bool:
    """问"要不要连 🟠 仅存测试版一起下"（默认 N：测试版可能崩档，不能替用户决定）。

    单独一问、而不是并进 ask_download：默认范围（🟢/🟡）要能用一句话说清，
    而这个开关一旦打开，下载内容里会多出**可能不稳定**的测试版，必须单独拍板。
    """
    ctx.console.line(t("download.prerelease.note"))
    return ctx.prompter.confirm(t("download.prerelease.prompt"), default=False)


def choose_target_dir(ctx: AppContext, prep: DownloadPrep, *,
                      picker: Callable[[str], tuple[str, str | None]] | None = None,
                      ) -> Path | None:
    """选下载目标文件夹；返回 None 表示取消下载（不是错误）。

    Windows 优先弹原生对话框；非 Windows / 对话框不可用 / 用户取消对话框分别处理：
    取消对话框 = 取消下载（PRD §14.4），没有对话框 = 回退手输。

    picker 默认 None 时在**运行时**取模块里的 pick_folder_ex ——
    写成默认参数会在 import 时绑定，测试就没法替换它（会真的弹窗）。
    """
    chooser = picker or pick_folder_ex
    status, raw = chooser(t("download.folder.dialog_title"))
    if status == FOLDER_OK and raw:
        target = Path(raw)
        return target if _confirm_target(ctx, target, prep) else None
    if status == FOLDER_CANCELLED:
        return None
    if status != FOLDER_UNAVAILABLE:              # 防御：未知状态也当"没有对话框"
        ctx.console.line(t("menu.invalid_choice"))
    return _ask_target_manually(ctx, prep)


def ask_overwrite(ctx: AppContext, prep: DownloadPrep) -> dict[str, bool] | None:
    """逐个问同名文件怎么处理；返回 None 表示取消整个下载。

    返回的映射正是 download_all 认的 overwrite（键 = 目标文件名）。
    """
    console = ctx.console
    conflicts = prep.conflicts
    if not conflicts:
        return {}
    console.line(t("download.conflict.header", count=len(conflicts)))
    console.line(t("download.conflict.note"))
    decisions: dict[str, bool] = {}
    all_decision: bool | None = None
    for item in conflicts:
        key = overwrite_key(item)
        if all_decision is not None:              # a / k 之后不再问
            decisions[key] = all_decision
            continue
        answer = _ask_one_conflict(ctx, item)
        if answer == "q":
            return None
        if answer == "a":
            all_decision = True
        elif answer == "k":
            all_decision = False
        decisions[key] = answer in ("o", "a")
    return decisions


def confirm_start(ctx: AppContext, prep: DownloadPrep,
                  decisions: dict[str, bool]) -> bool:
    """开跑前的最后一道闸（PRD §14.4）。"""
    console = ctx.console
    overwrite = sum(1 for value in decisions.values() if value)
    skipped = sum(1 for value in decisions.values() if not value)
    console.line(t("download.confirm.title", count=prep.total - skipped))
    console.line(t("download.confirm.dir", dir=prep.target_dir))
    console.line(t("download.confirm.selection", overwrite=overwrite, skipped=skipped))
    return ctx.prompter.confirm(t("download.confirm.ask"), default=True)

def run_with_progress(ctx: AppContext, prep: DownloadPrep,
                      decisions: dict[str, bool]) -> DownloadOutcome:
    """带进度地跑完下载（Ctrl+C 会转成"取消"而不是 traceback）。

    ⚠️ 非 TTY 的"每完成一个文件一行"是按**完成顺序**打的，不是计划顺序：
    下载是 jobs=3 并发的，先派发不等于先下完（实测同一场景 200 次里
    "第二个文件先完成"出现 116 次）。文件名与 done 计数始终取自**同一个条目**，
    所以不会错位；但任何断言都不该假定文件之间的先后。
    """
    console = ctx.console
    total = prep.total
    # 渲染模式在这里**一次定型**：下面两个回调是在下载线程里被调用的，
    # 中途再去读 console.is_tty 的话，任何外部改动都会让"每完成一个文件一行"
    # 静默消失（这种幽灵问题排查代价极高）。一次下载只按一种模式渲染。
    tty = bool(console.is_tty)
    state: dict = {"done": 0, "bytes": {}, "last": 0.0, "rate_limited": False,
                   "planned": prep.total_bytes}
    rate_limited_before = int(getattr(ctx.client, "rate_limited", 0) or 0)
    started = time.monotonic()

    def on_progress(item: DownloadItem, done_bytes: int, _file_total: int) -> None:
        """TTY：单行原地刷新（按间隔节流）；非 TTY：一个字都不打。"""
        state["bytes"][str(item.target)] = int(done_bytes)
        if not tty:
            return
        now = time.monotonic()
        if now - state["last"] < PROGRESS_INTERVAL:
            return
        state["last"] = now
        console.progress(_progress_line(total, state, item.target.name, started))

    def on_item(item: DownloadItem, ok: bool) -> None:
        """每完成一个文件 +1；非 TTY 每完成一个打一行（PRD §14.4）。"""
        if not ok:
            return
        state["done"] = int(state["done"]) + 1
        state["bytes"][str(item.target)] = int(item.file.size or 0)
        if not tty:
            console.line(t("download.progress.plain", done=state["done"], total=total,
                           name=item.target.name, mb=format_mb(item.file.size)))

    event = threading.Event()
    box: dict = {}

    def worker() -> None:
        """下载跑在工作线程：主线程才能接住 Ctrl+C 并让流程自己清理 .part。"""
        try:
            box["outcome"] = run_download_flow(prep, ctx.client, overwrite=decisions,
                                               on_progress=on_progress, on_item=on_item,
                                               cancel=event)
        except BaseException as exc:               # noqa: BLE001 - 原样带回主线程
            box["error"] = exc

    thread = threading.Thread(target=worker, name="modcheck-download", daemon=True)
    thread.start()
    try:
        while thread.is_alive():
            thread.join(0.1)
            _maybe_show_rate_limit(ctx, state, rate_limited_before, tty)
    except KeyboardInterrupt:
        event.set()                                # 停止派发 + 清理 .part（流程负责）
        while thread.is_alive():
            thread.join(0.1)
        console.clear_progress()
        raise
    console.clear_progress()
    error = box.get("error")
    if error is not None:
        raise error                                # type: ignore[misc]
    return box["outcome"]                          # type: ignore[return-value]


def render_result(ctx: AppContext, outcome: DownloadOutcome) -> None:
    """结束语：取消用取消语，跑完用汇总屏（PRD §14.4 逐字）。"""
    console = ctx.console
    summary = outcome.summary
    if summary.cancelled:
        console.line(t("download.cancelled", done=summary.ok, dir=summary.target_dir))
        return
    # 汇总行的三个数必须能加得起来：outcome_total == ok + skipped_total + failed
    console.line(t("download.summary.line", count=summary.outcome_total, ok=summary.ok,
                   skipped=summary.skipped_total, failed=summary.failed,
                   seconds=int(summary.elapsed), mb=format_mb(summary.bytes_total)))
    if summary.ok:
        console.line(t("download.summary.ok", count=summary.ok, dir=summary.target_dir))
    for index, (name, reason_key) in enumerate(summary.skipped_rows):
        key = "download.summary.skipped" if index == 0 else "download.summary.skipped_more"
        console.line(t(key, count=summary.skipped_total, name=name, reason=t(reason_key)))
    rows = summary.failure_rows
    if rows:
        console.line(t("download.summary.failed", count=summary.failed))
        for name, reason_key, detail in rows:
            reason = t(reason_key, detail=detail or t("download.error.detail.unknown"))
            # 写不进去是确定性的：重试也救不回来，所以不说"已重试 N 次"
            # （PRD 的两条示例正是"校验失败说了重试次数、写不进去没说"）
            if reason_key == "download.error.write":
                console.line(t("download.summary.failed_item", name=name, reason=reason))
            else:
                console.line(t("download.summary.failed_item.retried", name=name,
                               reason=reason, retries=summary.retries))
    console.line(t("download.summary.hint"))
    if summary.extra_files:
        console.line(t("download.summary.extras", count=summary.extra_files))
    if summary.all_failed:
        console.line(t("download.summary.all_failed"))

def post_check_download(ctx: AppContext, report: Report) -> DownloadOutcome | None:
    """检查之后的整条下载路径（菜单 [5] 用它）；返回 None 表示用户取消。

    顺序完全按 PRD §14.4：询问 -> 选文件夹 -> 同名冲突 -> 开跑确认 -> 进度 -> 汇总；
    唯一的插入是"要不要连 🟠 仅存测试版一起下"（作者要求，默认否），它排在同名冲突之前，
    因为选品口径必须先于"有没有东西可下 / 同名冲突"确定。
    任何一个环节回退（b / q / 取消对话框）都只是"不做这件事"，不是错误。
    """
    console = ctx.console
    if report.interrupted:
        return None                                # 检查被中断：不拿半份报告去选品
    if not console.is_tty and not getattr(ctx.prompter, "injected", False):
        return None                                # 非交互：不提问（PRD §14.4 的非 TTY 行为）
    if not ask_download(ctx):
        return None
    # 下载口径在这里**一次定死**：下面的"有没有东西可下"、总大小、同名冲突全都由同一个
    # 计划算出。若等选完文件夹再问，🟠 只有测试版的清单会先被判成"没有东西可下"而直接返回，
    # 用户永远看不到这个开关。
    include_prerelease = ask_prerelease(ctx)
    prep = prepare_download(report, Path("."),
                            include_prerelease=include_prerelease)   # 先看"有没有东西可下"
    if not prep.has_work:
        for line in nothing_lines(report, prep):
            console.line(line)
        return None
    target = choose_target_dir(ctx, prep)
    if target is None:
        return None
    prep = prepare_download(report, target,
                            include_prerelease=include_prerelease)   # 重算路径与同名冲突
    decisions = ask_overwrite(ctx, prep)
    if decisions is None:
        return None
    if not confirm_start(ctx, prep, decisions):
        console.line(t("menu.check.aborted"))
        return None
    console.line()
    outcome = run_with_progress(ctx, prep, decisions)
    render_result(ctx, outcome)
    return outcome


# ---------------------------------------------------------------- 内部
def _progress_line(total: int, state: dict, name: str, started: float) -> str:
    """拼装单行进度（PRD §14.4）。"""
    done = int(state["done"])
    filled = int(done / total * BAR_WIDTH) if total else BAR_WIDTH
    downloaded = sum(int(value) for value in state["bytes"].values())
    return t("download.progress.line", total=total,
             bar="#" * filled + "-" * (BAR_WIDTH - filled), done=done, name=name,
             done_mb=format_mb(downloaded), total_mb=format_mb(state.get("planned", 0)),
             seconds=int(time.monotonic() - started))


def _maybe_show_rate_limit(ctx: AppContext, state: dict, before: int, tty: bool) -> None:
    """被限流时在进度行上说明一句（PRD §14.5 第 8 条；只提示一次）。"""
    if state["rate_limited"] or not tty:
        return
    if int(getattr(ctx.client, "rate_limited", 0) or 0) <= before:
        return
    state["rate_limited"] = True
    ctx.console.progress(t("download.progress.rate_limited"))


def _ask_one_conflict(ctx: AppContext, item: DownloadItem) -> str:
    """问一个同名文件：o / s / a / k / q；回车 = 跳过（绝不默认覆盖）。"""
    console, prompter = ctx.console, ctx.prompter
    size, stamp = _stat_of(item.target)
    console.line(t("download.conflict.title", name=Path(item.target).name))
    console.line(t("download.conflict.existing", size=format_mb(size), time=stamp))
    console.line(t("download.conflict.incoming", size=format_mb(item.file.size),
                   project=item.entry.best_name or item.entry.key,
                   version=item.version.version_number or item.version.name or ""))
    console.line(t("download.conflict.options"))
    while True:
        raw = prompter.ask(t("download.prompt")).lower()
        if raw in ("o", "s", "a", "k", "q"):
            return raw
        if not raw:
            return "s"                             # 默认跳过（危险操作默认答案永远是 No）
        console.line(t("menu.invalid_choice"))


def _stat_of(path: Path) -> tuple[int, str]:
    """已有文件的大小与修改时间；读不到时给空值（不抛异常打断询问）。"""
    try:
        info = Path(path).stat()
    except OSError:
        return 0, ""
    return int(info.st_size), time.strftime("%Y-%m-%d %H:%M", time.localtime(info.st_mtime))


def _ask_target_manually(ctx: AppContext, prep: DownloadPrep) -> Path | None:
    """手输目标文件夹（含 创建 / 可写 / 是文件 三种校验，PRD §14.4）。"""
    console, prompter = ctx.console, ctx.prompter
    console.line(t("download.folder.header"))
    console.line(t("download.folder.hint"))
    while True:
        kind, raw = read_line(prompter, t("download.folder.prompt"))
        if kind in (KIND_BACK, KIND_QUIT):
            return None
        if not raw:
            continue
        target = Path(raw).expanduser()
        check = check_target_dir(target, prep.total_bytes)
        if not check.ok:
            if check.problem_key != TARGET_MISSING:
                console.line(t(check.problem_key, path=target))
                continue
            if not prompter.confirm(t("download.folder.missing_ask"), default=True):
                continue
            if not ensure_target_dir(target):
                console.line(t("download.folder.create_failed", path=target))
                continue
        # 创建完重新检查一次（可能仍然不可写），顺便拿到空间与"像 mods 吗"
        check = check_target_dir(target, prep.total_bytes)
        if not check.ok:
            console.line(t(check.problem_key, path=target))
            continue
        if not _confirm_target(ctx, target, prep, check):
            continue
        return target


def _confirm_target(ctx: AppContext, target: Path, prep: DownloadPrep, check=None) -> bool:
    """目标文件夹的两个提醒：像 mods 文件夹（允许但要问）、剩余空间不够（可继续）。"""
    console, prompter = ctx.console, ctx.prompter
    if check is None:
        check = check_target_dir(target, prep.total_bytes)
    if not check.ok:
        console.line(t(check.problem_key, path=target))
        return False
    if check.looks_like_mods and not prompter.confirm(
            t("download.folder.looks_like_mods", path=target), default=False):
        return False
    if check.low_space and not prompter.confirm(
            t("download.folder.low_space", free=format_mb(check.free_bytes),
              needed=format_mb(check.needed_bytes)), default=False):
        return False
    return True


__all__ = ["BAR_WIDTH", "PROGRESS_INTERVAL", "ask_download", "ask_overwrite",
           "ask_prerelease", "choose_target_dir", "confirm_start", "download_nothing_line",
           "format_mb", "nothing_lines", "post_check_download", "render_result",
           "run_with_progress"]
