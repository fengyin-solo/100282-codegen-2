"""园林废弃物处置业务规则。

过磅单先进入“待过账”批次；处置台账只从已过账批次展开。批次内的合计、
车次数和随车对账单均由过磅单实时重算，避免磅单与台账两张皮。
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from threading import RLock
from typing import Any

from app.store import store

BATCH_MODULE = "greenwaste_batch"
VEHICLE_MODULE = "greenwaste_vehicle"

DRAFT = "待过账"
POSTED = "已过账"
CANCELLED = "已撤下"
RECYCLED = "粉碎还田"
EXTERNAL = "外部转运"

MODE_ALIASES = {
    "粉碎还田": RECYCLED,
    "还田": RECYCLED,
    "粉碎": RECYCLED,
    "外部转运": EXTERNAL,
    "外运": EXTERNAL,
    "转运": EXTERNAL,
}

FIELD_ALIASES = {
    "ticket_no": ("过磅单号", "单号", "磅单号", "ticket_no"),
    "plate": ("车牌", "车牌号", "车牌号码", "plate"),
    "rated_load": ("核定载重", "核定载质量", "载重", "rated_load"),
    "weight": ("净重", "净重(kg)", "净重（kg）", "重量", "weight"),
    "mode": ("处置方式", "处置类型", "去向", "mode"),
    "origin": ("来源绿地", "来源", "产地", "origin"),
    "weigh_date": ("过磅日期", "过磅时间", "日期", "weigh_date"),
}

SEED_VEHICLES = [
    {"plate": "粤A12345", "rated_load": 5000},
    {"plate": "粤A67890", "rated_load": 8000},
    {"plate": "粤A88888", "rated_load": 3000},
]

SEED_TICKETS = [
    {
        "ticket_no": "PB-20260915-001",
        "plate": "粤A12345",
        "weight": 3200,
        "mode": RECYCLED,
        "origin": "滨河公园",
        "weigh_date": "2026-09-15",
    },
    {
        "ticket_no": "PB-20260915-002",
        "plate": "粤A12345",
        "weight": 2800,
        "mode": EXTERNAL,
        "origin": "滨河公园",
        "weigh_date": "2026-09-15",
    },
    {
        "ticket_no": "PB-20260915-003",
        "plate": "粤A67890",
        "weight": 7600,
        "mode": RECYCLED,
        "origin": "城北绿带",
        "weigh_date": "2026-09-15",
    },
]


def _number(value: Any) -> float | None:
    """把导入的重量转成 kg；空值和无法识别的值交给调用方退回。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text:
        return None
    text = text.removesuffix("kg").removesuffix("KG").removesuffix("千克").strip()
    multiplier = Decimal("1")
    if text.endswith("吨"):
        multiplier = Decimal("1000")
        text = text[:-1]
    try:
        number = Decimal(text) * multiplier
    except InvalidOperation:
        return None
    return round(float(number), 2)


def _clean(value: Any) -> str:
    return str(value or "").strip()


