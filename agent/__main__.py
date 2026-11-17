# -*- coding: utf-8 -*-
"""入口: python -m agent            (终端 REPL)
       python -m agent --web     (Web 界面, http://127.0.0.1:8000)
也兼容直接运行: python agent/__main__.py"""
import sys
from pathlib import Path

if __package__ in (None, ""):
    # 被当脚本直接运行(非包上下文): 项目根加入 sys.path, 用绝对包名导入
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "agent"

if "--web" in sys.argv:
    from .web import main as web_main
    web_main()
else:
    from .loop import main
    main()
