"""图表配置角色授权接口。

围绕主对象图表配置 CFG-0005 提供：授权清单、可见范围调整、发布校验、
越权查询拦截、只读评审副本与授权核对任务的完整接口。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.schemas import ActionResult
from app.services.auth_engine import auth_engine
from app.services.chart_config import chart_config_service
from app.services.chart_query import chart_query_service
from app.services.review_snapshot import review_snapshot_service
from app.store import store

router = APIRouter(prefix="/api/chart-auth", tags=["图表配置角色授权"])


class GrantItem(BaseModel):
    团队编号: str
    角色编号: str | None = None
    允许维度: list[str] = Field(default_factory=list)
    权限级别: str = "viewer"
    是否拒绝: bool = False
    授权方式: str | None = None


class ScopePayload(BaseModel):
    operator_role: str
    grants: list[GrantItem]
    remark: str | None = None


class BindingPayload(BaseModel):
    operator_role: str
    横轴字段: str
    纵轴字段: str


class QueryPayload(BaseModel):
    role: str
    dimensions: list[str]
    copy_id: int | None = None


class CopyPayload(BaseModel):
    operator_role: str
    target_role: str = "ROLE-REVIEWER"
    freeze_dimensions: list[str] | None = None


class TaskCompletePayload(BaseModel):
    operator_role: str
    conclusion: str


@router.get("/master")
def get_master() -> dict[str, Any]:
    """图表配置主记录：可见范围、可视化图表绑定与配置版本以这里为准。"""
    master = chart_config_service.get_master()
    return {
        "主记录": master,
        "版本流水": chart_config_service.list_versions(),
        "数据集": store.auth_find("auth_dataset", 数据集编号=master["数据集编号"]),
    }


@router.get("/teams")
def list_teams_and_roles() -> dict[str, Any]:
    return {
        "teams": store.auth_rows("team"),
        "roles": store.auth_rows("role"),
        "dimensions": store.auth_rows("auth_dimension"),
    }


@router.get("/manifest")
def grant_manifest() -> dict[str, Any]:
    """CFG-0005、DASH-0002、FILT-0003 三个对象分别列出可见团队与继承来源。"""
    return chart_config_service.grant_manifest()


@router.get("/decision")
def role_decision(role: str) -> dict[str, Any]:
    return auth_engine.effective_authorization("CFG-0005", role)


@router.put("/scope", response_model=ActionResult)
def update_scope(payload: ScopePayload) -> ActionResult:
    grants = [item.model_dump() for item in payload.grants]
    result, errors = chart_config_service.update_scope(
        grants,
        operator_role=payload.operator_role,
        remark=payload.remark or "",
    )
    if errors:
        raise HTTPException(status_code=403 if "不能调整" in errors[0] else 400, detail="；".join(errors))
    return ActionResult(ok=True, message="可见范围已更新并生成相邻模块核对任务", entry=result)


@router.get("/versions")
def list_versions() -> list[dict[str, Any]]:
    return chart_config_service.list_versions()


@router.get("/tasks")
def list_tasks(scope_version: str | None = None) -> list[dict[str, Any]]:
    return chart_config_service.list_check_tasks(scope_version)


@router.post("/tasks/{task_id}/complete", response_model=ActionResult)
def complete_task(task_id: int, payload: TaskCompletePayload) -> ActionResult:
    task, message = chart_config_service.complete_check_task(
        task_id, payload.conclusion, operator_role=payload.operator_role
    )
    if task is None:
        raise HTTPException(status_code=403, detail=message)
    return ActionResult(ok=True, message=message, entry=task)


@router.post("/publish-validate")
def publish_validate(operator_role: str = "ROLE-ADMIN") -> dict[str, Any]:
    """发布校验：角色 × 联动维度 × 数据集组合，越权组合直接判定不通过。"""
    return chart_config_service.publish_validate(operator_role=operator_role)


@router.put("/binding", response_model=ActionResult)
def update_binding(payload: BindingPayload) -> ActionResult:
    master, message = chart_config_service.update_binding(
        横轴字段=payload.横轴字段,
        纵轴字段=payload.纵轴字段,
        operator_role=payload.operator_role,
    )
    if master is None:
        raise HTTPException(status_code=403, detail=message)
    return ActionResult(ok=True, message=message, entry=master)


@router.post("/query")
def query_chart(payload: QueryPayload) -> dict[str, Any]:
    """图表数据查询：未授权维度在入口拒绝，越权筛选无法改变图表结果。"""
    result, status, message = chart_query_service.query_chart(
        role_code=payload.role,
        dimensions=payload.dimensions,
        copy_id=payload.copy_id,
    )
    if status != 200:
        raise HTTPException(status_code=status, detail=message)
    result["message"] = message
    return result


@router.get("/filter-dimensions")
def filter_dimensions(role: str) -> dict[str, Any]:
    """全局筛选器对该角色实际暴露的联动维度。"""
    return chart_query_service.filter_dimensions(role)


@router.get("/panels/status")
def panel_status() -> dict[str, Any]:
    """可见范围调整后，看板面板与筛选器显示的最新授权状态。"""
    return {
        "图表主记录授权状态": chart_config_service.get_master()["授权状态"],
        "看板面板": store.auth_rows("panel_binding"),
        "全局筛选器": store.auth_rows("filter_binding"),
    }


@router.post("/review-copies", response_model=ActionResult)
def create_review_copy(payload: CopyPayload) -> ActionResult:
    snapshot, errors = review_snapshot_service.create_copy(
        operator_role=payload.operator_role,
        target_role=payload.target_role,
        freeze_dimensions=payload.freeze_dimensions,
    )
    if errors:
        raise HTTPException(status_code=403 if "无编辑权" in errors[0] else 400, detail="；".join(errors))
    return ActionResult(ok=True, message="只读评审副本已生成，维度与范围版本已冻结", entry=snapshot)


@router.get("/review-copies")
def list_review_copies() -> list[dict[str, Any]]:
    return review_snapshot_service.list_copies()


@router.post("/review-copies/{copy_id}/attempt-edit")
def attempt_copy_edit(copy_id: int, role: str) -> ActionResult:
    """演示受控维度修改被拒绝：任何角色都不能改动只读副本。"""
    snapshot = review_snapshot_service.get_copy(copy_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"评审副本 {copy_id} 不存在")
    ok, message = review_snapshot_service.attempt_edit(snapshot, role)
    return ActionResult(ok=ok, message=message)
