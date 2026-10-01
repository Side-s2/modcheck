# PM 验收清单 —— Minecraft 模组版本检查工具（modcheck）

> 依据：`docs/PROJECT_BRIEF.md` v1.2 + `docs/PRD.md` v1.1 + `docs/TASKS_FOR_PROGRAMMER.md` + `docs/ENGINEERING_CONTRACT.md`
> 作者：Product Manager 子代理 ｜ 版本 v1.0
> **这份清单会被 PM 逐条真的跑一遍。每一条都是「操作步骤（确切命令）→ 期望结果」。**

---

## 0. 验收环境与准备（先做，否则下面每条都跑不了）

### 0.1 环境

| 项 | 值 |
|---|---|
| 工作目录 | `D:\Programme\python_prgram\mod-version-checker` |
| Python | `.toolchain\Python311\python.exe`（3.11.9） |
| 运行入口 | Windows：`modcheck.cmd` ｜ Linux：`./modcheck.sh` |
| 隔离配置目录 | Windows：`set MODCHECK_CONFIG_DIR=D:\tmp\modcheck-pm` ｜ Linux：`export MODCHECK_CONFIG_DIR=/tmp/modcheck-pm` |
| 每轮开始 | 删掉隔离目录，保证是全新环境 |

### 0.2 准备命令

```
:: Windows（在仓库根目录）
set MODCHECK_CONFIG_DIR=D:\tmp\modcheck-pm
rmdir /s /q %MODCHECK_CONFIG_DIR% 2>nul
.toolchain\Python311\python.exe tests\make_fixtures.py
modcheck.cmd --version
```

```
# Linux
export MODCHECK_CONFIG_DIR=/tmp/modcheck-pm
rm -rf $MODCHECK_CONFIG_DIR
.toolchain/Python311/python.exe tests/make_fixtures.py
./modcheck.sh --version
```

### 0.3 缺陷严重级别（发现即记录）

| 级别 | 定义 | 例子 |
|---|---|---|
| **P0** | 导致用户做出错误升级决策，或程序崩溃 | 误报为 🟢；网络错误标成 🔴；traceback |
| **P1** | 结论正确但用户看不懂 / 做不到 | 问题项没有「建议」行；文案与 PRD 不一致 |
| **P2** | 体验瑕疵 | 列宽微错；进度条刷新略慢 |

### 0.4 记录表模板

```
| 编号 | 结果(通过/失败) | 实际输出摘要 | 缺陷级别 | 备注 |
|---|---|---|---|---|
| A1 |  |  |  |  |
```

---

## A. 启动与环境（9 条）

- [ ] **A1** 运行 `modcheck.cmd --version` → 输出一行 `modcheck 0.1.0`，退出码 0，耗时 < 2 秒，**全程不联网**（可先拔网线再执行）
- [ ] **A2** 运行 `modcheck.cmd --help` → 中文帮助；能看到 `check` / `scan` / `profile` / `versions` / `config` / `cache` 六个子命令；退出码 0
- [ ] **A3** 用全新配置目录运行 `modcheck.cmd` → 横幅含三行：版本行、`配置目录：…`、`数据源：Modrinth 已启用 ｜ CurseForge 未启用（缺少 API Key）`；多一行 `还没有任何模组清单…`；主菜单 6 项齐全；退出码 0
- [ ] **A4** 运行 `modcheck.cmd config show` → 输出与 PRD §5.9 一致（并发 6（上限 8，Modrinth 限速 300 次/分钟）、超时 20 秒（重试 3 次）、缓存 24 小时 / 6 小时）
- [ ] **A5** 运行 `modcheck.cmd config path` → 输出绝对路径，等于 `MODCHECK_CONFIG_DIR`
- [ ] **A6** 运行 `modcheck.cmd --config-dir Z:\definitely\not\writable config path` → 打印 `⚠ 配置目录不可写…已自动改用…`；**不崩溃**；退出码 0
- [ ] **A7** 运行 `modcheck.cmd versions --limit 5` → 前 5 个正式版依次为 `26.3 / 26.2 / 26.1.2 / 26.1.1 / 26.1`；**不含任何 snapshot**
- [ ] **A8** 运行 `modcheck.cmd cache info` → 显示缓存目录、文件数、体积、最早/最新时间；退出码 0
- [ ] **A9** 断网（或 `modcheck.cmd config set proxy http://127.0.0.1:9` 后再 `modcheck.cmd`）→ 主菜单仍正常出现；**不打印 traceback**；退出码 0

