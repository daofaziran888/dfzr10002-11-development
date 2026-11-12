"""只读评审副本服务。

副本在创建瞬间冻结三样东西：图表配置版本、可见范围版本、可见维度集合。
冻结之后：
  - 主管收紧在线范围，旧副本保持原范围（快照独立，不随主记录变化）；
  - 在线范围新增维度，副本不能访问新增维度（冻结集合不扩容）；
  - 副本永远只读，受控维度与绑定一律拒绝修改。
"""
from __future__ import annotations

from typing import Any

from app.services.auth_engine import auth_engine
from app.store import store

from app.seed_auth import CHART_ID


class ReviewSnapshotService:
    def create_copy(
        self,
        *,
        operator_role: str,
        target_role: str = "ROLE-REVIEWER",
        freeze_dimensions: list[str] | None = None,
        chart_code: str = CHART_ID,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if not auth_engine.can_edit(chart_code, operator_role):
            return None, [f"角色 {operator_role} 无编辑权，不能生成评审副本"]
        target = auth_engine.get_role(target_role)
        if target is None:
            return None, [f"目标角色 {target_role} 不存在"]

        master = store.auth_find("chart_config", 图表编号=chart_code)
        # 默认冻结：目标角色当前在线可见维度与图表维度的交集；外部评审若在线无权，则为空集，
        # 必须由主管显式指定冻结维度，避免无意扩大授权。
        if freeze_dimensions is None:
            freeze_dimensions = auth_engine.allowed_dimensions(chart_code, target_role)
        dataset = store.auth_find("auth_dataset", 数据集编号=master["数据集编号"])
        illegal = [dim for dim in freeze_dimensions if dim not in dataset["维度列表"]]
        if illegal:
            return None, [f"冻结维度超出数据集范围：{'、'.join(illegal)}"]

        existing = store.auth_rows("review_snapshot")
        copy_code = f"COPY-{len(existing) + 1:04d}"
        snapshot = {
            "id": store.next_auth_id("review_snapshot"),
            "副本编号": copy_code,
            "源图表编号": chart_code,
            "图表名称": master["图表名称"],
            "目标角色编号": target_role,
            "目标团队编号": target["团队编号"],
            "冻结配置版本": master["图表配置版本"],
            "冻结范围版本": master["可见范围版本"],
            "冻结维度": list(freeze_dimensions),
            "冻结绑定": {
                "横轴字段": master["横轴字段"],
                "纵轴字段": master["纵轴字段"],
            },
            "只读": True,
            "状态": "评审中",
            "创建时间": store.auth_rows("chart_version")[-1]["创建时间"],
        }
        store.auth_rows("review_snapshot").append(snapshot)
        return snapshot, []

    def list_copies(self) -> list[dict[str, Any]]:
        return store.auth_rows("review_snapshot")

    def get_copy(self, copy_id: int) -> dict[str, Any] | None:
        return store.auth_find("review_snapshot", id=copy_id)

    def assert_can_view(self, snapshot: dict[str, Any], role_code: str) -> tuple[bool, str]:
        if auth_engine.can_edit(CHART_ID, role_code):
            return True, "编辑角色可查看全部副本"
        if snapshot["目标角色编号"] == role_code:
            return True, "副本目标角色只读查看"
        return False, f"角色 {role_code} 不在副本 {snapshot['副本编号']} 的评审名单内"

    def attempt_edit(self, snapshot: dict[str, Any], role_code: str) -> tuple[bool, str]:
        """任何角色对评审副本的受控维度修改都必须被拒绝。"""
        ok, _ = self.assert_can_view(snapshot, role_code)
        if not ok:
            return False, f"角色 {role_code} 无权访问该副本"
        return False, f"副本 {snapshot['副本编号']} 为只读快照，受控维度与绑定不能修改"

    def check_dimensions(
        self, snapshot: dict[str, Any], requested: list[str]
    ) -> tuple[bool, list[str]]:
        frozen = set(snapshot["冻结维度"])
        illegal = [dim for dim in requested if dim not in frozen]
        return not illegal, illegal


review_snapshot_service = ReviewSnapshotService()
