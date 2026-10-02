"""R3-B04 ~ R3-B09：菜单 [5] 的"问"与"画"（屏幕级，注入假输入 + 假 fetcher，不联网）。

这里断言的是用户看到什么、被问了什么、以及答案如何影响落盘；
下载本身的规则（选品/重试/取消清理）在 tests/test_flows_download.py 与
tests/test_downloader.py 里断言，不重复。
"""
from __future__ import annotations

import io
import shutil
import time
from pathlib import Path

import pytest

from fakes import FakeTransport
from modcheck.cli.context import AppContext
from modcheck.cli.folderpicker import (FOLDER_CANCELLED, FOLDER_OK, FOLDER_UNAVAILABLE)
from modcheck.cli.prompts import Prompter
from modcheck.cli import screens_download as screen
from modcheck.console import Console
from modcheck.core.models import FileInfo, Loader, ModEntry, ReasonCode, Settings, Status, VersionInfo
from modcheck.core.report import Report, ReportItem
from modcheck.errors import ProviderNetworkError, UserCancelled
from modcheck.flows.download_flow import prepare_download
from modcheck.providers.http import HttpConfig, HttpClient
from modcheck.providers.registry import ProviderRegistry


def feed(values: list[str], prompts: list[str] | None = None, echo=None):
    """注入输入序列；用完后返回空串（相当于一路回车）。

    echo：真实的 input() 会把提示语回显到终端，测试里的假输入不会 ——
    屏幕级断言（"用户看到什么"）必须把这步补上，否则断言的就是"没印出来的提示"。
    """
    queue = list(values)

    def _input(prompt: str = "") -> str:
        if prompts is not None:
            prompts.append(prompt)
        if echo is not None:
            echo.line(prompt)
        return queue.pop(0) if queue else ""

    return _input


class FakeClient:
    """假 fetcher：本地写文件；可选让某个文件失败。"""

    def __init__(self, payload: bytes = b"x" * 10, fail_names: tuple[str, ...] = ()) -> None:
        self.payload = payload
        self.fail_names = fail_names
        self.calls: list[str] = []
        self.rate_limited = 0

    def download(self, url: str, dest: Path, *, sha1: str | None = None,
                 on_chunk=None, timeout: float | None = None) -> int:
        self.calls.append(Path(dest).name)
        if Path(dest).name in self.fail_names:
            raise OSError(28, "disk full")
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(self.payload)
        if on_chunk is not None:
            on_chunk(len(self.payload))
        return len(self.payload)


def make_ctx(tmp_path: Path, values: list[str], *, client=None, tty: bool = True,
             prompts: list[str] | None = None) -> AppContext:
    """注入输入序列的上下文（默认 tty=True：走 TTY 进度分支）。"""
    def handler(method: str, url: str, data, index: int):
        raise ProviderNetworkError("offline")

    console = Console(stream=io.StringIO(), color="never", width=100)
    console.is_tty = tty
    if client is None:
        client = HttpClient(HttpConfig(rate_limit_per_min=100000),
                            transport=FakeTransport(handler))
    return AppContext(settings=Settings(), config_dir=tmp_path, console=console,
                      registry=ProviderRegistry(providers=[]), cache=None, client=client,
                      interactive=True,
                      prompter=Prompter(input_fn=feed(values, prompts, echo=console),
                                        out=console))


def out(ctx: AppContext) -> str:
    """取屏幕输出。"""
    return ctx.console.stream.getvalue()      # type: ignore[attr-defined]


def file_info(name: str, size: int = 100) -> FileInfo:
    """造一个文件条目。"""
    return FileInfo(filename=name, url="https://cdn.example/" + name, primary=True,
                    size=size, hashes={})


def version(name: str, files: tuple[FileInfo, ...],
            channel: str = "release") -> VersionInfo:
    """造一个版本条目。"""
    return VersionInfo(version_id="V1", version_number=name, name=name, project_id="p",
                       date_published="2026-09-18T00:00:00Z", version_type=channel,
                       game_versions=("26.3",), loaders=("fabric",), files=files)


def downloadable_report(*names: str) -> Report:
    """造一份全是 🟢 的报告。"""
    report = Report(mc_version="26.3", loader=Loader.FABRIC, profile_name="demo",
                    generated_at="2026-10-01T00:00:00+08:00")
    for name in names:
        entry = ModEntry(key=name, display_name=name.title(), mod_id=name,
                         sources={"modrinth": name})
        report.add(ReportItem(mod=entry, status=Status.READY, reason=ReasonCode.OK,
                              reason_key="reason.ok", hint_key="advice.ok",
                              latest_for_loader=version("26.3", (file_info(name + ".jar"),))))
    return report


