"""图表查询与筛选器维度暴露服务。

核心安全口径：前端传入未授权维度时整体拒绝（403），不做静默丢弃，
保证越权筛选不可能改变图表结果。评审副本走冻结维度，同样在入口拦截。
"""
from __future__ import annotations

from typing import Any

from app.services.auth_engine import auth_engine
from app.services.review_snapshot import review_snapshot_service
from app.store import store

from app.seed_auth import CHART_ID, FILTER_ID


class ChartQueryService:
    def query_chart(
        self,
        *,
        role_code: str,
        dimensions: list[str],
        copy_id: int | None = None,
        chart_code: str = CHART_ID,
    ) -> tuple[dict[str, Any] | None, int, str]:
        """返回（结果, http状态, 说明）。越权维度直接 403，不执行任何聚合。"""
        if copy_id is not None:
            return self._query_copy(copy_id, role_code, dimensions)

        decision = auth_engine.effective_authorization(chart_code, role_code)
        if not decision["可访问"]:
            return None, 403, f"角色 {role_code} 对图表 {chart_code} 无可见授权"
        ok, illegal = auth_engine.check_dimensions(chart_code, role_code, dimensions)
        if not ok:
            return (
                None,
                403,
                f"角色 {role_code} 未授权维度：{'、'.join(illegal)}，请求已拒绝，图表结果保持不变",
            )
        rows = self._aggregate(dimensions)
        return (
            {
                "图表编号": chart_code,
                "角色编号": role_code,
                "使用维度": dimensions,
                "权限级别": decision["权限级别"],
                "范围版本": decision.get("范围版本"),
                "行数": len(rows),
                "数据": rows,
            },
            200,
            "查询按授权维度执行",
        )

    def _query_copy(
        self, copy_id: int, role_code: str, dimensions: list[str]
    ) -> tuple[dict[str, Any] | None, int, str]:
        snapshot = review_snapshot_service.get_copy(copy_id)
        if snapshot is None:
            return None, 404, f"评审副本 {copy_id} 不存在"
        ok, reason = review_snapshot_service.assert_can_view(snapshot, role_code)
        if not ok:
            return None, 403, reason
        valid, illegal = review_snapshot_service.check_dimensions(snapshot, dimensions)
        if not valid:
            return (
                None,
                403,
                f"副本 {snapshot['副本编号']} 冻结范围不含维度：{'、'.join(illegal)}（新增维度对旧副本不可见）",
            )
        rows = self._aggregate(dimensions)
        return (
            {
                "副本编号": snapshot["副本编号"],
                "角色编号": role_code,
                "只读": True,
                "冻结范围版本": snapshot["冻结范围版本"],
                "使用维度": dimensions,
                "行数": len(rows),
                "数据": rows,
            },
            200,
            "只读副本按冻结维度查询",
        )

    def _aggregate(self, dimensions: list[str]) -> list[dict[str, Any]]:
        """按给定维度对销售额求和；维度已在调用前完成授权校验。"""
        buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in store.auth_rows("chart_data"):
            key = tuple(row.get(dim) for dim in dimensions)
            if key not in buckets:
                bucket = {dim: row.get(dim) for dim in dimensions}
                bucket["销售额"] = 0
                buckets[key] = bucket
            buckets[key]["销售额"] += int(row["销售额"])
        return list(buckets.values())

    def filter_dimensions(self, role_code: str, chart_code: str = CHART_ID) -> dict[str, Any]:
        """全局筛选器对当前角色实际暴露的联动维度：筛选器配置 ∩ 角色授权维度。"""
        decision = auth_engine.effective_authorization(chart_code, role_code)
        filter_binding = store.auth_find("filter_binding", 筛选器编号=FILTER_ID)
        configured = list(filter_binding["联动维度"])
        if not decision["可访问"]:
            exposed: list[str] = []
        else:
            exposed = [dim for dim in configured if dim in decision["允许维度"]]
        return {
            "筛选器编号": FILTER_ID,
            "角色编号": role_code,
            "筛选器配置联动维度": configured,
            "角色授权维度": decision["允许维度"],
            "实际暴露维度": exposed,
            "被隐藏维度": [dim for dim in configured if dim not in exposed],
            "授权状态": filter_binding["授权状态"],
        }


chart_query_service = ChartQueryService()
