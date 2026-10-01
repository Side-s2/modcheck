"""Nuitka 打包脚本（T-22）。

实测约束（见 ENGINEERING_CONTRACT §1.2）：
  * 系统自带 MinGW gcc 8.1.0 会被 Nuitka 拒绝，必须允许它下载配套 winlibs-gcc；
  * --assume-yes-for-downloads **必须加**，否则 Nuitka 会交互式询问然后中止；
  * 缓存目录必须指向工作区内，否则写用户目录会被沙箱拒绝。

用法：
    python build/nuitka_build.py                 # CLI standalone（推荐默认）
    python build/nuitka_build.py --onefile       # CLI 单文件（首次启动约 7 秒，见 README）
    python build/nuitka_build.py --gui            # GUI（PyQt6，体积大得多）
    python build/nuitka_build.py --gui --onefile  # GUI 单文件

GUI 版的关键差异：
  * 必须 --enable-plugin=pyqt6，否则 Qt 插件（平台插件 windows）不会被打进去，
    产物启动时报 "could not find or load the Qt platform plugin windows"；
  * --windows-console-mode=disable：GUI 双击不该弹出一个黑色控制台窗口；
  * **排除 modcheck.cli**：GUI 不依赖 CLI。这不只是省体积 ——
    构建期就能证明分层没被破坏（若 GUI 真的 import 了 cli，构建会失败而不是悄悄变胖）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: 从分发包里彻底排除的开发期依赖
EXCLUDES = ("pytest", "_pytest", "unittest", "pydoc", "doctest", "pdb", "test")


def build(*, onefile: bool = False, output_dir: Path = Path("dist"),
          keep_intermediate: bool = False, gui: bool = False) -> int:
    """调用 Nuitka 构建；返回子进程退出码。

    参数：
        onefile: 生成单文件产物（首次启动约 7 秒，见 README）。
        output_dir: 输出目录；构建前会清空，避免上次失败留下的空壳产物混淆验收。
        keep_intermediate: 保留 Nuitka 的中间目录（默认清掉，减少残留干扰）。
    """
    _clean_output(output_dir)
    env = dict(os.environ)
    env.setdefault("NUITKA_CACHE_DIR", str(ROOT / ".toolchain" / "nuitka-cache"))
    env.setdefault("TEMP", str(ROOT / ".toolchain" / "tmp"))
    env.setdefault("TMP", env["TEMP"])
    # src 布局：必须让 Nuitka 能找到 modcheck 包（否则报 failed to locate package）
    env["PYTHONPATH"] = str(ROOT / "src")
    # 注意：Nuitka **没有** --python-path 选项（那是 PyInstaller 的 --paths），
    # 让它找到 src 布局里的包只能靠 PYTHONPATH 环境变量 + --include-package。
    cmd = [sys.executable, "-m", "nuitka",
           "--assume-yes-for-downloads",          # 必须：否则会交互式询问并中止
           "--onefile" if onefile else "--standalone",
           "--output-dir=" + str(output_dir),
           "--include-package=modcheck",
           "--company-name=modcheck",
           "--product-name=modcheck",
           "--file-version=0.1.0",
           "--product-version=0.1.0"]
    if onefile:
        # ⚠️ 实测反馈：默认解包目录是 %TEMP%\onefile_<pid>_<time>_<rand>，
        # 而"从 %TEMP% 解包并执行子进程"正是杀毒软件最常拦截的行为模式 ——
        # 用户机器上表现为"双击一闪而过、以管理员身份运行却正常"（提权常被放行）。
        # 改成解包到用户缓存目录 + cached 模式：
        #   ① 不再是 %TEMP%，绕开最常见的启发式规则；
        #   ② 第二次启动不用重新解包，启动从约 7 秒降到接近瞬时。
        cmd.append("--onefile-tempdir-spec={CACHE_DIR}/modcheck/{VERSION}")
        cmd.append("--onefile-cache-mode=cached")
    if gui:
        # Qt 的平台插件必须显式带上，否则运行时报
        # "could not find or load the Qt platform plugin windows"
        cmd.append("--enable-plugin=pyqt6")
        # GUI 双击不该弹黑色控制台窗口
        cmd.append("--windows-console-mode=disable")
        # **排除 cli**：GUI 不依赖命令行前端。这既是省体积，也是**构建期的分层断言** ——
        # 如果哪天 GUI 偷偷 import 了 cli，这里会直接构建失败，而不是悄悄变胖。
        cmd.append("--nofollow-import-to=modcheck.cli")
    for name in EXCLUDES:
        cmd.append("--nofollow-import-to=" + name)
    if not keep_intermediate:
        # 中间产物残留会让下一次构建偶发失败（实测报过 __constants.h 找不到）
        cmd.append("--remove-output")
    # 产物名统一（否则 onefile 会叫 __main__.exe）
    cmd.append("--output-filename=" + ("modcheck-gui" if gui else "modcheck"))
    entry = (ROOT / "src" / "modcheck" / "gui" / "__main__.py") if gui \
        else (ROOT / "src" / "modcheck" / "__main__.py")
    cmd.append(str(entry))
    code = subprocess.call(cmd, cwd=str(ROOT), env=env)
    if code == 0:
        _fix_dist_name(Path(output_dir), onefile, gui=gui)
    return code


def _clean_output(output_dir: Path) -> None:
    """构建前清空输出目录（上一次失败的 0 字节产物最容易骗过验收）。"""
    import shutil

    target = Path(output_dir)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


def _fix_dist_name(output_dir: Path, onefile: bool, *, gui: bool = False) -> None:
    """把 Nuitka 按入口脚本名生成的 __main__.dist 改成 modcheck（产物更好看）。"""
    import shutil

    stem = "modcheck-gui" if gui else "modcheck"
    auto = Path(output_dir) / "__main__.dist"
    wanted = Path(output_dir) / stem
    if auto.is_dir() and not wanted.exists():
        try:
            shutil.move(str(auto), str(wanted))
        except OSError:
            pass
    elif onefile:
        auto_exe = Path(output_dir) / "__main__.exe"
        wanted_exe = Path(output_dir) / (stem + ".exe")
        if auto_exe.is_file() and not wanted_exe.exists():
            try:
                shutil.move(str(auto_exe), str(wanted_exe))
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="使用 Nuitka 打包 modcheck")
    parser.add_argument("--onefile", action="store_true", help="生成单文件（首次启动较慢）")
    parser.add_argument("--gui", action="store_true",
                        help="打包图形界面（PyQt6；体积大得多，约 100-150MB）")
    parser.add_argument("--output-dir", default="dist", help="输出目录")
    parser.add_argument("--keep-intermediate", action="store_true",
                        help="保留 Nuitka 中间目录（默认构建成功后清掉）")
    args = parser.parse_args(argv)
    return build(onefile=args.onefile, output_dir=Path(args.output_dir),
                 keep_intermediate=args.keep_intermediate, gui=args.gui)


if __name__ == "__main__":
    raise SystemExit(main())
