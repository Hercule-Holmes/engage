# -*- coding: utf-8 -*-
"""SQLite 只读访问层（silver/gold 表）"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "engage.db"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def query(con, sql, params=()):
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def query_one(con, sql, params=()):
    r = con.execute(sql, params).fetchone()
    return dict(r) if r else None
