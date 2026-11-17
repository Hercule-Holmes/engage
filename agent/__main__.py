# -*- coding: utf-8 -*-
"""入口: python -m agent  (推荐)
也兼容直接运行: python agent/__main__.py"""
import sys
from pathlib import Path

if __package__ in (None, ""):
    # 被当脚本直接运行(非包上下文): 项目根加入 sys.path, 用绝对包名导入
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from agent.loop import main
else:
    from .loop import main

main()
