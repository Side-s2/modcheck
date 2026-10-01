"""网络数据源层：唯一出网的地方。

只暴露抽象基类、注册表与具体 Provider；Provider 只抛 modcheck.errors 里的领域异常。
"""