---

## B. 扫描与清单（16 条）

- [ ] **B1** 运行 `.toolchain\Python311\python.exe tests\make_fixtures.py` → 生成 `tests\_fixtures\mods_demo\`（6 个文件）与 `tests\_fixtures\profiles\demo.json`
- [ ] **B2** 运行 `modcheck.cmd scan tests\_fixtures\mods_demo --profile demo --yes` → 输出含 `读到 N 个 jar 文件`、`跳过`（分类列出 `broken.jar / server-extra.jar / old-mod.jar.disabled`）、`识别结果：`三段、`清单「demo」已更新`
- [ ] **B3** 接 B2 → `[地毯] fabric-carpet-26.1+v260402.jar` 的识别来源是 **Modrinth 文件指纹** 或 **jar 内元数据**，**绝不是「文件名猜测」**
- [ ] **B4** 运行 `modcheck.cmd profile show demo` → 含 carpet（来源 modrinth、当前版本 `26.1 (v260402)`、识别方式为文件指纹或 jar 内信息）
- [ ] **B5** 再跑一次 B2 → `新增 0 个`；清单条目不翻倍（幂等）
- [ ] **B6** 运行 `modcheck.cmd scan tests\_fixtures\no_such_dir --profile demo --yes` → `✗ 找不到文件夹：…`；退出码 3
- [ ] **B7** 建一个空目录再 `scan` → `⚠ 这个文件夹里没有任何 jar 文件…`；退出码 0；清单未被清空
- [ ] **B8** 在 `mods_demo` 下建一个子文件夹放一个 jar 后 `scan` → 输出 `发现 1 个子文件夹未扫描：…（子文件夹不会被游戏加载）`
- [ ] **B9** 运行 `modcheck.cmd scan --from-list tests\_fixtures\filelist.txt --profile guessdemo --yes` → 清单生成成功；输出中 `文件名猜测` 计数 > 0
- [ ] **B10** 运行 `modcheck.cmd profile show guessdemo` → 这些条目的「识别方式」列显示 `文件名猜测`
- [ ] **B11** 运行 `modcheck.cmd check --profile guessdemo --mc 26.3 --loader fabric --no-color` → 报告头 `识别来源：…文件名猜测 N`；报告内含 `说明：modid 前面带 ~ 的条目是从文件名猜出来的…`；对应行的 modid 前有 `~`
- [ ] **B12** 运行 `modcheck.cmd profile new demo`（demo 已存在）→ `✗ 已存在名为「demo」的清单…`；退出码 3；原清单未被覆盖
- [ ] **B13** 建两份清单后运行 `modcheck.cmd profile rename A B`（B 已存在）→ 拒绝并提示已存在；退出码 3
- [ ] **B14** 运行 `modcheck.cmd profile delete demo`（交互）→ 弹二次确认；答 `n` 后清单仍在
- [ ] **B15** 手工把 `%MODCHECK_CONFIG_DIR%\profiles\demo.json` 删掉一个逗号后：`profile show demo` → PRD E11 文案（含「第 N 行附近不是合法的 JSON」）；退出码 3；同时 `profile list` **仍能**列出其它清单且不崩

---

- [ ] **B16** 在清单里加一条没有 `sources.modrinth`、名字正好是 `chunky` 的条目，然后**交互式**检查 → **不弹出候选选择**（slug 唯一命中 `chunky`），直接认定；报告里该条目正常分组。这验证「slug 唯一命中优先于多个 title 命中」

## C. 检查：三态判定与回归（17 条

- [ ] **C1** 运行 `modcheck.cmd check --profile demo --mc 26.3 --loader fabric --no-color` → 分组顺序为 🔴 → 🟡 → ⚪ → 🟢（🔴 在最前）；Carpet 出现在 🟢 就绪组；**退出码 1**（清单里有 create / create-fabric / no-such-mod-xyz 三个阻塞）
- [ ] **C2** 接 C1，看 Carpet 行 → 版本列显示 `26.1 (v260402) → 26.3 (v260915)`
- [ ] **C3** 运行 `modcheck.cmd check --profile demo --mc 26.3 --loader fabric --no-color --refresh` → Carpet 仍为 🟢（证明程序没有用 `/project/{id}` 里乱序的 versions 数组判断最新版）
- [ ] **C4** **回归重点**：接 C1，找到 `[旅程地图] JourneyMap`（清单里 slug 为 `journeymap`，目标 26.3 / fabric）→ **必须显示 🟢 就绪**。若显示 🟡 需降级，即为 P0 缺陷（全局最新版误判）
- [ ] **C5** 运行 `modcheck.cmd check --profile demo --mc 26.1 --loader fabric --no-color` → `carpet` 变成 🟡 需降级；详情含「最新 Fabric 版…不支持 MC 26.1」与「可用：…（支持 MC 26.1）」
- [ ] **C6** 接 C1，找 `[JEI] Just Enough Items`（26.3 / fabric）→ 🟡 需降级；原因含「没有任何正式版支持」/「只有测试版支持」；可用行含 `beta` 与「稳定性自负」
- [ ] **C7** 接 C1，找 `create` → 🔴 阻塞；原因含「没有 Fabric 版本」并列出它实际有的加载器（Forge、NeoForge）
- [ ] **C8** 接 C1，找 `create-fabric` → 🔴 阻塞；原因含「最高只支持 MC 1.20.1」
- [ ] **C9** 接 C1，找 `no-such-mod-xyz` → 🔴 阻塞；原因含「找不到同名项目」；建议含「CurseForge」
- [ ] **C10** 运行 `modcheck.cmd check --profile demo --mc 26.3 --loader neoforge --no-color` → 出现 `NO_LOADER` 类阻塞（至少一个原本 🟢 的 Fabric 专属模组变成 🔴「没有 NeoForge 版本」）
- [ ] **C11** 运行 `modcheck.cmd check --profile demo --mc 26.3 --loader fabric --no-color --pre` → JEI 不再是「仅测试版可用」的 🟡（应变为 🟢 就绪，或至少分组与原因文案随之变化）
- [ ] **C12** 分别用 `--jobs 1` 与 `--jobs 6` 跑同一条检查 → 两组结论（每个模组的状态与分组）**完全一致**，只有耗时不同
- [ ] **C13** 用一个 200 条的清单跑 `check` → 不崩溃；每个模组都出现在某一组里；无重复条目
- [ ] **C14** 接 C13，核对汇总行的**两条恒等式**（逐条算给主 Agent 看）→ ① `就绪 + 需降级 + 阻塞 + 未判定 = 本次检查数`；② `本次检查数 + 已忽略 = 共 N 个模组`；且报告头的「模组清单：X（N 个模组）」的 N 等于「共 N 个模组」
- [ ] **C15** 在清单里把某个模组标为 `"match_status": "ignored"` 后跑检查 → 它出现在 ⚫ 已忽略组（**最后**），**不计入「本次检查」的四个数**，但**计入「共 N 个模组」**；且汇总行两数关系仍满足 C14 的两条恒等式
- [ ] **C16** 运行 `modcheck.cmd check --mods-dir tests\_fixtures\mods_demo --mc 26.3 --loader fabric --no-color` → 报告头标明「临时清单（未保存）」；退出后 `profiles\` 目录里**没有**新增清单文件

---

- [ ] **C17** 重跑一次 C1 并与上一次报告逐行比对 → **同一清单 + 同一目标版本，两次运行的组内顺序完全一致**（数据源返回顺序不得影响报告顺序）

## D. 文案准确性（13 条，逐字比对 PRD §5）

- [ ] **D1** 任一次检查报告的第一行 → 是 `结论：…`，且与 PRD §5.4 对应分支**逐字一致**（含 emoji 与全角标点）
- [ ] **D2** 各分组标题 → 与 PRD §5.4 的 5 条标题逐字一致（含组说明句）
- [ ] **D3** 每一个 🔴 / 🟡 / ⚪ 条目 → 都有「原因：」与「建议：」两行（用计数校对）
- [ ] **D4** 报告末尾「下一步：」→ 步骤编号连续；把里面的 `modcheck check …` 命令原样粘回终端能跑
- [ ] **D5** ⚪ 组标题 → 含 `（不算失败）`
- [ ] **D6** 断网场景（A9 的代理设置 + 一次 check）→ 结论为 `❓ 无法得出结论` 或 `⚠️ 不能确定…`；**绝不出现 `✅ 可以升级`**
- [ ] **D7** 运行 `modcheck.cmd check --profile demo --mc 26.4-snapshot-2 --loader fabric` → PRD E08 文案逐字；退出码 3
- [ ] **D8** 运行 `modcheck.cmd check --profile demo --mc abc --loader fabric` → PRD E07 文案逐字；退出码 3
- [ ] **D9** 运行 `modcheck.cmd check --profile demo --mc 26.3 --loader quilt` → PRD E10 文案逐字；退出码 3
- [ ] **D10** 用一个 0 模组的清单跑检查 → PRD §5.4「空结果」文案逐字；退出码 0
- [ ] **D11** 用 `findstr /i "NO_LOADER traceback"`（Linux：`grep -iE "NO_LOADER|Traceback"`）搜任意输出 → **零命中**；`--json` 里出现 reason code 属正常
- [ ] **D12** 搜报告全文里的「最新版」字样 → 每处都能看出加载器语境（如「最新 Fabric 正式版」），不得出现光秃秃的「最新版」
- [ ] **D13** `--quiet` 下的输出（主 Agent 批复）→ 🔴 与 🟡 组**仍然逐条完整列出**；🟢 组只有一行 `（N 个，已省略明细）`；报告头 / 汇总 / 结论 / 下一步**全部保留**；`--json` 导出内容与不加 `--quiet` 时**完全一致**

---

## E. 交互式流程与匹配（12 条）

- [ ] **E1** 无参数运行 `modcheck.cmd` → 主菜单 6 项 + `请选择 > `；输入 `0` → 退出码 0
- [ ] **E2** 交互式走 `[1] 检查模组兼容性` 全流程（选清单 demo → 选 26.3 → 选 Fabric → 确认 y）→ 分组报告与子命令 `check --profile demo --mc 26.3 --loader fabric` **结论一致**
- [ ] **E3** 在选择版本那一步输入 `b` → 返回上一步（选清单）；之前的选择仍保留
- [ ] **E4** 在任意子流程输入 `q` → 回到主菜单（不是退出程序）
- [ ] **E5** 用 200 条清单开始检查，**检查进行中按 Ctrl+C** → 1 秒内打印 `已中断（按了 Ctrl+C）。本次检查了 X/Y 个模组，结果不完整…`；**无 traceback**；回到主菜单
- [ ] **E6** 在主菜单按 Ctrl+C → 程序退出，退出码 **130**，无 traceback
- [ ] **E7** 交互式检查 `guessdemo` 清单（含猜出来的、Modrinth 上搜不到完全同名的条目）→ 弹出 `⚠️ 未找到与「…」完全同名的项目` + 最多 5 个候选（含 slug 与下载量）+ 选项 `1-5 / m / s / i / q`
- [ ] **E8** 在 E7 界面选 `s` → 打印 `已跳过「…」，本次记为 ⚪ 未判定。`；该模组最终落在 ⚪ 组
- [ ] **E9** 在 E7 界面选 `i` → 打印 `已永久忽略「…」…`；`profile show` 里该条目 `match_status=ignored`；重跑检查不再询问
- [ ] **E10** 在 E7 界面选 `m` 后输入 `carpet` → 打印 `✓ 已记录：「…」→ Modrinth 项目「Carpet」（carpet）…`；重跑检查不再询问该模组
- [ ] **E11** 用非交互方式运行（加 `--yes`，或把 stdin 接管道）→ **绝不弹交互**；输出 `⚠️ 未找到与「…」完全同名的项目，已按「不猜」原则记为 ⚪ 未判定。`；退出码 2
- [ ] **E12** 交互式检查中选错版本后确认页输 `n` → 回到上一步重选，不开始检查

---

## F. 边界与异常（25 条）

- [ ] **F1** `modcheck.cmd config set proxy http://127.0.0.1:9` 后跑 `check --profile demo --mc 26.3 --loader fabric` → 全部 ⚪ 未判定；报告完整；结论行标注结论不完整；退出码 **4**（首个请求即失败）；文案含代理设置提示
- [ ] **F2** 200 条清单里混入一个必然超时的条目（例如指向 `no-such-host.invalid` 的 slug）→ 该条 ⚪，**其余 199 条结论正常**；退出码 **2**
- [ ] **F3** 清空缓存 + `--jobs 8` 连续跑两次 200 条检查 → 若触发限流，被限流的条目是 ⚪（原因含「被 Modrinth 限流」），**绝不出现 🔴 阻塞**
- [ ] **F4** `modcheck.cmd check --profile demo --mods-dir tests\_fixtures\mods_demo --mc 26.3 --loader fabric` → `✗ --profile 和 --mods-dir 不能同时使用。`；退出码 3
- [ ] **F5** `--jobs 100` → 正常完成（并发被截断到 8）；无报错；`--debug` 下能看到截断提示
- [ ] **F6** 手工造一个含两条相同 mod_id 但不同 key 的清单 → 载入时合并并打印 ⚠️ 文案；不崩；退出码正常
- [ ] **F7** 在 `mods_demo` 里放入同一个模组的两个版本 jar 后 `scan` → 出现 ⚠️ 告警块，列出被保留和被舍弃的两个文件名，并建议手工删除
- [ ] **F8** 用一个只含 `broken.jar` 的目录建清单后检查 → 该条 ⚪ 未判定；不中断；退出码 2
- [ ] **F9** 确认 `old-mod.jar.disabled` **没有**出现在任何清单或报告里（但 scan 输出里说明了跳过原因）
- [ ] **F10** `modcheck.cmd check --profile demo --mc 26.3 --loader fabric --no-color > out.txt` → `out.txt` 内**没有** ANSI 转义序列；中文完整；行宽 100
- [ ] **F11** `--json Z:\nope\out.json` → PRD E22 文案；退出码 3；报告已在屏幕输出
- [ ] **F12** `modcheck.cmd check --file tests\_fixtures\nope.json --mc 26.3 --loader fabric` → 中文提示找不到清单文件；退出码 3；无 traceback
- [ ] **F13** 用一个 0 模组的清单 → 空结果文案；退出码 0
- [ ] **F14** 用一个全部模组都不支持 26.3 的清单 → 结论为「{n} 个模组全部不支持」+ 提示句（新版本刚发布…1~3 周…）；退出码 1
- [ ] **F15** `modcheck.cmd profile new "bad:name"` → 拒绝并说明非法字符；退出码 3
- [ ] **F16** 手工把缓存目录里某个 .json 改成非法 JSON 后重跑检查 → 当作未命中重新请求；**不报错**；结果正确