class GreenwasteService:
    def __init__(self) -> None:
        self._lock = RLock()
        self._ensure_seed()

    def _ensure_seed(self) -> None:
        vehicles = store.rows(VEHICLE_MODULE)
        if not vehicles:
            vehicles.extend(dict(item) for item in SEED_VEHICLES)

        batches = store.rows(BATCH_MODULE)
        if batches:
            return
        batch = {
            "id": 1,
            "batch_no": "GW-202609-001",
            "status": POSTED,
            "pending": False,
            "abnormal": False,
            "remark": "9月中旬园林废弃物处置示例批次",
            "created_at": "2026-09-15 08:30",
            "posted_at": "2026-09-15 17:30",
            "cancelled_at": None,
            "tickets": [],
        }
        batches.append(batch)
        for ticket in SEED_TICKETS:
            self._append_ticket(batch, ticket, rated_load=self._vehicle_load(ticket["plate"]))
        self._recalculate(batch)

    def _batches(self) -> list[dict[str, Any]]:
        return store.rows(BATCH_MODULE)

    def _vehicles(self) -> list[dict[str, Any]]:
        return store.rows(VEHICLE_MODULE)

    def _vehicle_load(self, plate: str) -> float | None:
        for vehicle in self._vehicles():
            if vehicle["plate"] == plate:
                return float(vehicle["rated_load"])
        return None

    def _find_batch(self, batch_id: int) -> dict[str, Any] | None:
        return store.find(BATCH_MODULE, batch_id)

    def _next_batch_id(self) -> int:
        return max((int(item["id"]) for item in self._batches()), default=0) + 1

    def _next_batch_no(self) -> str:
        prefix = f"GW-{datetime.now():%Y%m}-"
        used = [item["batch_no"] for item in self._batches() if str(item["batch_no"]).startswith(prefix)]
        sequence = 1
        for value in used:
            try:
                sequence = max(sequence, int(str(value).rsplit("-", 1)[-1]) + 1)
            except ValueError:
                continue
        return f"{prefix}{sequence:03d}"

    def _pick(self, row: dict[str, Any], key: str) -> str:
        for alias in FIELD_ALIASES[key]:
            if alias in row and _clean(row.get(alias)):
                return _clean(row.get(alias))
        return ""

    def _parse_csv(self, content: str) -> list[dict[str, Any]]:
        text = io.StringIO(content.strip().lstrip("﻿"))
        reader = csv.DictReader(text)
        rows: list[dict[str, Any]] = []
        if not reader.fieldnames:
            return rows
        for raw in reader:
            row = {str(name).strip(): value for name, value in raw.items() if name is not None}
            if any(_clean(value) for value in row.values()):
                row["_source_row"] = reader.line_num
                rows.append(row)
        return rows

    def _append_ticket(self, batch: dict[str, Any], ticket: dict[str, Any], rated_load: float) -> dict[str, Any]:
        plate = ticket["plate"]
        sequence = sum(1 for item in batch["tickets"] if item["plate"] == plate) + 1
        entry = {
            "id": max((int(item["id"]) for item in batch["tickets"]), default=0) + 1,
            "ticket_no": ticket["ticket_no"],
            "plate": plate,
            "sequence": sequence,
            "weight": round(float(ticket["weight"]), 2),
            "rated_load": round(float(rated_load), 2),
            "mode": ticket["mode"],
            "origin": ticket.get("origin") or "",
            "weigh_date": ticket.get("weigh_date") or datetime.now().strftime("%Y-%m-%d"),
        }
        batch["tickets"].append(entry)
        return entry

    def _mode_summary(self) -> dict[str, Any]:
        return {"ticket_count": 0, "weight": 0.0}

    def _recalculate(self, batch: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "ticket_count": len(batch["tickets"]),
            "vehicle_count": 0,
            "total_weight": 0.0,
            "modes": {RECYCLED: self._mode_summary(), EXTERNAL: self._mode_summary()},
        }
        vehicles: dict[str, dict[str, Any]] = {}
        for ticket in batch["tickets"]:
            plate = ticket["plate"]
            weight = round(float(ticket["weight"]), 2)
            mode = ticket["mode"]
            vehicle = vehicles.setdefault(
                plate,
                {
                    "plate": plate,
                    "rated_load": float(ticket["rated_load"]),
                    "ticket_count": 0,
                    "recycled_weight": 0.0,
                    "external_weight": 0.0,
                    "total_weight": 0.0,
                    "first_sequence": int(ticket["sequence"]),
                    "ticket_nos": [],
                },
            )
            vehicle["ticket_count"] += 1
            vehicle["total_weight"] = round(vehicle["total_weight"] + weight, 2)
            vehicle["ticket_nos"].append(ticket["ticket_no"])
            if mode == RECYCLED:
                vehicle["recycled_weight"] = round(vehicle["recycled_weight"] + weight, 2)
            else:
                vehicle["external_weight"] = round(vehicle["external_weight"] + weight, 2)

            summary["modes"][mode]["ticket_count"] += 1
            summary["modes"][mode]["weight"] = round(summary["modes"][mode]["weight"] + weight, 2)
            summary["total_weight"] = round(summary["total_weight"] + weight, 2)

        summary["vehicle_count"] = len(vehicles)
        reconciliation = sorted(vehicles.values(), key=lambda item: (item["first_sequence"], item["plate"]))
        for item in reconciliation:
            item.pop("first_sequence", None)
        batch["summary"] = summary
        batch["reconciliation"] = reconciliation
        batch["abnormal"] = False
        return summary

    def _batch_view(self, batch: dict[str, Any]) -> dict[str, Any]:
        self._recalculate(batch)
        return dict(batch)

    def list_batches(
        self,
        *,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(self._batches())
        if status:
            rows = [item for item in rows if item["status"] == status]
        if keyword:
            needle = keyword.strip()
            rows = [
                item
                for item in rows
                if needle in item["batch_no"]
                or any(needle in ticket["plate"] or needle in ticket["ticket_no"] for ticket in item["tickets"])
            ]
        rows.sort(key=lambda item: int(item["id"]), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._batch_view(item) for item in rows[start:start + size]], total

    def vehicles(self) -> list[dict[str, Any]]:
        return [dict(item) for item in sorted(self._vehicles(), key=lambda item: item["plate"])]

    def create_batch(self, batch_no: str | None = None, remark: str | None = None) -> dict[str, Any]:
        with self._lock:
            return self._create_batch(batch_no=batch_no, remark=remark)

    def _create_batch(self, batch_no: str | None = None, remark: str | None = None) -> dict[str, Any]:
        number = _clean(batch_no) or self._next_batch_no()
        if any(item["batch_no"] == number for item in self._batches()):
            raise ValueError(f"批次号 {number} 已存在，请更换后再建批")
        batch = {
            "id": self._next_batch_id(),
            "batch_no": number,
            "status": DRAFT,
            "pending": True,
            "abnormal": False,
            "remark": _clean(remark),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "posted_at": None,
            "cancelled_at": None,
            "tickets": [],
        }
        self._recalculate(batch)
        self._batches().append(batch)
        return self._batch_view(batch)

    def import_tickets(
        self,
        batch_id: int,
        *,
        tickets: list[dict[str, Any]] | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        # 服务级锁保证导入、过账和撤下不会并发写出半批。
        with self._lock:
            return self._import_tickets(batch_id, tickets=tickets, content=content)

    def _import_tickets(
        self,
        batch_id: int,
        *,
        tickets: list[dict[str, Any]] | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        batch = self._find_batch(batch_id)
        if batch is None:
            raise ValueError(f"批次 {batch_id} 不存在")
        if batch["status"] != DRAFT:
            raise ValueError(f"批次 {batch['batch_no']} 已{batch['status']}，不能再导单")

        raw_rows = list(tickets or [])
        if content and content.strip():
            raw_rows.extend(self._parse_csv(content))

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        seen = {
            ticket["ticket_no"]: (item["batch_no"], ticket)
            for item in self._batches()
            if item["status"] != CANCELLED
            for ticket in item["tickets"]
        }
        plate_accepted: dict[str, int] = {}

        for index, raw in enumerate(raw_rows, start=1):
            source_row = int(raw.get("_source_row") or index)
            ticket_no = self._pick(raw, "ticket_no")
            plate = self._pick(raw, "plate")
            mode_text = self._pick(raw, "mode")
            mode = MODE_ALIASES.get(mode_text)
            weight = _number(self._pick(raw, "weight"))
            declared_load = _number(self._pick(raw, "rated_load"))
            base = {"row": source_row, "plate": plate, "ticket_no": ticket_no}

            if not ticket_no:
                rejected.append({**base, "reason": "过磅单号为空"})
                continue
            if not plate:
                rejected.append({**base, "reason": "车牌为空，无法按车归拢"})
                continue
            if not mode:
                rejected.append({**base, "reason": f"处置方式「{mode_text}」不是粉碎还田或外部转运"})
                continue
            if weight is None or weight <= 0:
                rejected.append({**base, "reason": "净重为空或不是有效正数"})
                continue

            rated_load = self._vehicle_load(plate)
            if rated_load is None and declared_load is None:
                rejected.append({**base, "reason": "车辆未登记核定载重，本单无法判断是否超载"})
                continue
            if rated_load is None:
                if declared_load is not None and declared_load <= 0:
                    rejected.append({**base, "reason": "核定载重必须为正数"})
                    continue
                rated_load = declared_load
                self._vehicles().append({"plate": plate, "rated_load": rated_load})
            elif declared_load is not None and abs(declared_load - rated_load) > 0.01:
                rejected.append(
                    {
                        **base,
                        "reason": f"申报核定载重 {declared_load:g}kg 与车辆档案 {rated_load:g}kg 不一致",
                    }
                )
                continue

            if weight > rated_load:  # type: ignore[operator]
                rejected.append(
                    {
                        **base,
                        "reason": f"净重 {weight:g}kg 超出{plate}核定载重 {rated_load:g}kg",
                    }
                )
                continue
            if ticket_no in seen:
                first_batch, first_ticket = seen[ticket_no]
                rejected.append(
                    {
                        **base,
                        "reason": f"单号已在批次 {first_batch} 的{first_ticket['plate']}首次导入，本次不重复入账",
                    }
                )
                continue

            normalized = {
                "ticket_no": ticket_no,
                "plate": plate,
                "weight": weight,
                "mode": mode,
                "origin": self._pick(raw, "origin"),
                "weigh_date": self._pick(raw, "weigh_date") or datetime.now().strftime("%Y-%m-%d"),
            }
            entry = self._append_ticket(batch, normalized, rated_load=rated_load)  # type: ignore[arg-type]
            accepted.append(entry)
            seen[ticket_no] = (batch["batch_no"], entry)
            plate_accepted[plate] = plate_accepted.get(plate, 0) + 1

        self._recalculate(batch)
        return {
            "ok": True,
            "message": f"导入完成：接收 {len(accepted)} 张，退回 {len(rejected)} 张",
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted": accepted,
            "rejected": rejected,
            "batch": self._batch_view(batch),
        }


    def change_status(self, batch_id: int, action: str) -> dict[str, Any]:
        with self._lock:
            return self._change_status(batch_id, action)

    def _change_status(self, batch_id: int, action: str) -> dict[str, Any]:
    batch = self._find_batch(batch_id)
    if batch is None:
        raise ValueError(f"批次 {batch_id} 不存在")
    if action == "post":
        if batch["status"] != DRAFT:
            raise ValueError(f"批次 {batch['batch_no']} 当前为{batch['status']}，不能过账")
        if not batch["tickets"]:
            raise ValueError("空批次不能过账，请先导入有效过磅单或撤下该批次")
        batch["status"] = POSTED
        batch["pending"] = False
        batch["posted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        message = f"批次 {batch['batch_no']} 已整批过账"
    elif action == "cancel":
        if batch["status"] == CANCELLED:
            raise ValueError(f"批次 {batch['batch_no']} 已撤下，不能重复操作")
        batch["status"] = CANCELLED
        batch["pending"] = False
        batch["cancelled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        message = f"批次 {batch['batch_no']} 已整批撤下，处置台账同步剔除"
    else:
        raise ValueError(f"不支持的批次动作 {action}")
    self._recalculate(batch)
    return {"ok": True, "message": message, "batch": self._batch_view(batch)}


    def get_batch(self, batch_id: int) -> dict[str, Any]:
        batch = self._find_batch(batch_id)
        if batch is None:
            raise ValueError(f"批次 {batch_id} 不存在")
        return self._batch_view(batch)

    def reconciliation(self, batch_id: int) -> dict[str, Any]:
        batch = self.get_batch(batch_id)
        return {
            "batch_no": batch["batch_no"],
            "status": batch["status"],
            "vehicle_count": batch["summary"]["vehicle_count"],
            "ticket_count": batch["summary"]["ticket_count"],
            "total_weight": batch["summary"]["total_weight"],
            "items": batch["reconciliation"],
        }

    def ledger(
        self,
        *,
        month: str | None = None,
        plate: str | None = None,
        mode: str | None = None,
        keyword: str | None = None,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for batch in self._batches():
            if batch["status"] != POSTED:
                continue
            for ticket in batch["tickets"]:
                item = {"batch_id": batch["id"], "batch_no": batch["batch_no"], **ticket}
                items.append(item)
        if month:
            items = [item for item in items if str(item["weigh_date"]).startswith(month)]
        if plate:
            items = [item for item in items if plate.strip() in item["plate"]]
        if mode:
            items = [item for item in items if item["mode"] == mode]
        if keyword:
            needle = keyword.strip()
            items = [item for item in items if needle in item["ticket_no"] or needle in item.get("origin", "")]

        summary = {
            "ticket_count": len(items),
            "vehicle_count": len({item["plate"] for item in items}),
            "total_weight": round(sum(float(item["weight"]) for item in items), 2),
            "modes": {RECYCLED: self._mode_summary(), EXTERNAL: self._mode_summary()},
        }
        for item in items:
            summary["modes"][item["mode"]]["ticket_count"] += 1
            summary["modes"][item["mode"]]["weight"] = round(
                summary["modes"][item["mode"]]["weight"] + float(item["weight"]), 2
            )
        items.sort(key=lambda item: (item["weigh_date"], item["batch_id"], item["id"]))
        return {"items": items, "summary": summary}
