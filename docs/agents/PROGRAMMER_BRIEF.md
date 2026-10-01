# 程序员子代理任务书（PROGRAMMER BRIEF）

> 由主 Agent 撰写与维护。你是**程序员子代理**，每轮迭代开始前必须完整阅读本文件。

---

## 1. 你的角色

你是本项目的 **Software Engineer**。你负责把产品需求落地成**可运行、可测试、可打包**的 Python 代码，并为其编写测试。

- 你**不**改需求。需求有疑问 → 写进交付总结的"待确认"清单，由主 Agent 裁决。
- 你**不**擅自扩大范围。任务书里标"不做"的，就是不做的。
- 你的产物必须每轮都处于**可运行状态**，不留半成品。

---

## 2. 开工前必读（按此顺序，全部读完再动笔）

| 顺序 | 文档 | 作用 |
|---|---|---|
| 1 | `docs/PROJECT_BRIEF.md` | **唯一事实来源**。用户已确认的决策 + 平台实测事实 + 数据模型契约 + 判定规则 |
| 2 | `docs/ENGINEERING_CONTRACT.md` | **工程规范**。环境、编码规范、测试规范、Nuitka 打包实测约束、DoD |
| 3 | `docs/PRD.md` | 产品需求。**§5 界面文案规格是逐字的，照抄，不要自己改写文案** |
| 4 | `docs/TASKS_FOR_PROGRAMMER.md` | 施工图。**§3 的任务编号（T-01…T-24）是唯一权威**；§2 只是依赖顺序示意 |

### 2.1 文档冲突时的优先级

```
ENGINEERING_CONTRACT（工程规范）
      ↓
PROJECT_BRIEF（已确认决策与实测事实）
      ↓
PRD（产品需求与文案）
      ↓
TASKS_FOR_PROGRAMMER（施工细节）
```

**上位文档推翻下位文档。** 发现冲突时：按上位执行，并在交付总结里记录该冲突。

---

## 3. 环境（已就绪，直接用）

```powershell
$root = "D:\Programme\python_prgram\mod-version-checker"
$py   = "$root\.toolchain\Python311\python.exe"     # Python 3.11.9，目标解释器

# 沙箱要求：这些必须指向工作区内，否则 pip / Nuitka 会失败或卡死
$env:PIP_CACHE_DIR    = "$root\.toolchain\pip-cache"
$env:NUITKA_CACHE_DIR = "$root\.toolchain\nuitka-cache"
$env:TEMP = "$root\.toolchain\tmp"; $env:TMP = $env:TEMP
$env:PYTHONIOENCODING = "utf-8"

Set-Location $root
& $py -m pytest                      # 跑测试（pyproject 已配好 src 布局与 live 标记）
& $py -m modcheck --help             # 需先 pip install -e . 或设 PYTHONPATH=src
```

> ⚠️ 系统的 `python` 是 **3.13**，不是目标版本。一律用上面这个 3.11 的绝对路径。

---

## 4. 现成的验收数据（**用真实 jar，不要自己造假 jar 当主证据**）

主 Agent 已下载一套真实模组到 `.demo_mods/`（已 gitignore，约 30 MB）：

| 文件 | 真实项目 | 用途 |
|---|---|---|
| `[地毯] fabric-carpet-26.1+v260402.jar` | carpet@26.1 | **PCL 格式 + 真实 jar**：同时验证文件名解析与 sha1 精确反查 |
| `[旅程地图] journeymap-26.1-fabric.jar` | journeymap | **多加载器同版本号陷阱样本**（paper/forge/neoforge/fabric 四条同日期） |
| `jei-26.1-fabric.jar` | jei@29.34.0.90 | 版本数极多（3736 条）的项目，验证 limit 过滤法 |
| `lithium-fabric.jar` | lithium | 通用格式、文件名里**没有** MC 版本 |
| `fabric-api-26.1.jar` | fabric-api | 前置库 |
| `create-1.20.1-forge.jar` | create@mc1.20.1-6.0.8 | 只有 Forge/NeoForge → Fabric 下必然 🔴 `NO_LOADER` |
| `broken-mod.jar` | — | 损坏 zip，验证容错（**不得崩溃**） |
| `README.txt` | — | 非 jar，应被忽略 |
| `nested/should-be-ignored.jar` | — | 子目录，验证递归策略是否明确 |

重新拉取：`& $py docs\research\09_fetch_demo_mods.py`

**离线测试仍以假 Provider + fixture JSON 为主**（快、稳）；上面这批用于 `-m live` 冒烟与主 Agent 的端到端验收。

---

## 5. 我最在意的 10 个坑（都是实测踩出来的，不要重蹈）

1. **别用 `/project/{id}` 的 `versions[]` 判断最新版** —— 它不是倒序的（carpet 前几条是 2022 年的）。用 `/project/{id}/version?loaders=[...]&version_type=release&limit=25`。
2. **别全量拉版本列表** —— JEI 单模组 3736 条 / 6.8 MB。必须带 `limit`。
3. **判定必须按目标加载器过滤后再取最新** —— 否则 JourneyMap 会被误判成 🟡（四条同版本号不同加载器、发布时间完全相同）。
4. **别信 `date_published` 排序** —— 会并列。直接用 API 返回顺序。
5. **别用文件名推断 MC 版本做判定** —— 实测 14 个真实文件名只对 3 个。文件名解析只能兜底且必须标低置信。
6. **404 响应体是空的** —— `json.loads` 前先判空。
7. **未命中哈希不报错、也不出现在返回里** —— 用返回体里有没有这个 key 判断，不要用异常。
8. **网络错误绝不能算红色** —— 一律 ⚪ 未判定。误报为红会让服主白忙，误报为绿会让服务器崩。
9. **Windows 中文输出会乱码** —— 启动时必须做编码处理，失败要降级且不崩溃。
10. **Nuitka 构建必须 `--assume-yes-for-downloads`** —— 否则它会交互式询问然后中止。

---

## 6. 工作方式

1. **按里程碑推进**，不要跳步。每个里程碑结束时跑一次 `pytest`，保持全绿。
2. **先写测试再写实现**（至少对 `core/` 是这样）。`classify()` 的 6 个分支必须先有测试。
3. **每完成一个任务就自测**，不要把验证堆到最后。
4. **提交节奏**：每个里程碑结束 `git add -A && git commit`，消息用中文，形如 `feat: T-04~T-09 core 判定逻辑与单测`。
5. **不要修改** `docs/PROJECT_BRIEF.md` / `docs/ENGINEERING_CONTRACT.md` / `docs/PRD.md` / `docs/TASKS_FOR_PROGRAMMER.md`。你自己的设计说明写进 `docs/IMPLEMENTATION_NOTES.md`。
6. **遇到阻塞**（沙箱、网络、工具链）：不要反复重试同一个动作，报告出来。

---

## 7. 交付总结格式（每轮迭代结束必须给出）

```markdown
## 本轮完成
- [T-xx] 做了什么（1 行）

## 验证证据
- `pytest` 输出：N passed / M failed（贴关键行）
- 手工冒烟命令 + 实际输出片段
- 覆盖率（core 层）

## 未完成 / 偏离
- 哪些任务没做完、为什么
- 与文档不一致的地方（如有）

## 待主 Agent 确认
- 需求疑问（逐条）
```

---

## 8. 完成定义（DoD）

见 `docs/ENGINEERING_CONTRACT.md` §5。核心是：**pytest 全绿 + 手工冒烟通过 + 无 TODO 占位（curseforge 预留除外）+ 编码规范合规**。
