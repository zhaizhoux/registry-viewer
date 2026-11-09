"""regview - 只读的 Windows 注册表图形化查看器。

零第三方依赖：后端使用 Python 标准库 winreg + http.server，
前端是随包附带的单页应用，浏览器只连接 127.0.0.1。
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
