# 附录 35：`.cmd` 文件必须纯 ASCII（我踩了两次）

cmd.exe 按**系统 OEM 代码页**（简中 Windows 是 GBK）读取 `.cmd`/`.bat`，
而我们的工具链写文件一律 UTF-8 —— 于是 .cmd 里的中文注释会变成乱码：

```
rem 双击这个文件启动 modcheck   ->   rem 鍙屽嚮杩欎釜鏂囦欢鍚姩 modcheck
```

**后果不只是难看**：乱码字节可能被 cmd 当成命令，实测报过
`'文件跟程序放一起（便携），不写进' is not recognized as an internal or external command`。

## 规则

1. `.cmd` / `.bat` 的**内容**一律纯 ASCII（注释也写英文）；
2. 文件名可以是中文（NTFS 与 cmd 都能处理），但内容不行；
3. `.ps1` 同理会按代码页读 —— 需要中文时用 **UTF-8 with BOM**，其余情况也建议纯 ASCII；
4. `.sh` 没有这个问题（Linux 默认 UTF-8）。

## 这条已经踩过两次

- 第一次：`modcheck.cmd` 里加中文注释 → 启动直接报错；
- 第二次：给用户做的 `启动.cmd` 又写了中文注释 → 同样乱码。
