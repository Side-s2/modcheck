# 研究 / 验证脚本索引

本目录是**主 Agent 的技术验证证据**，不是产品代码。每个脚本都可独立运行，用于复现设计决策。

运行解释器一律用：`.toolchain\Python311\python.exe`（Python 3.11.9）。

| 脚本 | 作用 | 结果文件 |
|---|---|---|
| `01_filename_parsing.py` | 用 14 个真实模组文件名验证"文件名解析"的可靠性 | `results/`（见 02） |
| `02_jar_metadata.py` | 验证 jar 内 `fabric.mod.json` / `mods.toml` / `neoforge.mods.toml` 的可读性与字段 | `results/02_jar_metadata.txt` |
| `03_hash_lookup.py` | 验证 `POST /v2/version_files` 的 sha1 精确反查（含重命名后的 jar） | `results/03_hash_lookup.txt` |
| `04_ordering_and_errors.py` | 验证版本列表排序、404 空响应体、限流响应头 | `results/04_ordering.txt` |
| `05_payload_size.py` | 实测各取数方式的响应体积（JEI 全量 6.8 MB） | `results/05_payload_size.txt` |
| `06_filters_and_limits.py` | 验证 `limit`/`offset`/`loaders`/`game_versions` 过滤是否生效 | `results/06_filters.txt` |
| `07_algorithm_validation.py` | **limit 过滤法 vs 全量法的等价性**：5/5 完全一致 | `results/07_algorithm_validation.txt` |
| `08_pm_spec_verification.py` | PM 子代理复核平台事实时用的脚本 | — |
| `09_fetch_demo_mods.py` | 拉取 `.demo_mods/`：6 个真实模组 + 损坏 jar + 非 jar + 子目录 | `.demo_mods/_manifest.json` |
| `10_ground_truth.py` | **独立判定基准**：不 import modcheck，用自己的算法算期望状态 | `results/10_ground_truth.json` |
| `11_oracle_mods_sample.py` | 对 `mods_sample/` 的 30 个真实 jar 建基准 | `results/11_ground_truth_mods_sample.json` |

## 两个验收数据集

### 1. `.demo_mods/`（可复现，脚本拉取）

由 `09_fetch_demo_mods.py` 从 Modrinth 拉取，特点是**刻意构造边界**：PCL 中文名重命名、损坏 zip、非 jar 文件、子目录、只有 Forge 版的模组。用于验证容错路径。

### 2. `mods_sample/`（**用户提供的真实服务器数据**）

> **来源**：由项目所有者（Minecraft 服主）提供的其服务器真实 `mods` 文件夹副本，共 **30 个 jar / 47 MB**。
> **不来源于任何脚本**，因此**没有**、也不应该有"拉取脚本"。文件来源不可从仓库重建，属于一次性真实样本。

**为什么它最有价值**：它不是构造出来的测试数据，而是一个真实中文 Minecraft 服务端的模组组合（Carpet 系附加、投影/构造系、优化系、权限/回放等），包含真实的命名习惯与版本分布。

**基准结果**（`results/11_ground_truth_mods_sample.json`，由独立脚本算出）：

| 目标 | 🟢 就绪 | 🟡 需降级 | 🔴 阻塞 |
|---|---|---|---|
| MC 26.3 / Fabric | 21 | 7 | 2 |
| MC 26.1 / Fabric | 6 | 24 | 0 |

- **指纹反查命中率 30/30**（100%）——所有 jar 都能被 sha1 精确定位到项目与版本，说明"文件指纹识别"是可靠的一等公民手段。
- 26.3 下的 2 个阻塞项是 `antideath-carpet-addition` 与 `carpet-extra`（都只支持到 MC 26.2）。

> ⚠️ 该目录已在 `.gitignore` 中，**不入库**（体积原因）。验收时它必须存在于磁盘上。
