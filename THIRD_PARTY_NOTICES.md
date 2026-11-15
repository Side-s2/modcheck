# 第三方组件与许可证

本项目整体以 **GNU General Public License v3.0 or later**（见 [LICENSE](LICENSE)）发布。

## 运行时依赖

| 组件 | 许可证 | 说明 |
|---|---|---|
| **PyQt6** | **GPL v3** | Riverbank 的 Qt 绑定。**正是它决定了本项目必须采用 GPL** |
| **Qt 6** | LGPL v3 / GPL v3 / 商业 | PyQt6 底层依赖；以 LGPL 方式链接 |
| [truststore](https://github.com/sethmlarson/truststore) | MIT | 使用系统证书信任链验证 HTTPS |
| Python 标准库 | PSF License | 随 Python 分发 |

### truststore 许可

```text
The MIT License (MIT)

Copyright (c) 2022 Seth Michael Larson

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

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
