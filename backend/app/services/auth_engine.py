"""角色授权裁决引擎。

裁决规则（本系统的核心约定）：

1. 团队继承：角色归属团队，沿父团队链向上继承上级团队的「默认授权」。
2. 显式优先：角色编号不为空的直接授权（direct）优先于团队默认授权（default）。
3. 冲突裁决：沿团队链从近到远查找，显式拒绝（deny）一票否决，且级别高于允许；
   同为允许时取「最近的一条」生效，默认继承可被就近授权覆盖。
4. 权限级别：editor（可改绑定/受控维度）高于 viewer（只读）；未命中任何授权即无权访问。
"""
from __future__ import annotations

from typing import Any

from app.seed_auth import CHART_ID
from app.store import store

EDITOR = "editor"
VIEWER = "viewer"
DENY = "deny"


class AuthEngine:
    def get_team(self, team_code: str) -> dict[str, Any] | None:
        return store.auth_find("team", 团队编号=team_code)

    def get_role(self, role_code: str) -> dict[str, Any] | None:
        return store.auth_find("role", 角色编号=role_code)

    def team_chain(self, team_code: str) -> list[dict[str, Any]]:
        """从角色所属团队向上到根，顺序：自身团队 → 父团队 → … → 根。"""
        chain: list[dict[str, Any]] = []
        current = self.get_team(team_code)
        guard = 0
        while current is not None and guard < 32:
            chain.append(current)
            parent_code = current.get("父团队编号")
            current = self.get_team(parent_code) if parent_code else None
            guard += 1
        return chain

    def active_grants(self, chart_code: str) -> list[dict[str, Any]]:
        return [
            row
            for row in store.auth_rows("chart_grant")
            if row.get("图表编号") == chart_code and row.get("状态") == "生效"
        ]

    def effective_authorization(
        self, chart_code: str, role_code: str
    ) -> dict[str, Any]:
        """计算某个角色对某张图表的有效授权，并保留继承来源，便于核对清单追溯。"""
        role = self.get_role(role_code)
        if role is None:
            return self._denied(chart_code, role_code, None, "角色不存在")
        team_code = role["团队编号"]
        chain = self.team_chain(team_code)
        grants = self.active_grants(chart_code)

        traces: list[dict[str, Any]] = []
        chosen: dict[str, Any] | None = None
        denied_by: dict[str, Any] | None = None

        # 第一轮：最近的显式拒绝优先（沿团队链由近及远，命中即停）
        # 直接拒绝只针对本人；团队默认拒绝（角色编号为空）对团队内所有角色生效
        for index, team in enumerate(chain):
            for grant in grants:
                if grant["团队编号"] != team["团队编号"] or not grant.get("是否拒绝"):
                    continue
                if grant.get("角色编号") in (None, role_code):
                    denied_by = grant
                    traces.append(self._trace(grant, team, index, "显式拒绝"))
                    break
            if denied_by is not None:
                break

        # 第二轮：未被拒绝时，取最近一条允许授权。
        # 角色直接授权（带角色编号）只对该角色本人有效；
        # 团队默认授权（角色编号为空）才可被本团队及下级团队角色继承。
        if denied_by is None:
            for index, team in enumerate(chain):
                team_candidates = [
                    grant
                    for grant in grants
                    if grant["团队编号"] == team["团队编号"] and not grant.get("是否拒绝")
                ]
                direct = [g for g in team_candidates if g.get("角色编号") == role_code]
                inherited = [g for g in team_candidates if g.get("角色编号") is None]
                picked = direct[0] if direct else (inherited[0] if inherited else None)
                if picked is None:
                    continue
                chosen = picked
                if direct:
                    inherit = "直接授权"
                elif index == 0:
                    inherit = "团队默认"
                else:
                    inherit = "上级继承"
                traces.append(self._trace(picked, team, index, inherit))
                break

        if denied_by is not None:
            return {
                "图表编号": chart_code,
                "角色编号": role_code,
                "团队编号": team_code,
                "可访问": False,
                "权限级别": DENY,
                "允许维度": [],
                "继承来源": traces,
                "裁决说明": "命中显式拒绝授权，拒绝优先于一切允许",
            }
        if chosen is None:
            return {
                "图表编号": chart_code,
                "角色编号": role_code,
                "团队编号": team_code,
                "可访问": False,
                "权限级别": DENY,
                "允许维度": [],
                "继承来源": [],
                "裁决说明": "团队链上没有命中任何授权，默认无权访问",
            }
        return {
            "图表编号": chart_code,
            "角色编号": role_code,
            "团队编号": team_code,
            "可访问": True,
            "权限级别": chosen["权限级别"],
            "允许维度": list(chosen.get("允许维度", [])),
            "范围版本": chosen.get("范围版本"),
            "继承来源": traces,
            "裁决说明": traces[0]["来源类型"] if traces else "直接授权",
        }

    def allowed_dimensions(self, chart_code: str, role_code: str) -> list[str]:
        decision = self.effective_authorization(chart_code, role_code)
        return decision["允许维度"] if decision["可访问"] else []

    def can_edit(self, chart_code: str, role_code: str) -> bool:
        decision = self.effective_authorization(chart_code, role_code)
        return decision["可访问"] and decision["权限级别"] == EDITOR

    def check_dimensions(
        self, chart_code: str, role_code: str, requested: list[str]
    ) -> tuple[bool, list[str]]:
        """越权维度校验：返回（是否全部合法，越权维度清单）。"""
        allowed = set(self.allowed_dimensions(chart_code, role_code))
        illegal = [dim for dim in requested if dim not in allowed]
        return not illegal, illegal

    def all_role_decisions(self, chart_code: str = CHART_ID) -> list[dict[str, Any]]:
        return [
            self.effective_authorization(chart_code, role["角色编号"])
            for role in store.auth_rows("role")
        ]

    def _trace(self, grant: dict[str, Any], team: dict[str, Any], depth: int, source: str) -> dict[str, Any]:
        return {
            "团队编号": team["团队编号"],
            "团队名称": team["团队名称"],
            "角色编号": grant.get("角色编号"),
            "授权方式": grant.get("授权方式"),
            "权限级别": grant.get("权限级别"),
            "允许维度": list(grant.get("允许维度", [])),
            "来源类型": source,
            "继承层级": depth,
            "范围版本": grant.get("范围版本"),
        }

    def _denied(self, chart_code: str, role_code: str, team_code: str | None, reason: str) -> dict[str, Any]:
        return {
            "图表编号": chart_code,
            "角色编号": role_code,
            "团队编号": team_code,
            "可访问": False,
            "权限级别": DENY,
            "允许维度": [],
            "继承来源": [],
            "裁决说明": reason,
        }


auth_engine = AuthEngine()
