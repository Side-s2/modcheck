"""使用 Nuitka 构建 Windows 图形界面便携目录。"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from modcheck import __version__

EXCLUDES = ("pytest", "_pytest", "unittest", "pydoc", "doctest", "pdb", "test")
LAUNCHER = (
    "@echo off\r\n"
    'cd /d "%~dp0"\r\n'
    'start "" "modcheck-gui\\modcheck-gui.exe" %*\r\n'
)


def build(*, output_dir: Path = Path("dist-gui"), keep_intermediate: bool = False) -> int:
    toolchain = ROOT / ".toolchain"
    temp_dir = toolchain / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("NUITKA_CACHE_DIR", str(toolchain / "nuitka-cache"))
    env.setdefault("TEMP", str(temp_dir))
    env.setdefault("TMP", env["TEMP"])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(ROOT / "src"), env.get("PYTHONPATH"))))

    # 在输出目录之外先编译，避免一次失败的构建破坏现有便携版。
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".modcheck-build-", dir=output_dir))
    try:
        cmd = [sys.executable, "-m", "nuitka", "--assume-yes-for-downloads",
               "--standalone", "--enable-plugin=pyqt6", "--windows-console-mode=disable",
               "--include-package=truststore",
               "--output-dir=" + str(staging), "--output-filename=modcheck-gui.exe",
               "--company-name=modcheck", "--product-name=modcheck",
               "--file-version=" + __version__, "--product-version=" + __version__]
        icon = ROOT / "assets" / "modcheck.ico"
        if icon.is_file():
            cmd.append("--windows-icon-from-ico=" + str(icon))
            cmd.append(f"--include-data-files={icon}=assets/modcheck.ico")
        for name in ("arrow-down.png", "arrow-down-on.png"):
            asset = ROOT / "src" / "modcheck" / "gui" / name
            cmd.append(f"--include-data-files={asset}=modcheck/gui/{name}")
        cmd.extend("--nofollow-import-to=" + name for name in EXCLUDES)
        if not keep_intermediate:
            cmd.append("--remove-output")
        cmd.append(str(ROOT / "src" / "modcheck" / "gui" / "__main__.py"))
        code = subprocess.call(cmd, cwd=ROOT, env=env)
        if code:
            return code

        product = next((path for path in staging.glob("*.dist")
                        if (path / "modcheck-gui.exe").is_file()), None)
        if product is None:
            raise RuntimeError("Nuitka 未生成 modcheck-gui.exe")
        target = output_dir / "modcheck-gui"
        previous = staging / "previous"
        if target.exists():
            # 便携模式把清单和缓存存在 exe 旁边。
            if (target / "config").is_dir():
                shutil.copytree(target / "config", product / "config")
            target.rename(previous)
        try:
            product.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise
        (output_dir / "启动GUI.cmd").write_bytes(LAUNCHER.encode("ascii"))
        if previous.exists():
            shutil.rmtree(previous)
        return 0
    finally:
        if not keep_intermediate and not (staging / "previous").exists():
            shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 modcheck 图形界面便携版")
    parser.add_argument("--output-dir", default="dist-gui", help="输出目录")
    parser.add_argument("--keep-intermediate", action="store_true", help="保留 Nuitka 中间目录")
    args = parser.parse_args(argv)
    return build(output_dir=Path(args.output_dir), keep_intermediate=args.keep_intermediate)


if __name__ == "__main__":
    raise SystemExit(main())