def prerelease_item(name: str) -> ReportItem:
    """一条 🟠：该加载器的最新**正式版**（26.0）装不上，能用的只有测试版 26.4-beta.1。"""
    entry = ModEntry(key=name, display_name=name.title(), mod_id=name,
                     sources={"modrinth": name})
    return ReportItem(mod=entry, status=Status.PRERELEASE, reason=ReasonCode.PRERELEASE_ONLY,
                      reason_key="reason.prerelease_only", hint_key="advice.prerelease_only",
                      latest_for_loader=version("26.0", (file_info(name + "-26.0.jar"),)),
                      latest_any=version("26.4-beta.1",
                                         (file_info(name + "-26.4-beta.1.jar"),),
                                         channel="beta"))


def prerelease_report(*names: str) -> Report:
    """造一份全是 🟠 的报告。"""
    report = Report(mc_version="26.3", loader=Loader.FABRIC, profile_name="demo",
                    generated_at="2026-10-01T00:00:00+08:00")
    for name in names:
        report.add(prerelease_item(name))
    return report

# ---------------------------------------------------------------- 问：要不要下载
def test_ask_download_defaults_to_no_and_prints_notes(tmp_path: Path) -> None:
    """回车 = 不下载（默认 N），三条说明逐字出现在询问之前。"""
    ctx = make_ctx(tmp_path, [""])
    assert screen.ask_download(ctx) is False
    text = out(ctx)
    assert "是否下载可用的版本？(y/N) > " in text
    assert "    · 只会下载 🟢 就绪（最新版）和 🟡 需注意（可用的旧稳定版）的模组。" in text
    # 🟠 不再写「一律跳过」—— 紧接着会问「是否同时下载 🟠」，先说不下再问要不要下是自相矛盾的。
    # 这里断言新措辞，同时**顺带断言它不再出现旧说法**，避免以后被改回去。
    assert "    · 🔴 阻塞、⚪ 未判定、⚫ 已忽略 一律跳过；🟠 仅存测试版默认跳过" in text
    assert "🟠 仅存测试版、⚪ 未判定" not in text
    assert "    · 不会改动你当前的 mods 文件夹，只会向你选择的文件夹写入文件。" in text


def test_ask_download_yes(tmp_path: Path) -> None:
    """答 y 才继续。"""
    assert screen.ask_download(make_ctx(tmp_path, ["y"])) is True


def test_ask_prerelease_defaults_to_no(tmp_path: Path) -> None:
    """测试性模组询问：回车 = 不下载（默认 N），询问前写明后果与备份提醒。"""
    ctx = make_ctx(tmp_path, [""])
    assert screen.ask_prerelease(ctx) is False
    text = out(ctx)
    assert "    · 🟠 仅存测试版只有测试版（beta/alpha）可用，稳定性没有保证；确认后才会一并下载，请先备份存档。" in text
    assert "是否同时下载 🟠 仅存测试版的模组？(y/N) > " in text


def test_ask_prerelease_yes(tmp_path: Path) -> None:
    """答 y 才算显式要求。"""
    assert screen.ask_prerelease(make_ctx(tmp_path, ["y"])) is True


def test_download_nothing_line_uses_group_counts(tmp_path: Path) -> None:
    """一个都没得下时给出各组计数（🟡/🟢 恒为 0）。"""
    report = Report(mc_version="26.3", loader=Loader.FABRIC, profile_name="demo",
                    generated_at="")
    for index, status in enumerate((Status.BLOCKED, Status.PRERELEASE, Status.UNKNOWN)):
        report.add(ReportItem(mod=ModEntry(key="m%d" % index, display_name="M%d" % index),
                              status=status, reason=ReasonCode.OK, reason_key="r",
                              hint_key="h"))
    assert screen.download_nothing_line(report) == (
        "没有需要下载的模组：这次检查里没有 🟢 就绪 或 🟡 需注意 的条目"
        "（🔴 1 ｜ 🟠 1 ｜ 🟡 0 ｜ ⚪ 1 ｜ 🟢 0）。")


def test_format_mb() -> None:
    """MB 文本一位小数（拿不到大小也不显示 None）。"""
    assert screen.format_mb(1024 * 1024) == "1.0"
    assert screen.format_mb(0) == "0.0"
    assert screen.format_mb(None) == "0.0"


