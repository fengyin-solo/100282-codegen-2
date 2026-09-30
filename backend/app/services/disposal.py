"""绿化废弃物处置业务规则。

口径说明（磅单与处置台账不再「两张皮」）：
- 每次过磅生成一张过磅单（disposal_ticket），过磅单是唯一数据源；
- 过磅单先挂在草稿批次下，整批过账后才进入处置台账，整批撤下即整体退出；
- 按车牌归拢同一车的多张单，对账单与页面归拢共用同一份聚合结果，保证一车一行、条数一致；
- 处置汇总的合计在每次导入/过账/撤下时都由过磅单实时重算，不另存口径。
"""
from __future__ import annotations

import datetime as dt
import threading
from typing import Any

from app.store import SUMMARY_SKIP_TABLES, store

VEHICLE_TABLE = "disposal_vehicle"
BATCH_TABLE = "disposal_batch"
TICKET_TABLE = "disposal_ticket"

METHOD_PLOW = "粉碎还田"
METHOD_TRANSFER = "外部转运"
METHODS = (METHOD_PLOW, METHOD_TRANSFER)

STATUS_DRAFT = "草稿"
STATUS_POSTED = "已过账"
STATUS_WITHDRAWN = "已撤下"
BATCH_STATUSES = (STATUS_DRAFT, STATUS_POSTED, STATUS_WITHDRAWN)

# 处置相关表不是通用台账结构，运营概览里不参与计数
SUMMARY_SKIP_TABLES.update({VEHICLE_TABLE, BATCH_TABLE, TICKET_TABLE})


def _today() -> str:
    return dt.date.today().isoformat()


def _now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def _parse_weight(value: Any) -> float | None:
    """把 1200、'1200'、'1200kg' 统一解析成千克数；解析不出返回 None。"""
    if value is None:
        return None
    text = str(value).strip().lower().replace("kg", "").replace("公斤", "").strip()
    if not text:
        return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


