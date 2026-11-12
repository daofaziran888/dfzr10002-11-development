"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS
from app.seed_auth import AUTH_SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 授权域表（团队/角色/图表配置主记录/授权/副本/核对任务等）
        self.auth_tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in AUTH_SEED_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def auth_rows(self, table: str) -> list[dict[str, Any]]:
        return self.auth_tables.setdefault(table, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def auth_find(self, table: str, **criteria: Any) -> dict[str, Any] | None:
        for row in self.auth_rows(table):
            if all(row.get(key) == value for key, value in criteria.items()):
                return row
        return None

    def auth_find_all(self, table: str, **criteria: Any) -> list[dict[str, Any]]:
        return [
            row
            for row in self.auth_rows(table)
            if all(row.get(key) == value for key, value in criteria.items())
        ]

    def next_auth_id(self, table: str) -> int:
        return max((int(row.get("id", 0)) for row in self.auth_rows(table)), default=0) + 1

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