# ---------------------------------------------------------------- 问：目标文件夹
def test_choose_target_dir_uses_dialog(tmp_path: Path, monkeypatch) -> None:
    """对话框拿到路径就直接用（不再问一遍）。"""
    target = tmp_path / "dl"
    target.mkdir()
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_OK, str(target)))
    ctx = make_ctx(tmp_path, [])
    prep = prepare_download(downloadable_report("carpet"), target)
    assert screen.choose_target_dir(ctx, prep) == target
    assert "请选择下载到哪个文件夹。" not in out(ctx)


def test_choose_target_dir_cancelled_dialog_is_cancel_not_error(tmp_path: Path,
                                                                monkeypatch) -> None:
    """用户取消对话框 = 取消下载（PRD §14.4），不进入手输、也不报错。"""
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_CANCELLED, None))
    ctx = make_ctx(tmp_path, [])
    prep = prepare_download(downloadable_report("carpet"), tmp_path)
    assert screen.choose_target_dir(ctx, prep) is None
    assert "下载目标：[b] 取消下载 > " not in out(ctx)


def test_choose_target_dir_falls_back_to_manual_input(tmp_path: Path, monkeypatch) -> None:
    """没有对话框（非 Windows / COM 不可用）就手输；不存在的目录先问要不要建。"""
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_UNAVAILABLE, None))
    target = tmp_path / "brand-new"
    ctx = make_ctx(tmp_path, [str(target), "y"])
    prep = prepare_download(downloadable_report("carpet"), tmp_path)
    assert screen.choose_target_dir(ctx, prep) == target
    assert target.is_dir()
    text = out(ctx)
    assert "请选择下载到哪个文件夹。" in text
    assert "建议新建一个空文件夹，不要直接选择正在使用的 mods 文件夹。" in text
    assert "该文件夹不存在。是否现在创建？(Y/n) > " in text


def test_manual_missing_dir_declined_then_back(tmp_path: Path, monkeypatch) -> None:
    """答 n 就不创建，再按 b 返回（取消下载）。"""
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_UNAVAILABLE, None))
    target = tmp_path / "nope"
    ctx = make_ctx(tmp_path, [str(target), "n", "b"])
    prep = prepare_download(downloadable_report("carpet"), tmp_path)
    assert screen.choose_target_dir(ctx, prep) is None
    assert not target.exists()


def test_manual_path_is_a_file(tmp_path: Path, monkeypatch) -> None:
    """目标是一个文件不是文件夹：✗ 文案，然后重新问。"""
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_UNAVAILABLE, None))
    target = tmp_path / "afile"
    target.write_bytes(b"x")
    ctx = make_ctx(tmp_path, [str(target), "b"])
    prep = prepare_download(downloadable_report("carpet"), tmp_path)
    assert screen.choose_target_dir(ctx, prep) is None
    assert "是一个文件，不是文件夹。" in out(ctx)


def test_manual_path_not_writable(tmp_path: Path, monkeypatch) -> None:
    """无法写入：✗ 文案，让用户换一个。"""
    import tempfile as tempfile_module

    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_UNAVAILABLE, None))
    monkeypatch.setattr(tempfile_module, "mkstemp",
                        lambda *a, **k: (_ for _ in ()).throw(OSError(13, "denied")))
    target = tmp_path / "ro"
    target.mkdir()
    ctx = make_ctx(tmp_path, [str(target), "b"])
    prep = prepare_download(downloadable_report("carpet"), tmp_path)
    assert screen.choose_target_dir(ctx, prep) is None
    assert "✗ 该文件夹无法写入（没有权限）。请更换文件夹。" in out(ctx)


def test_manual_mods_folder_asks_once(tmp_path: Path, monkeypatch) -> None:
    """选到 mods 文件夹：允许，但要先提醒一次（PRD §14.5 第 14 条）。"""
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_UNAVAILABLE, None))
    mods = tmp_path / "mods"
    mods.mkdir()
    prep = prepare_download(downloadable_report("carpet"), tmp_path)
    declined = make_ctx(tmp_path, [str(mods), "n", "b"])
    assert screen.choose_target_dir(declined, prep) is None
    assert "看起来像正在使用的 mods 文件夹" in out(declined)
    accepted = make_ctx(tmp_path, [str(mods), "y"])
    assert screen.choose_target_dir(accepted, prep) == mods


# ---------------------------------------------------------------- 问：同名文件
def conflict_prep(tmp_path: Path, *names: str):
    """造一个"目标目录里已有同名文件"的计划。"""
    for name in names:
        (tmp_path / (name + ".jar")).write_bytes(b"old-file")
    return prepare_download(downloadable_report(*names), tmp_path)