---

- [ ] **F17** 让 Modrinth 返回非 JSON（无法构造时改为核对单元测试 `tests/test_http.py` 的 parse-error 用例）→ 该模组 ⚪，文案含「返回的数据看不懂」；**不崩**
- [ ] **F18** 证书错误（无法构造时核对单元测试 cert-error 用例）→ 该模组 ⚪；文案含「证书验证失败」；**不崩**
- [ ] **F19** 让 Mojang 不可达（把 `piston-meta.mojang.com` 指向 127.0.0.1 或断网后只恢复 Modrinth）→ `versions` 提示「没取到官方版本列表」；`check --mc 26.3 --profile demo` **仍能跑完**，不因 Mojang 失败而退出
- [ ] **F20** `--window 1` → 正常完成；`--debug` 下能看到「窗口过小可能误判」的提示
- [ ] **F21** `modcheck.cmd scan --from-list tests\_fixtures\nope.txt --profile demo --yes` → 「读不到文件名清单」文案；退出码 3
- [ ] **F22** 造两条 `mod_id` 相同但中文名不同的记录后 `scan` → 合并为一条；两个文件名与两个中文名都保留在 `aliases` 里（`profile show` 可见）
- [ ] **F23** 造一个文件名写 `sodium-fabric-x.jar`、内部 `fabric.mod.json` 的 `id` 却是 `carpet` 的 jar 后 `scan` → 输出「以 jar 内信息为准」；清单里记的是 `carpet`
- [ ] **F24** 放入一个 200 MB 以上的大 jar（可用随机数据改名）后 `scan` → 不爆内存、不卡死、正常跳过或解析；**不崩**
- [ ] **F25** 把清单某条目的 `sources.modrinth` 手工改成不存在的 slug（如 `carpet-old`）后跑检查 → 自动重新搜索并更新为 `carpet`，打印「项目地址已变更」；该条目结论正确

