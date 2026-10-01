"""核心纯逻辑层：无网络、无 print、无 input、无 sys.exit。

core 只接收注入的 Provider / Cache / Clock 接口，绝不 import 具体实现，
这样 GUI 与测试都可以直接复用它。
"""
