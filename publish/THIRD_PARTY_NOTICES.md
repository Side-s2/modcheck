# 第三方组件与许可证

本项目整体以 **GNU General Public License v3.0 or later**（见 [LICENSE](LICENSE)）发布。

## 运行时依赖

### CLI 版（`modcheck`）

**零第三方运行时依赖** —— 只使用 Python 标准库。
因此 CLI 产物里不含任何第三方代码，分发时只需随附本项目的 LICENSE。

### GUI 版（`modcheck-gui`，规划中）

| 组件 | 许可证 | 说明 |
|---|---|---|
| **PyQt6** | **GPL v3** | Riverbank 的 Qt 绑定。**正是它决定了本项目必须采用 GPL** |
| **Qt 6** | LGPL v3 / GPL v3 / 商业 | PyQt6 底层依赖；以 LGPL 方式链接 |
| Python 标准库 | PSF License | 随 Python 分发 |

## 为什么本项目是 GPL 而不是 MIT

PyQt6 以 **GPL v3** 授权（另有付费商业许可）。GPL 具有传染性：**分发链接了 PyQt6 的程序，
整个程序就必须以 GPL 兼容的许可证发布并提供源码**。
既然本项目本就开源，采用 GPL-3.0 是最简单、也最合规的选择。

> 如果将来希望 GUI 以**闭源**方式分发，有两条路：
> ① 改用 **PySide6**（Qt 官方，LGPL，闭源分发友好，API 与本项目用法几乎一致）；
> ② 向 Riverbank 购买 PyQt6 商业许可。
> 两者的**界面效果完全相同**，切换成本约为改一行 import。

## 构建期依赖（不随产物分发）

| 组件 | 许可证 | 用途 |
|---|---|---|
| Nuitka | Apache License 2.0 | 打包成独立可执行文件 |
| pytest | MIT | 测试 |
| winlibs GCC（Nuitka 自动下载） | GPL v3 + GCC Runtime Library Exception | 编译 C 代码 |

## 数据来源

- **Modrinth API v2** —— 模组与版本数据；使用其公开 API，遵守其服务条款与速率限制（本程序内置 240 次/分钟限速）；
- **Mojang 版本清单**（`piston-meta.mojang.com`）—— 官方游戏版本列表。

本程序**不重新分发任何模组文件**：下载功能直接指向 Modrinth 官方 CDN 直链，
用户下载到的文件由模组作者按其自身许可证提供。