## G. 颜色、编码与终端兼容（8 条）

- [ ] **G1** `--no-color` 输出 → 没有 ANSI 转义序列（搜 ESC 字符零命中）
- [ ] **G2** 在 Windows Terminal 里交互式跑检查 → 🔴 组为红色、🟡 黄色、🟢 绿色、⚪ 灰色；去色后靠 `✗ ! ? ✓` 也能分辨
- [ ] **G3** 设置 `NO_COLOR=1` 后运行 → 无颜色
- [ ] **G4** 在旧版控制台（`cmd.exe` 配 legacy conhost）运行 → 不崩溃；颜色自动降级；文本标签可读
- [ ] **G5** **Windows 中文编码**：分别在 `cmd.exe`、Windows PowerShell、Windows Terminal 里运行 `modcheck.cmd versions --limit 5` → 三次输出中文均正常，无乱码方块
- [ ] **G6** 把终端宽度调到 60 列后跑检查 → 走窄版布局；不出现横向错乱或半个汉字
- [ ] **G7** Linux（WSL / 容器）下跑同一条 `./modcheck.sh check --profile demo --mc 26.3 --loader fabric --no-color` → 分组、结论、退出码与 Windows 完全一致（仅路径分隔符不同）
- [ ] **G8** `modcheck.cmd check … | findstr "阻塞"`（Linux 用 `| grep 阻塞`）→ 能正常过滤；无颜色码干扰

