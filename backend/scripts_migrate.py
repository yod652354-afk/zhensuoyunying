# -*- coding: utf-8 -*-
"""启动前迁移：为已有表补充模型新增的列（SQLite ALTER TABLE ADD COLUMN）。"""
import warnings
warnings.filterwarnings("ignore")

import sqlalchemy as sa
from sqlalchemy import inspect

import app.models  # noqa: F401  注册全部模型
from app.database import engine, Base

insp = inspect(engine)
existing_tables = set(insp.get_table_names())

added = 0
with engine.begin() as conn:
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # 新表由 create_all 处理
        existing_cols = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue
            # 构造 ADD COLUMN DDL（SQLite 支持 nullable/default 常量）
            col_type = col.type.compile(dialect=engine.dialect)
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'
            if col.nullable is False:
                default = col.default.arg if col.default is not None else None
                if default is not None and isinstance(default, (str, int, float, bool)):
                    if isinstance(default, str):
                        default = f"'{default}'"
                    ddl += f" NOT NULL DEFAULT {default}"
                else:
                    ddl += " NULL"  # 无常量默认值则放宽为可空
            try:
                conn.execute(sa.text(ddl))
                print(f"  + {table.name}.{col.name}")
                added += 1
            except Exception as e:
                print(f"  ! {table.name}.{col.name}: {e}")
print(f"迁移完成：补充 {added} 列")