def test_ask_overwrite_enter_means_skip(tmp_path: Path) -> None:
    """回车 = 跳过（绝不默认覆盖），并且先给出总数与默认值提示。"""
    prep = conflict_prep(tmp_path, "a", "b")
    ctx = make_ctx(tmp_path, ["", ""])
    assert screen.ask_overwrite(ctx, prep) == {"a.jar": False, "b.jar": False}
    text = out(ctx)
    assert "开始前先确认：目标文件夹里已经有 2 个同名文件。" in text
    assert "ℹ 默认为「跳过」，不会覆盖已有的文件。" in text
    assert "   [o] 覆盖它  [s] 跳过这个  [a] 后面的全部覆盖  [k] 后面的全部跳过  [q] 取消下载" in text


def test_ask_overwrite_all_overwrite(tmp_path: Path) -> None:
    """a 之后不再问（三个冲突只问一次）。"""
    prep = conflict_prep(tmp_path, "a", "b", "c")
    ctx = make_ctx(tmp_path, ["a"])
    assert screen.ask_overwrite(ctx, prep) == {"a.jar": True, "b.jar": True, "c.jar": True}
    assert out(ctx).count("⚠ 已存在同名文件：") == 1


def test_ask_overwrite_all_skip(tmp_path: Path) -> None:
    """k 之后不再问，全部跳过。"""
    prep = conflict_prep(tmp_path, "a", "b", "c")
    ctx = make_ctx(tmp_path, ["k"])
    assert screen.ask_overwrite(ctx, prep) == {"a.jar": False, "b.jar": False, "c.jar": False}
    assert out(ctx).count("⚠ 已存在同名文件：") == 1


def test_ask_overwrite_per_file(tmp_path: Path) -> None:
    """o / s 混着选：每个文件各自决定。"""
    prep = conflict_prep(tmp_path, "a", "b")
    ctx = make_ctx(tmp_path, ["o", "s"])
    assert screen.ask_overwrite(ctx, prep) == {"a.jar": True, "b.jar": False}


def test_ask_overwrite_quit_cancels_whole_download(tmp_path: Path) -> None:
    """q = 取消整个下载（返回 None，调用方据此一个都不下）。"""
    prep = conflict_prep(tmp_path, "a")
    ctx = make_ctx(tmp_path, ["q"])
    assert screen.ask_overwrite(ctx, prep) is None


def test_ask_overwrite_shows_sizes_and_source(tmp_path: Path) -> None:
    """冲突屏要有"现在这个 / 将要下载"两行（含来源与版本）。"""
    (tmp_path / "a.jar").write_bytes(b"x" * (2 * 1024 * 1024))
    prep = prepare_download(downloadable_report("a"), tmp_path)
    ctx = make_ctx(tmp_path, ["s"])
    screen.ask_overwrite(ctx, prep)
    text = out(ctx)
    assert "⚠ 已存在同名文件：a.jar" in text
    assert "   现在这个：2.0 MB，修改于 " in text
    assert "   将要下载：0.0 MB，来自 Modrinth（A 26.3）" in text


def test_ask_overwrite_without_conflicts(tmp_path: Path) -> None:
    """没有同名文件：不问、返回空映射。"""
    prep = prepare_download(downloadable_report("a"), tmp_path)
    ctx = make_ctx(tmp_path, [])
    assert screen.ask_overwrite(ctx, prep) == {}
    assert out(ctx) == ""


# ---------------------------------------------------------------- 开跑确认
def test_confirm_start_counts_and_default(tmp_path: Path) -> None:
    """确认屏：总数减掉跳过的，回默认 Y。"""
    prep = conflict_prep(tmp_path, "a")
    ctx = make_ctx(tmp_path, [""])
    assert screen.confirm_start(ctx, prep, {"a.jar": False}) is True
    text = out(ctx)
    assert "即将下载 0 个文件到：" in text
    assert "   " + str(tmp_path) in text
    assert "（已选：覆盖 0 个 ｜ 跳过 1 个）" in text
    assert "开始下载？(Y/n) > " in text
# ---------------------------------------------------------------- 下载 + 汇总（整条路径）
def progress_rows(text: str) -> list[tuple[str, str, str]]:
    """从屏幕输出里取出"已下载 done/total：文件名（… MB）"行 -> (done, total, 文件名)。

    注意：**不要**假定行与行之间的先后 —— 下载是并发的，完成顺序不确定（见下面的回归用例）。
    """
    rows: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        if not line.startswith("已下载 "):
            continue
        head, _sep, rest = line.partition("：")
        done, _slash, total = head.split(" ")[1].partition("/")
        rows.append((done, total, rest.split("（")[0]))
    return rows


