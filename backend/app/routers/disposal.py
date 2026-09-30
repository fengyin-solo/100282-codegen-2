"""绿化废弃物处置接口：过磅单按批导入、按车归拢、整批过账/撤下、处置汇总与随车对账单。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.disposal import BATCH_STATUSES, DisposalService

router = APIRouter(prefix="/api/disposal", tags=["绿化废弃物处置"])

service = DisposalService()


class BatchOpenPayload(BaseModel):
    note: str | None = None


class ImportPayload(BaseModel):
    raw_text: str = Field(default="", description="磅单原文，支持制表符/逗号分隔，首行可带表头")


class BatchActionResult(BaseModel):
    ok: bool
    message: str
    detail: dict[str, Any] | None = None


class ImportResult(BaseModel):
    ok: bool
    message: str
    detail: dict[str, Any] | None = None
    rejected: list[dict[str, str]] = Field(default_factory=list)
    duplicated: list[dict[str, str]] = Field(default_factory=list)


@router.get("/vehicles")
def list_vehicles() -> dict[str, Any]:
    """车辆档案：车牌与核定载重，超载退回按这里的口径卡。"""
    return {"items": service.list_vehicles()}


@router.get("/batches")
def list_batches(status: str | None = None) -> dict[str, Any]:
    """批次列表：草稿、已过账、已撤下都保留痕迹；可按状态过滤。"""
    if status is not None and status not in BATCH_STATUSES:
        raise HTTPException(status_code=400, detail=f"批次状态只认：{'、'.join(BATCH_STATUSES)}")
    return {"items": service.list_batches(status)}


@router.post("/batches/open", response_model=BatchActionResult)
def open_batch(_: BatchOpenPayload) -> BatchActionResult:
    """开启/领回草稿批次：已有草稿直接领回，中途关页面再进来接着做，不会新开半批。"""
    detail, created = service.open_batch()
    message = "已开启新批次，等待导入过磅单" if created else "已领回未过账的草稿批次，可继续追加过磅单"
    return BatchActionResult(ok=True, message=message, detail=detail)


@router.get("/batches/{batch_id}", response_model=BatchActionResult)
def get_batch(batch_id: int) -> BatchActionResult:
    """批次明细：过磅单、按车归拢、分栏汇总一次性给齐，页面与对账单共用。"""
    detail = service.get_batch(batch_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"批次 {batch_id} 不存在或已归档")
    return BatchActionResult(ok=True, message="批次明细读取成功", detail=detail)


@router.post("/batches/{batch_id}/import", response_model=ImportResult)
def import_tickets(batch_id: int, payload: ImportPayload) -> ImportResult:
    """导入磅单文本：空重量、超载、未登记车牌等单张退回并写明车与条；重复磅单只认第一次。"""
    if not payload.raw_text.strip():
        return ImportResult(ok=False, message="磅单内容为空，请粘贴或录入过磅数据")
    detail, rejected, duplicated, message = service.import_tickets(batch_id, payload.raw_text)
    if detail is None:
        return ImportResult(ok=False, message=message)
    return ImportResult(ok=True, message=message, detail=detail, rejected=rejected, duplicated=duplicated)


@router.post("/batches/{batch_id}/post", response_model=BatchActionResult)
def post_batch(batch_id: int) -> BatchActionResult:
    """整批过账：要么整批进处置台账，要么一张都不动。"""
    detail, message = service.post_batch(batch_id)
    if detail is None:
        return BatchActionResult(ok=False, message=message)
    return BatchActionResult(ok=True, message=message, detail=detail)


@router.post("/batches/{batch_id}/withdraw", response_model=BatchActionResult)
def withdraw_batch(batch_id: int) -> BatchActionResult:
    """整批撤下：已过账的整批退出台账，草稿整批丢弃。"""
    ok, message = service.withdraw_batch(batch_id)
    return BatchActionResult(ok=ok, message=message, detail=service.get_batch(batch_id) if ok else None)


@router.get("/batches/{batch_id}/statement")
def batch_statement(batch_id: int) -> dict[str, Any]:
    """随车对账单：一车一行，条数与页面归拢完全一致（同一聚合口径）。"""
    statement, message = service.statement(batch_id)
    if statement is None:
        raise HTTPException(status_code=404, detail=message)
    return statement


@router.get("/ledger")
def disposal_ledger() -> dict[str, Any]:
    """处置台账：磅单与台账合一，只列已过账过磅单；批次撤下后自动退出。"""
    items = service.ledger_tickets()
    return {"total": len(items), "items": items}


@router.get("/summary")
def disposal_summary() -> dict[str, Any]:
    """处置汇总：粉碎还田/外部转运分栏，合计随过磅单一起重算。"""
    return service.disposal_summary()