---

## H. 退出码与导出（13 条）

- [ ] **H1** 全绿清单 → 退出码 **0**
- [ ] **H2** 含 🔴 的清单 → 退出码 **1**
- [ ] **H3** 只有 ⚪（断网，且不是首个请求就失败的情况）→ 退出码 **2**
- [ ] **H4** 参数错误（如 `--mc abc`）→ 退出码 **3**
- [ ] **H5** 数据源整体不可用（首个请求即连接失败）→ 退出码 **4**
- [ ] **H6** 检查中 Ctrl+C → 退出码 **130**
- [ ] **H7** 只有 🟡 的清单 → 退出码 **0**（决策 D2：需降级不算失败）
- [ ] **H8** `--json out.json` → 合法 JSON；含 `schema_version`、分组、每条 `status` 与 `reason`
- [ ] **H9** `--md out.md` → 含分组标题、结论与下一步；可直接贴到群里阅读
- [ ] **H10** `--csv out.csv` → 表头固定；用 Excel 打开中文不乱码
- [ ] **H11** 不写导出路径时（交互式菜单里的「导出报告」）→ 默认文件名形如 `report_demo_26.3_fabric_20261001-2103.json`
- [ ] **H12** 导出到只读路径 → PRD E22 文案；退出码 3

---

- [ ] **H13** 用 PRD §5.3 的样例清单（3 阻塞 + 2 未判定 + 1 已忽略）跑检查 → **退出码必须是 1**（不是 2、不是 130）；验证「🔴 优先于 ⚪」的退出码优先级