class SlowFirstClient(FakeClient):
    """让指定文件慢一点，把"谁先下完"钉死（并发下完成顺序本来是不确定的）。"""

    def __init__(self, slow_names: tuple[str, ...], **kw) -> None:
        super().__init__(**kw)
        self.slow_names = slow_names

    def download(self, url: str, dest: Path, *, sha1: str | None = None,
                 on_chunk=None, timeout: float | None = None) -> int:
        if Path(dest).name in self.slow_names:
            time.sleep(0.2)
        return super().download(url, dest, sha1=sha1, on_chunk=on_chunk, timeout=timeout)


def test_post_check_download_full_path(tmp_path: Path, monkeypatch) -> None:
    """整条路径：询问 -> 对话框选目录 -> 开跑确认 -> 下载 -> 汇总（非 TTY 每完成一个一行）。

    ⚠️ 只断言"两行都在、done 是 1 与 2"，**不断言谁先谁后**：
    jobs=3 是并发的，先派发不等于先下完（写死顺序的断言实测约 58% 概率红）。
    """
    target = tmp_path / "dl"
    target.mkdir()
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_OK, str(target)))
    client = FakeClient(payload=b"y" * 2048)
    # y=要下载, 回车=不含测试性模组（默认）, y=开跑
    ctx = make_ctx(tmp_path, ["y", "", "y"], client=client, tty=False)
    outcome = screen.post_check_download(ctx, downloadable_report("carpet", "lithium"))
    assert outcome is not None and outcome.summary.ok == 2
    assert (target / "carpet.jar").read_bytes() == b"y" * 2048
    text = out(ctx)
    rows = progress_rows(text)
    assert len(rows) == 2
    assert {name for _done, _total, name in rows} == {"carpet.jar", "lithium.jar"}
    assert {done for done, _total, _name in rows} == {"1", "2"}      # done 不重号、不漏号
    assert {total for _done, total, _name in rows} == {"2"}
    assert all("（0.0 MB）" in line for line in text.splitlines() if line.startswith("已下载 "))
    assert "下载完成：2 个文件里 2 个成功、0 个跳过、0 个失败。" in text
    assert "  ✓ 成功 2 个 → " + str(target) in text
    assert "提示：将下载好的 .jar 复制到服务端的 mods 文件夹，然后重启服务器。" in text


def test_post_check_download_prerelease_is_off_by_default(tmp_path: Path,
                                                          monkeypatch) -> None:
    """默认（回车）：同一份报告里只下 🟢，🟠 一个文件都不下。"""
    target = tmp_path / "dl"
    target.mkdir()
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_OK, str(target)))
    report = downloadable_report("carpet")
    report.add(prerelease_item("jei"))
    client = FakeClient()
    ctx = make_ctx(tmp_path, ["y", "", "y"], client=client, tty=False)
    outcome = screen.post_check_download(ctx, report)
    assert outcome is not None and outcome.summary.ok == 1
    assert client.calls == ["carpet.jar"]
    assert [path.name for path in target.iterdir()] == ["carpet.jar"]
    assert "下载完成：1 个文件里 1 个成功、0 个跳过、0 个失败。" in out(ctx)


def test_post_check_download_prerelease_opt_in_downloads_beta(tmp_path: Path,
                                                              monkeypatch) -> None:
    """答 y：🟠 的测试版一起下，且取的是能装上的那个测试版（不是装不上的正式版）。"""
    target = tmp_path / "dl"
    target.mkdir()
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_OK, str(target)))
    report = downloadable_report("carpet")
    report.add(prerelease_item("jei"))
    client = FakeClient()
    ctx = make_ctx(tmp_path, ["y", "y", "y"], client=client, tty=False)
    outcome = screen.post_check_download(ctx, report)
    assert outcome is not None and outcome.summary.ok == 2
    assert sorted(client.calls) == ["carpet.jar", "jei-26.4-beta.1.jar"]
    assert (target / "jei-26.4-beta.1.jar").exists()
    assert not (target / "jei-26.0.jar").exists()        # 装不上的正式版绝不能下
    text = out(ctx)
    assert "是否同时下载 🟠 仅存测试版的模组？(y/N) > " in text
    assert "下载完成：2 个文件里 2 个成功、0 个跳过、0 个失败。" in text


