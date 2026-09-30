"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any, Callable

from app.seed import SEED_ROWS

# 非通用台账结构的业务表（如绿化废弃物处置的过磅单/批次/车辆），不计入运营概览
SUMMARY_SKIP_TABLES: set[str] = set()


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name not in SUMMARY_SKIP_TABLES)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def remove(self, module: str, predicate: Callable[[dict[str, Any]], bool]) -> int:
        """按条件就地删除行，返回删掉的条数；用于整批撤下这类需要「整体消失」的操作。"""
        table = self.rows(module)
        kept = [row for row in table if not predicate(row)]
        removed = len(table) - len(kept)
        self._tables[module] = kept
        return removed

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

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
