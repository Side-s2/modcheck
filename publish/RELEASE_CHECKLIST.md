# 发布清单

> 每次发版照着走一遍。**这份清单本身也由 `build/make_publish.py` 同步到 `publish/`。**

## 0. 这份清单为什么存在

发布最容易漏的不是构建，而是**那些只有发版时才做、平时想不起来的事**：
改版本号、补下载地址、确认产物真能跑。漏一次就要重发一次。

---

## 1. 发版前

- [ ] 确认 `pyproject.toml` 里的 `version` 已更新
- [ ] 全量测试通过：`pytest`（应全绿；需要联网的用例默认跳过）
- [ ] 逐字快照无意外差异：`docs/research/42_verify_golden_normalized.py` 与 `docs/research/40_flow_output_baseline.py` 的 compare
- [ ] 分层自检 0 违规：`python docs/research/36_layering_check.py`
- [ ] `publish/` 已重新生成：`python build/make_publish.py --source-zip`

## 2. 构建产物

```bash
python build/nuitka_build.py --onefile --output-dir dist        # 命令行单文件
python build/nuitka_build.py --output-dir dist-standalone      # 命令行免安装目录
python build/nuitka_build.py --gui --output-dir dist-gui       # 图形界面
```

每个产物目录里应自带双击启动脚本（`启动CLI.cmd` / `启动GUI.cmd`），由构建脚本生成。

## 3. 验证产物（**不要跳过**）

- [ ] 命令行版跑一次真实检查，结论与源码版**逐字一致**（含退出码）
- [ ] 图形界面版能启动并显示窗口
- [ ] 单文件版双击能起来（若失败，见下方「已知坑」）

参考脚本：`docs/research/44_verify_packages.py`

## 4. 上传到 Release

| 上传文件 | 说明 |
|---|---|
| modcheck-<版本>-cli-standalone.zip | 由 `dist-standalone/` 打包 |
| modcheck-<版本>-cli-onefile.exe | 由 `dist/` 取 |
| modcheck-<版本>-gui.zip | 由 `dist-gui/` 打包 |
| modcheck-<版本>-source.zip | 即 `publish/` 里那份（GitHub 也会自动生成 Source code） |

发布说明里建议写清：**这次改了什么、有没有行为变化、升级时要注意什么**。

## 5. 补下载地址

- [ ] `README.md` 的「下载」一节里有一处 `<待补充>`，填上 Releases 页面地址
- [ ] 改完**重跑** `python build/make_publish.py`，让 `publish/README.md` 同步

---

## 已知坑（都实际踩过）

1. **单文件版解包目录**：默认解到 `%TEMP%`，而从临时目录解包并执行正是杀毒软件最常拦的行为 ——
   用户表现为「双击一闪而过、以管理员身份运行却正常」。构建脚本已改成解到用户缓存目录并启用 cached 模式。
2. **启动脚本要纯 ASCII**：cmd.exe 用 OEM 代码页，脚本里的中文注释会变成乱码。
3. **构建会清空输出目录**：所以启动脚本必须由构建脚本生成，手工放进去的每次都会丢。
4. **推 tag 前先确认工作区干净**：二进制产物不进版本库（见 `.gitignore`），别把它们提交上去。