def test_progress_lines_follow_completion_order(tmp_path: Path, monkeypatch) -> None:
    """回归（"单独跑绿、一起跑红"）：非 TTY 的每文件行按**完成顺序**打。

    把第二个文件变快、完成顺序钉死；任何"按计划顺序"的断言都会在这里红 ——
    那正是旧用例约 58% 概率失败的原因（实测 200 次：lithium 先完成 116 次）。
    它同时守住"文件名与 done 计数取自同一条目"，不会张冠李戴。
    """
    target = tmp_path / "dl"
    target.mkdir()
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_OK, str(target)))
    ctx = make_ctx(tmp_path, ["y", "", "y"],
                   client=SlowFirstClient(("carpet.jar",)), tty=False)
    outcome = screen.post_check_download(ctx, downloadable_report("carpet", "lithium"))
    assert outcome is not None and outcome.summary.ok == 2
    assert progress_rows(out(ctx)) == [("1", "2", "lithium.jar"), ("2", "2", "carpet.jar")]


def test_post_check_download_ttyshows_single_progress_line(tmp_path: Path,
                                                           monkeypatch) -> None:
    """TTY：进度行走单行原地刷新（不每块一行）。"""
    target = tmp_path / "dl"
    target.mkdir()
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_OK, str(target)))
    ctx = make_ctx(tmp_path, ["y", "", "y"], client=FakeClient(), tty=True)
    screen.post_check_download(ctx, downloadable_report("carpet"))
    text = out(ctx)
    assert "正在下载 1 个文件……" in text
    assert "当前：carpet.jar" in text and "已用 " in text
    assert "已下载 1/1：" not in text          # 非 TTY 的那行不该出现


def test_post_check_download_summary_of_failure(tmp_path: Path, monkeypatch) -> None:
    """失败清单写明原因；"无法写入"不说"已重试 N 次"（PRD 的两条示例）。"""
    target = tmp_path / "dl"
    target.mkdir()
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_OK, str(target)))
    ctx = make_ctx(tmp_path, ["y", "", "y"], client=FakeClient(fail_names=("carpet.jar",)),
                   tty=False)
    outcome = screen.post_check_download(ctx, downloadable_report("carpet", "lithium"))
    assert outcome is not None and outcome.summary.failed == 1
    text = out(ctx)
    assert "下载完成：2 个文件里 1 个成功、0 个跳过、1 个失败。" in text
    assert "  ✗ 失败 1 个：" in text
    assert "      carpet.jar —— 无法写入（磁盘空间不足或没有权限）" in text
    assert "已重试" not in text


def test_post_check_download_skipped_files_are_listed(tmp_path: Path, monkeypatch) -> None:
    """同名文件选跳过：汇总里列出来，且不再问第二次。"""
    target = tmp_path / "dl"
    target.mkdir()
    (target / "carpet.jar").write_bytes(b"old")
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_OK, str(target)))
    client = FakeClient()
    ctx = make_ctx(tmp_path, ["y", "", "s", "y"], client=client, tty=False)
    outcome = screen.post_check_download(ctx, downloadable_report("carpet"))
    assert outcome is not None and outcome.summary.skipped == 1
    assert client.calls == []                     # 一个请求都没发
    assert (target / "carpet.jar").read_bytes() == b"old"
    text = out(ctx)
    assert "  ⏭ 跳过 1 个：carpet.jar（已选择跳过）" in text


def test_post_check_download_user_declines(tmp_path: Path) -> None:
    """答 N：什么都不做，也不问文件夹。"""
    ctx = make_ctx(tmp_path, [""])
    assert screen.post_check_download(ctx, downloadable_report("carpet")) is None
    assert "下载目标" not in out(ctx)


def test_post_check_download_nothing_to_download(tmp_path: Path) -> None:
    """没有可下载的条目：直接给结论，不弹文件夹选择（PRD §14.5 第 12 条）。"""
    ctx = make_ctx(tmp_path, ["y", ""])
    assert screen.post_check_download(ctx, downloadable_report()) is None
    assert "没有需要下载的模组" in out(ctx)
    assert "下载目标" not in out(ctx)


def test_post_check_download_interrupted_report_is_ignored(tmp_path: Path) -> None:
    """检查被中断：不拿半份报告去选品，也不问下载。"""
    report = downloadable_report("carpet")
    report.interrupted = True
    ctx = make_ctx(tmp_path, ["y"])
    assert screen.post_check_download(ctx, report) is None
    assert "是否下载可用的版本" not in out(ctx)