class DisposalService:
    """批次入账服务：所有写操作都在同一把锁内完成，过账/撤下按「先算齐、再落库」执行。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ensure_seed()

    # ------------------------------------------------------------------ 基础数据

    def list_vehicles(self) -> list[dict[str, Any]]:
        return [dict(row) for row in store.rows(VEHICLE_TABLE)]

    def _vehicle_map(self) -> dict[str, dict[str, Any]]:
        return {str(row["车牌号"]): row for row in store.rows(VEHICLE_TABLE)}

    def _find_batch(self, batch_id: int) -> dict[str, Any] | None:
        return store.find(BATCH_TABLE, batch_id)

    def _batch_tickets(self, batch_id: int) -> list[dict[str, Any]]:
        return [row for row in store.rows(TICKET_TABLE) if int(row["批次id"]) == batch_id]

    def _all_active_numbers(self) -> set[str]:
        """未撤下批次里的磅单号都算数，重复导入只认第一次（含跨批次重复）。"""
        batch_status = {int(b["id"]): b["状态"] for b in store.rows(BATCH_TABLE)}
        numbers: set[str] = set()
        for ticket in store.rows(TICKET_TABLE):
            if batch_status.get(int(ticket["批次id"])) != STATUS_WITHDRAWN:
                numbers.add(str(ticket["磅单号"]))
        return numbers

    def _next_batch_no(self) -> str:
        prefix = f"PC-{_today().replace('-', '')}-"
        tail = 0
        for batch in store.rows(BATCH_TABLE):
            no = str(batch.get("批次号", ""))
            if no.startswith(prefix):
                try:
                    tail = max(tail, int(no.rsplit("-", 1)[1]))
                except ValueError:
                    continue
        return f"{prefix}{tail + 1:02d}"

    def _next_id(self, table: str) -> int:
        return max((int(row.get("id", 0)) for row in store.rows(table)), default=0) + 1

    # ------------------------------------------------------------------ 聚合口径

    @staticmethod
    def _empty_method_bucket() -> dict[str, Any]:
        return {"条数": 0, "重量kg": 0.0}

    def _aggregate(self, tickets: list[dict[str, Any]]) -> dict[str, Any]:
        """粉碎还田 / 外部转运分栏合计，合计随过磅单一起重算。"""
        columns = {METHOD_PLOW: self._empty_method_bucket(), METHOD_TRANSFER: self._empty_method_bucket()}
        for ticket in tickets:
            bucket = columns.setdefault(str(ticket["处置方式"]), self._empty_method_bucket())
            bucket["条数"] += 1
            bucket["重量kg"] = round(bucket["重量kg"] + float(ticket["净重kg"]), 2)
        total_count = sum(item["条数"] for item in columns.values())
        total_weight = round(sum(item["重量kg"] for item in columns.values()), 2)
        return {
            "分栏": columns,
            "合计": {"条数": total_count, "重量kg": total_weight},
        }

    def _group_by_vehicle(
        self, tickets: list[dict[str, Any]], vehicles: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """按车牌归拢同一车的多张单，一车一行；对账单直接复用这份结果。"""
        order: list[str] = []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for ticket in tickets:
            plate = str(ticket["车牌号"])
            if plate not in grouped:
                grouped[plate] = []
                order.append(plate)
            grouped[plate].append(ticket)

        rows: list[dict[str, Any]] = []
        for plate in order:
            vehicle = vehicles.get(plate, {})
            vehicle_tickets = grouped[plate]
            summary = self._aggregate(vehicle_tickets)
            rows.append({
                "车牌号": plate,
                "车辆单位": vehicle.get("车辆单位", "—"),
                "核定载重kg": vehicle.get("核定载重kg"),
                "条数": summary["合计"]["条数"],
                "总净重kg": summary["合计"]["重量kg"],
                "粉碎还田": summary["分栏"].get(METHOD_PLOW, self._empty_method_bucket()),
                "外部转运": summary["分栏"].get(METHOD_TRANSFER, self._empty_method_bucket()),
                "磅单号列表": [str(t["磅单号"]) for t in vehicle_tickets],
            })
        return rows

    def _batch_detail(self, batch: dict[str, Any]) -> dict[str, Any]:
        tickets = sorted(self._batch_tickets(int(batch["id"])), key=lambda row: int(row["id"]))
        vehicles = self._vehicle_map()
        return {
            "batch": dict(batch),
            "tickets": [dict(ticket) for ticket in tickets],
            "groups": self._group_by_vehicle(tickets, vehicles),
            "summary": self._aggregate(tickets),
        }

    # ------------------------------------------------------------------ 批次流转

    def open_batch(self) -> tuple[dict[str, Any], bool]:
        """开启新批次；已有草稿时直接领回（关页面后再进来不留下半批，草稿接着做）。"""
        with self._lock:
            for batch in store.rows(BATCH_TABLE):
                if batch["状态"] == STATUS_DRAFT:
                    return self._batch_detail(batch), False
            batch = {
                "id": self._next_id(BATCH_TABLE),
                "批次号": self._next_batch_no(),
                "状态": STATUS_DRAFT,
                "创建时间": _now(),
                "过账时间": None,
                "撤下时间": None,
            }
            store.rows(BATCH_TABLE).append(batch)
            return self._batch_detail(batch), True

    def list_batches(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            batches = sorted(
                (dict(row) for row in store.rows(BATCH_TABLE)),
                key=lambda row: int(row["id"]),
                reverse=True,
            )
            if status:
                batches = [row for row in batches if row["状态"] == status]
            for batch in batches:
                batch["票据条数"] = len(self._batch_tickets(int(batch["id"])))
            return batches

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        with self._lock:
            batch = self._find_batch(batch_id)
            return self._batch_detail(batch) if batch else None

    def post_batch(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        """整批过账：先把合计算齐，最后一次性改状态；任何一步失败都不落半批。"""
        with self._lock:
            batch = self._find_batch(batch_id)
            if batch is None:
                return None, f"批次 {batch_id} 不存在或已归档"
            if batch["状态"] != STATUS_DRAFT:
                return None, f"批次「{batch['批次号']}」当前是{batch['状态']}，只有草稿批次能过账"
            tickets = self._batch_tickets(batch_id)
            if not tickets:
                return None, f"批次「{batch['批次号']}」还没有一张有效过磅单，不能空批过账"
            # 过账前按过磅单重算一遍合计（合计随过磅单一起重算）
            summary = self._aggregate(tickets)
            posted_at = _now()
            batch["状态"] = STATUS_POSTED
            batch["过账时间"] = posted_at
            batch["合计条数"] = summary["合计"]["条数"]
            batch["合计重量kg"] = summary["合计"]["重量kg"]
            for ticket in tickets:
                ticket["状态"] = STATUS_POSTED
            return self._batch_detail(batch), f"批次「{batch['批次号']}」已整批过账，处置台账同步 {summary['合计']['条数']} 张过磅单"

    def withdraw_batch(self, batch_id: int) -> tuple[bool, str]:
        """整批撤下：已过账的整体退出台账；草稿则整体丢弃，绝不留半截。"""
        with self._lock:
            batch = self._find_batch(batch_id)
            if batch is None:
                return False, f"批次 {batch_id} 不存在或已归档"
            if batch["状态"] == STATUS_WITHDRAWN:
                return False, f"批次「{batch['批次号']}」已经撤下，不能重复撤下"
            if batch["状态"] == STATUS_DRAFT:
                store.remove(TICKET_TABLE, lambda row: int(row["批次id"]) == batch_id)
                store.remove(BATCH_TABLE, lambda row: int(row["id"]) == batch_id)
                return True, f"草稿批次「{batch['批次号']}」已整批撤下，草稿与过磅单全部丢弃"
            batch["状态"] = STATUS_WITHDRAWN
            batch["撤下时间"] = _now()
            for ticket in self._batch_tickets(batch_id):
                ticket["状态"] = STATUS_WITHDRAWN
            return True, f"批次「{batch['批次号']}」已整批撤下，相关过磅单全部退出处置台账"

    # ------------------------------------------------------------------ 过磅单导入

    def parse_text(self, raw_text: str) -> list[tuple[int, dict[str, str]]]:
        """解析粘贴的磅单文本，支持制表符/逗号分隔，首行带不带表头都可以。"""
        parsed: list[tuple[int, dict[str, str]]] = []
        header: dict[str, int] | None = None
        for line_no, line in enumerate(raw_text.splitlines(), start=1):
            # 空单元格必须保留（比如毛重空着的单），否则后续列会错位；只跳过整行空白
            cells = [cell.strip() for cell in line.replace(",", "\t").split("\t")]
            if not any(cells):
                continue
            if header is None and any("磅单号" in cell for cell in cells):
                header = {name: idx for idx, name in enumerate(cells)}
                continue
            if header is not None:
                row = {name: (cells[idx] if idx < len(cells) else "") for name, idx in header.items()}
            else:
                # 默认列序：磅单号 车牌 毛重 皮重 处置方式 过磅时间
                names = ["磅单号", "车牌号", "毛重kg", "皮重kg", "处置方式", "过磅时间"]
                row = {name: (cells[idx] if idx < len(cells) else "") for idx, name in enumerate(names)}
            parsed.append((line_no, row))
        return parsed

    def import_tickets(
        self, batch_id: int, raw_text: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]], list[dict[str, str]], str]:
        """同一批单重复导入只认第一次；重量空着或超载的单张退回，并写出是哪一车哪一条。

        返回：批次明细、退回明细、重复明细、错误信息。
        """
        rejected: list[dict[str, str]] = []
        duplicated: list[dict[str, str]] = []
        with self._lock:
            batch = self._find_batch(batch_id)
            if batch is None:
                return None, rejected, duplicated, f"批次 {batch_id} 不存在或已归档"
            if batch["状态"] != STATUS_DRAFT:
                return None, rejected, duplicated, f"批次「{batch['批次号']}」已是{batch['状态']}，不能再追加过磅单"

            vehicles = self._vehicle_map()
            claimed = self._all_active_numbers()
            accepted = 0
            for line_no, row in self.parse_text(raw_text):
                ticket_no = row.get("磅单号", "").strip()
                plate = row.get("车牌号", "").strip()
                method = row.get("处置方式", "").strip()
                where = f"第{line_no}行"

                def reject(reason: str) -> None:
                    rejected.append({
                        "位置": where,
                        "车牌号": plate or "（未填车牌）",
                        "磅单号": ticket_no or "（未填磅单号）",
                        "退回原因": reason,
                    })

                if not ticket_no:
                    reject("磅单号为空，无法生成过磅单")
                    continue
                if ticket_no in claimed:
                    duplicated.append({
                        "位置": where,
                        "车牌号": plate or "（未填车牌）",
                        "磅单号": ticket_no,
                        "重复原因": "同一批单重复导入，只认第一次的过磅单",
                    })
                    continue
                if not plate:
                    reject("车牌号为空，无法按车归拢")
                    continue
                vehicle = vehicles.get(plate)
                if vehicle is None:
                    reject(f"车牌 {plate} 未登记车辆档案，查不到核定载重")
                    continue
                if method not in METHODS:
                    reject(f"处置方式「{method or '（空）'}」不支持，只认：{'、'.join(METHODS)}")
                    continue

                gross = _parse_weight(row.get("毛重kg"))
                tare = _parse_weight(row.get("皮重kg")) or 0.0
                if gross is None:
                    reject(f"车牌 {plate} 的磅单 {ticket_no} 毛重空着或不是数字，无法计量净重")
                    continue
                net = round(gross - tare, 2)
                if net <= 0:
                    reject(f"车牌 {plate} 的磅单 {ticket_no} 净重 {net}kg 不合规（毛重须大于皮重）")
                    continue
                capacity = float(vehicle["核定载重kg"])
                if net > capacity:
                    reject(
                        f"车牌 {plate} 的磅单 {ticket_no} 净重 {net:g}kg 超出核定载重 {capacity:g}kg，单张退回"
                    )
                    continue

                claimed.add(ticket_no)
                ticket = {
                    "id": self._next_id(TICKET_TABLE),
                    "批次id": batch_id,
                    "磅单号": ticket_no,
                    "车牌号": plate,
                    "毛重kg": gross,
                    "皮重kg": tare,
                    "净重kg": net,
                    "处置方式": method,
                    "过磅时间": row.get("过磅时间", "").strip() or _now(),
                    "状态": STATUS_DRAFT,
                }
                store.rows(TICKET_TABLE).append(ticket)
                accepted += 1

            return self._batch_detail(batch), rejected, duplicated, f"导入完成：认入 {accepted} 张，退回 {len(rejected)} 张，重复跳过 {len(duplicated)} 张"

    # ------------------------------------------------------------------ 台账与对账单

    def ledger_tickets(self) -> list[dict[str, Any]]:
        """处置台账：只取已过账批次的过磅单，撤下批次自动退出。"""
        batch_rows = {int(b["id"]): b for b in store.rows(BATCH_TABLE) if b["状态"] == STATUS_POSTED}
        tickets = [
            dict(ticket)
            for ticket in store.rows(TICKET_TABLE)
            if int(ticket["批次id"]) in batch_rows
        ]
        for ticket in tickets:
            batch = batch_rows[int(ticket["批次id"])]
            ticket["批次号"] = batch["批次号"]
            ticket["过账时间"] = batch["过账时间"]
        return sorted(tickets, key=lambda row: int(row["id"]))

    def disposal_summary(self) -> dict[str, Any]:
        """处置汇总：合计全部由已过账过磅单重算，撤下的批次不计入。"""
        tickets = self.ledger_tickets()
        summary = self._aggregate(tickets)
        summary["批次数"] = len({int(ticket["批次id"]) for ticket in tickets})
        return summary

    def statement(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        """随车对账单：一车一行，行数与条数直接取页面同一批次的归拢结果。"""
        with self._lock:
            batch = self._find_batch(batch_id)
            if batch is None:
                return None, f"批次 {batch_id} 不存在或已归档"
            detail = self._batch_detail(batch)
            return {
                "批次号": batch["批次号"],
                "状态": batch["状态"],
                "生成时间": _now(),
                "车辆行数": len(detail["groups"]),
                "rows": detail["groups"],
                "summary": detail["summary"],
            }, ""

    # ------------------------------------------------------------------ 示例数据

    def _ensure_seed(self) -> None:
        if getattr(self, "_seeded", False):
            return
        if store.rows(VEHICLE_TABLE):
            self._seeded = True
            return
        vehicles = [
            {"id": 1, "车牌号": "沪A·D3126", "车辆单位": "静安养护一班", "核定载重kg": 3000},
            {"id": 2, "车牌号": "沪B·P8052", "车辆单位": "徐汇清运队", "核定载重kg": 5000},
            {"id": 3, "车牌号": "沪C·K1779", "车辆单位": "浦东林洁公司", "核定载重kg": 8000},
            {"id": 4, "车牌号": "沪D·Z2048", "车辆单位": "闵行转运组", "核定载重kg": 5000},
        ]
        store.rows(VEHICLE_TABLE).extend(vehicles)

        batch = {
            "id": 1,
            "批次号": f"PC-{_today().replace('-', '')}-01",
            "状态": STATUS_POSTED,
            "创建时间": _now(),
            "过账时间": _now(),
            "撤下时间": None,
        }
        seed_tickets = [
            ("WD-1001", "沪A·D3126", 2600, 400, METHOD_PLOW),
            ("WD-1002", "沪A·D3126", 2300, 380, METHOD_TRANSFER),
            ("WD-1003", "沪B·P8052", 4800, 600, METHOD_PLOW),
            ("WD-1004", "沪C·K1779", 7200, 900, METHOD_TRANSFER),
            ("WD-1005", "沪C·K1779", 6900, 900, METHOD_PLOW),
        ]
        for idx, (no, plate, gross, tare, method) in enumerate(seed_tickets, start=1):
            store.rows(TICKET_TABLE).append({
                "id": idx,
                "批次id": 1,
                "磅单号": no,
                "车牌号": plate,
                "毛重kg": float(gross),
                "皮重kg": float(tare),
                "净重kg": float(gross - tare),
                "处置方式": method,
                "过磅时间": _now(),
                "状态": STATUS_POSTED,
            })
        summary = self._aggregate(self._batch_tickets(1))
        batch["合计条数"] = summary["合计"]["条数"]
        batch["合计重量kg"] = summary["合计"]["重量kg"]
        store.rows(BATCH_TABLE).append(batch)
        self._seeded = True


service = DisposalService()
