# -*- coding: utf-8 -*-
"""文本规范化——build_silver(别名入库)与 engine(查询侧)共用的同一函数。

契约: 只做可逆性无关的机械归一(全半角/重音/大小写/空白标点),
不含任何游戏语义。两侧行为不一致 = 数据 Bug。
"""
import unicodedata

_KEEP_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF))  # CJK 扩展A + 基本区


def norm(text: str) -> str:
    """NFKC → 去重音(é→e) → 小写 → 仅保留 CJK 与 ASCII 字母数字。"""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = unicodedata.normalize("NFKC", s).lower()
    out = []
    for ch in s:
        o = ord(ch)
        if any(lo <= o <= hi for lo, hi in _KEEP_RANGES):
            out.append(ch)
        elif ch.isascii() and ch.isalnum():
            out.append(ch)
    return "".join(out)