def test_post_check_download_conflict_quit_cancels(tmp_path: Path, monkeypatch) -> None:
    """冲突屏选 q：一个都不下、目录无变化。"""
    target = tmp_path / "dl"
    target.mkdir()
    (target / "carpet.jar").write_bytes(b"old")
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_OK, str(target)))
    client = FakeClient()
    ctx = make_ctx(tmp_path, ["y", "", "q"], client=client, tty=False)
    assert screen.post_check_download(ctx, downloadable_report("carpet")) is None
    assert client.calls == []
    assert (target / "carpet.jar").read_bytes() == b"old"


def test_post_check_download_non_interactive_does_nothing(tmp_path: Path) -> None:
    """非 TTY 且没注入输入：一个字都不问（管道/重定向里不会挂死）。"""
    ctx = make_ctx(tmp_path, ["y"], tty=False)
    ctx.prompter.injected = False
    assert screen.post_check_download(ctx, downloadable_report("carpet")) is None
    assert out(ctx) == ""


# ---------------------------------------------------------------- 取消 / 汇总渲染
def cancelled_outcome(prep, ok: int = 1):
    """造一个"被取消"的结果。"""
    from modcheck.core.downloader import DownloadReport
    from modcheck.flows.download_flow import DownloadOutcome, DownloadSummary

    report = DownloadReport(items=(), ok=ok, skipped=0, failed=0, bytes_total=1024,
                            elapsed=1.5, cancelled=True)
    summary = DownloadSummary(target_dir=prep.target_dir, total=2, ok=ok, skipped=0,
                              failed=0, bytes_total=1024, elapsed=1.5, cancelled=True,
                              extra_files=0)
    return DownloadOutcome(prep=prep, report=report, summary=summary)


def test_render_result_cancelled(tmp_path: Path) -> None:
    """取消语逐字（含"已下载完成的 N 个文件保留在…"）。"""
    prep = prepare_download(downloadable_report("carpet"), tmp_path)
    ctx = make_ctx(tmp_path, [])
    screen.render_result(ctx, cancelled_outcome(prep, ok=1))
    assert ("已取消下载。已下载完成的 1 个文件保留在 " + str(tmp_path)
            + " 中，未完成的临时文件已清理。") in out(ctx)


def test_render_result_extras_line(tmp_path: Path) -> None:
    """附加文件提示行只在 k>0 时出现（PRD §14.4）。"""
    from modcheck.core.downloader import DownloadReport
    from modcheck.flows.download_flow import DownloadOutcome, DownloadSummary

    prep = prepare_download(downloadable_report("carpet"), tmp_path)
    summary = DownloadSummary(target_dir=tmp_path, total=1, ok=1, skipped=0, failed=0,
                              bytes_total=10, elapsed=1.0, cancelled=False, extra_files=0)
    report = DownloadReport(items=(), ok=1, skipped=0, failed=0, bytes_total=10,
                            elapsed=1.0, cancelled=False)
    ctx = make_ctx(tmp_path, [])
    screen.render_result(ctx, DownloadOutcome(prep=prep, report=report, summary=summary))
    assert "ℹ 有 " not in out(ctx)

    summary2 = DownloadSummary(target_dir=tmp_path, total=1, ok=1, skipped=0, failed=0,
                               bytes_total=10, elapsed=1.0, cancelled=False, extra_files=3)
    ctx2 = make_ctx(tmp_path, [])
    screen.render_result(ctx2, DownloadOutcome(prep=prep, report=report, summary=summary2))
    assert ("ℹ 有 3 个模组除了主文件还有附加文件（源码/文档），本次只下载了主文件。"
            in out(ctx2))


def test_render_result_all_failed_hint(tmp_path: Path) -> None:
    """一个都没成功：追加代理提示那句。"""
    from dataclasses import replace

    from modcheck.core.downloader import DownloadReport
    from modcheck.flows.download_flow import DownloadOutcome, DownloadSummary

    prep = prepare_download(downloadable_report("carpet"), tmp_path)
    failed_item = replace(prep.items[0], status="failed", message_key="download.error.net",
                          detail="连接超时")
    summary = DownloadSummary(target_dir=tmp_path, total=1, ok=0, skipped=0, failed=1,
                              bytes_total=0, elapsed=1.0, cancelled=False, extra_files=0,
                              retries=2, failed_items=(failed_item,))
    report = DownloadReport(items=(failed_item,), ok=0, skipped=0, failed=1, bytes_total=0,
                            elapsed=1.0, cancelled=False)
    ctx = make_ctx(tmp_path, [])
    screen.render_result(ctx, DownloadOutcome(prep=prep, report=report, summary=summary))
    text = out(ctx)
    assert "      carpet.jar —— 下载失败（连接超时），已重试 2 次" in text
    assert "{detail}" not in text                  # 未填的占位符绝不能漏到用户面前
    assert "✗ 全部下载失败。可稍后重试；若为网络问题，请先检查代理设置：" in text
