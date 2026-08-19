"""终端进度条工具。

仅在交互式终端（stderr 为 TTY）时显示 tqdm 进度条；否则返回禁用态 tqdm，
不会向 Streamlit 子进程的 stdout 管道写入任何进度字符。
禁用态 tqdm 仍是完整可用的对象（update / refresh / close 均为安全操作）。
"""
import sys

from tqdm import tqdm


def terminal_progress(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    kwargs.setdefault("disable", not sys.stderr.isatty())
    return tqdm(*args, **kwargs)