## I. 性能与体感（7 条）

- [ ] **I1** 200 条清单、清空缓存后跑检查 → **≤ 90 秒**（记录实测秒数）
- [ ] **I2** 同一条清单紧接着再跑一次（热缓存）→ **≤ 5 秒**；报告头显示缓存命中数
- [ ] **I3** 检查过程中观察进度行 → 至少每秒刷新一次；含「当前：<模组名>」；结束后该行**不残留**在报告上方
- [ ] **I4** 当检查到若干个阻塞项后 → 进度行出现并累加 `已发现 N 个阻塞`
- [ ] **I5** 用 `--debug` 观察某个模组的请求数 → **≤ 3 次**（A / B / B2，A2 仅在 A 为空时）
- [ ] **I6** 检查前后对比缓存目录体积 → 增幅不超过原始响应体积的 15%
- [ ] **I7** 检查进行中按 Ctrl+C → **≤ 1 秒**开始输出中断摘要

---

## J. 打包与交付（6 条）

- [ ] **J1** 运行 `.toolchain\Python311\python.exe build\nuitka_build.py` → 构建成功；产出 `dist\modcheck\modcheck.exe`
- [ ] **J2** 运行 `dist\modcheck\modcheck.exe --version` → 打印 `modcheck 0.1.0`
- [ ] **J3** 在 `dist\modcheck\` 里搜 `pytest` / `_pytest` → **零命中**
- [ ] **J4** 把 `dist\modcheck\` 整个目录复制到 `D:\tmp\modcheck-dist\` 并在那里运行 `modcheck.exe versions --limit 3` → 正常运行
- [ ] **J5** 检查 `pyproject.toml` 的 `dependencies` 为空；`pip show` 依赖列表里无第三方
- [ ] **J6** `README.md` 为中文，含四个典型命令（scan / check / profile list / versions）与退出码表

---

## K. 文档与测试一致性（6 条）

- [ ] **K1** 抽查 10 条 PRD §5 的文案 → 与程序实际输出逐字一致
- [ ] **K2** TASKS §4.2 的 30 条必含回归用例 → 在 `tests/` 里都能找到对应测试函数（`pytest --collect-only -q` 里能搜到）
- [ ] **K3** 运行 `.toolchain\Python311\python.exe -m pytest tests -m "not live"` → **全绿**，且**全程不联网**（可断网执行验证）
- [ ] **K4** core 层测试覆盖率 → **≥ 80%**
- [ ] **K5** PRD §0.1 标注「需主 Agent 确认」的决策（D2/D3/D8/D9/D11/D14）→ 主 Agent 已全部批复，且程序员的实现与批复后的 PRD 一致（尤其 D8 用的是独立 reason_code **NO_FILES**，不是 NO_LOADER）
- [ ] **K6** 打开 `docs/ENGINEERING_CONTRACT.md` 与 `docs/TASKS_FOR_PROGRAMMER.md` → 任务书 §0 明确引用了工程师契约；§2 里程碑表的任务编号与 §3 任务清单**完全对齐**（T-01~T-24，无 T-07b / T-25 / T-26 这类不存在的编号）

---

## L. 一票否决项（出现任意一条，整体不通过）

1. 把网络错误 / 限流 / 超时标成 🔴 阻塞。
2. 用「全局最新版」而不是「目标加载器最新版」做判定，导致 JourneyMap 这类模组被误判（C4 失败）。
3. 在非交互模式下自动"猜"一个项目并给出结论。
4. 文件名解析结果被用于三态判定。
5. 出现任何 Python traceback。
6. 单个模组失败导致整个检查中断。
7. 报告结论不完整（有 ⚪ 或 被中断）却显示「✅ 可以升级」。
8. 程序写入了用户的 mods 文件夹。
