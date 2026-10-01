# 协作约定：并行提交不得互相卷入

## 背景（真实事故）

重构期间主 Agent 与程序员子代理并行工作。主 Agent 执行了这样一条命令：

```powershell
git add docs/research/41_verify_refactor.py docs/research/42_verify_golden_normalized.py
git commit -q -m "test: 主 Agent 的独立复核"
```

结果该提交里**还包含了子代理尚未提交的 CheckOutcome 改动**（src/modcheck/flows/*、tests/test_flows_check.py）。

## 根因

**git commit 提交的是整个暂存区，而不只是你刚 add 的那几个文件。**
子代理当时已经 git add 了自己的改动（处于「已暂存未提交」的中间态），
主 Agent 的 add 只是追加到同一个暂存区，于是 commit 把两者一起提交了。

失败的那条假设是：**「暂存区里只有我的东西」** —— 在并行工作时这个假设不成立。

## 约定

1. **并行期间一律用路径限定提交**：
   ```
   git commit -q -m "..." -- <路径1> <路径2>
   ```
   git commit -- <pathspec> 只提交这些路径，**不受暂存区其它内容影响**。
2. **提交前先看** git status --porcelain，确认自己只碰了该碰的路径；
3. **分工边界**：子代理主要动 src/ + tests/，主 Agent 主要动 docs/ + docs/research/；
   需要跨界改动时先打招呼。
4. **不改历史**：两人并行时 rebase/amend 的风险大于收益。提交信息与内容不符时，
   记录在案（就像本条），而不是重写历史。

## 这条的普遍意义

任何「A 写代码、B 做验证」的并行流程都会遇到同一类问题：
**验证者为了记录证据而提交，却可能连带提交被验证者尚未定稿的代码** ——
那会让「这个提交是绿的」这个判断失去意义。路径限定提交是最小、最直接的防护。
