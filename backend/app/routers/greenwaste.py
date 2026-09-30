"""园林废弃物处置接口。

批次中的过磅单、随车对账单和分方式合计由同一批数据重算；处置台账只读取
已过账批次，撤下批次会整体从台账口径剔除。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    GreenwasteActionPayload,
    GreenwasteBatchPayload,
    GreenwasteImportPayload,
    PageResult,
)
from app.services.greenwaste import GreenwasteService

router = APIRouter(prefix="/api/greenwaste", tags=["园林废弃物处置"])

service = GreenwasteService()


@router.get("", response_model=PageResult[dict])
def list_batches(
    keyword: str | None = Query(default=None, description="按批次号、车牌或单号检索"),
    status: str | None = Query(default=None, description="待过账、已过账、已撤下"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """分页读取处置批次；每张批次卡片带上最新重算的合计。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_batches(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/vehicles")
def list_vehicles() -> dict[str, object]:
    """读取车牌核定载重档案，导入单可自动带出载重上限。"""
    return {"items": service.vehicles()}


@router.get("/ledger")
def disposal_ledger(
    month: str | None = Query(default=None, description="YYYY-MM"),
    plate: str | None = None,
    mode: str | None = Query(default=None, description="粉碎还田或外部转运"),
    keyword: str | None = None,
) -> dict[str, object]:
    """正式处置台账：仅包含已过账批次，按粉碎还田、外部转运分栏汇总。"""
    return service.ledger(month=month, plate=plate, mode=mode, keyword=keyword)


@router.post("/batches", response_model=ActionResult)
def create_batch(payload: GreenwasteBatchPayload) -> ActionResult:
    """建立空的待过账批次；未传批次号时按月份自动编号。"""
    try:
        batch = service.create_batch(batch_no=payload.batch_no, remark=payload.remark)
    except ValueError as exc:
        return ActionResult(ok=False, message=str(exc))
    return ActionResult(ok=True, message=f"批次 {batch['batch_no']} 已建立，等待导入过磅单", entry=batch)


@router.post("/batches/{batch_id}/tickets/import")
def import_tickets(batch_id: int, payload: GreenwasteImportPayload) -> dict[str, object]:
    """导入过磅单；空重、超载、重复单号逐张退回并标明车号、单号和数据行。"""
    if not payload.tickets and not (payload.content or "").strip():
        raise HTTPException(status_code=400, detail="没有可导入的过磅单，请先粘贴 CSV 或提交单据列表")
    try:
        return service.import_tickets(batch_id, tickets=payload.tickets, content=payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batches/{batch_id}/actions", response_model=ActionResult)
def batch_action(batch_id: int, payload: GreenwasteActionPayload) -> ActionResult:
    """整批过账或整批撤下；不存在“半批”的正式台账状态。"""
    try:
        result = service.change_status(batch_id, payload.action)
    except ValueError as exc:
        return ActionResult(ok=False, message=str(exc))
    return ActionResult(ok=True, message=result["message"], entry=result["batch"])


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int) -> dict[str, object]:
    """读取一个批次的过磅单、合计和随车对账单。"""
    try:
        return service.get_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/batches/{batch_id}/reconciliation")
def batch_reconciliation(batch_id: int) -> dict[str, object]:
    """随车对账单按车归拢：一车一行，条数与页面过磅单完全一致。"""
    try:
        return service.reconciliation(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