# ---------------------------------------------------------------- 数字自洽（主 Agent 裁决 4）
def sources_only_report(name: str = "jei") -> Report:
    """一个 🟢 模组，但它的版本里只有 sources.jar（没有可下载的主文件）。"""
    report = Report(mc_version="26.3", loader=Loader.FABRIC, profile_name="demo",
                    generated_at="")
    entry = ModEntry(key=name, display_name=name.title(), mod_id=name,
                     sources={"modrinth": name})
    addon = FileInfo(filename=name + "-26.3-sources.jar", url="https://cdn.example/x",
                     primary=True, size=100, hashes={})
    report.add(ReportItem(mod=entry, status=Status.READY, reason=ReasonCode.OK,
                          reason_key="reason.ok", hint_key="advice.ok",
                          latest_for_loader=version("26.3", (addon,))))
    return report


def test_nothing_lines_keep_prd_wording_when_truly_nothing(tmp_path: Path) -> None:
    """检查结果里本来就没有 🟢/🟡 -> PRD 那句逐字，且句句属实。"""
    report = Report(mc_version="26.3", loader=Loader.FABRIC, profile_name="demo",
                    generated_at="")
    report.add(ReportItem(mod=ModEntry(key="c", display_name="C"), status=Status.BLOCKED,
                          reason=ReasonCode.OK, reason_key="r", hint_key="h"))
    prep = prepare_download(report, tmp_path)
    assert screen.nothing_lines(report, prep) == [
        "没有需要下载的模组：这次检查里没有 🟢 就绪 或 🟡 需注意 的条目"
        "（🔴 1 ｜ 🟠 0 ｜ 🟡 0 ｜ ⚪ 0 ｜ 🟢 0）。"]


def test_nothing_lines_list_reasons_when_mods_exist(tmp_path: Path) -> None:
    """有 🟢 但不能下：不能再说"没有 🟢 就绪 的条目（🟢 0）"—— 那是假话。"""
    report = sources_only_report("jei")
    prep = prepare_download(report, tmp_path)
    lines = screen.nothing_lines(report, prep)
    assert lines[0] == ("没有可以下载的文件：🟢 就绪 / 🟡 需注意 的条目里没有可下载的主文件"
                        "（.jar）。")
    assert lines[1] == "  Jei：这个版本没有可下载的 .jar 文件"   # 显示名（条目没有 file_name）
    assert all("🟢 0" not in line for line in lines)


def test_post_check_download_nothing_screen_is_honest(tmp_path: Path) -> None:
    """菜单路径：这个场景打印的是原因清单，不是那句"没有 🟢 就绪"的话。"""
    ctx = make_ctx(tmp_path, ["y", ""])
    assert screen.post_check_download(ctx, sources_only_report("jei")) is None
    text = out(ctx)
    assert "  Jei：这个版本没有可下载的 .jar 文件" in text
    assert "没有需要下载的模组" not in text


def test_summary_numbers_add_up_on_screen(tmp_path: Path, monkeypatch) -> None:
    """跳一个、失败一个、成功一个：汇总行的三个数与下面的清单必须对得上。"""
    target = tmp_path / "dl"
    target.mkdir()
    (target / "carpet.jar").write_bytes(b"old")
    monkeypatch.setattr(screen, "pick_folder_ex", lambda title: (FOLDER_OK, str(target)))
    client = FakeClient(fail_names=("sodium.jar",))
    # y=要下载, 回车=不含测试性模组（默认）, s=跳过同名文件, y=开跑
    ctx = make_ctx(tmp_path, ["y", "", "s", "y"], client=client, tty=False)
    outcome = screen.post_check_download(ctx, downloadable_report("carpet", "sodium", "lithium"))
    assert outcome is not None
    summary = outcome.summary
    assert summary.outcome_total == (summary.ok + summary.skipped_total + summary.failed)
    text = out(ctx)
    assert "下载完成：3 个文件里 1 个成功、1 个跳过、1 个失败。" in text
    assert "  ⏭ 跳过 1 个：carpet.jar（已选择跳过）" in text
    assert "  ✗ 失败 1 个：" in text
    assert text.count(" —— ") == 1                # 失败清单只有一条



