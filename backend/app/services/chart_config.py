"""图表配置主服务。

主对象是图表配置：可见范围、可视化图表绑定（坐标轴）、配置版本都以图表配置为主记录；
数据看板只引用图表配置，不替代主记录。每次可见范围变更会：
  1. 递增范围版本并记录版本流水；
  2. 让旧授权失效、写入新授权；
  3. 对相邻模块（看板面板、全局筛选器）逐个生成授权核对任务；
  4. 看板/筛选器授权状态先置为「待核对」，任务结果回写后再恢复同步。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.seed_auth import (
    ALL_DIMENSIONS,
    CHART_ID,
    DATASET_ID,
    FILTER_ID,
    PANEL_ID,
)
from app.services.auth_engine import EDITOR, VIEWER, auth_engine
from app.store import store

GRANT_LEVELS = {EDITOR, VIEWER}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _next_scope_version(current: str) -> str:
    prefix = "SCOPE-V"
    if current and current.startswith(prefix):
        try:
            return f"{prefix}{int(current.removeprefix(prefix)) + 1}"
        except ValueError:
            pass
    return "SCOPE-V2"


def _next_config_version(current: str) -> str:
    if current and current.startswith("V"):
        try:
            return f"V{int(current.removeprefix('V')) + 1}"
        except ValueError:
            pass
    return "V2"


class ChartConfigService:
    # ---------- 主记录读取 ----------
    def get_master(self, chart_code: str = CHART_ID) -> dict[str, Any]:
        master = store.auth_find("chart_config", 图表编号=chart_code)
        if master is None:
            raise KeyError(f"图表配置 {chart_code} 不存在")
        return master

    def list_versions(self, chart_code: str = CHART_ID) -> list[dict[str, Any]]:
        return store.auth_find_all("chart_version", 图表编号=chart_code)

    # ---------- 授权清单 ----------
    def grant_manifest(self, chart_code: str = CHART_ID) -> dict[str, Any]:
        """三对象授权清单：CFG-0005、DASH-0002、FILT-0003 分别列可见团队与继承来源。"""
        decisions = auth_engine.all_role_decisions(chart_code)
        chart_teams = self._visible_teams(decisions)

        panel = store.auth_find("panel_binding", 面板编号=PANEL_ID)
        filter_binding = store.auth_find("filter_binding", 筛选器编号=FILTER_ID)
        # 面板/筛选器只是引用方，可见团队与角色裁决均来自图表主记录，不另设全局开关
        panel_decisions = [
            {**decision, "对象编号": PANEL_ID, "对象类型": "数据看板面板"}
            for decision in decisions
            if decision["可访问"]
        ]
        filter_decisions = []
        for decision in decisions:
            if not decision["可访问"]:
                continue
            exposed = [
                dim
                for dim in filter_binding["联动维度"]
                if dim in decision["允许维度"]
            ]
            filter_decisions.append(
                {
                    **decision,
                    "对象编号": FILTER_ID,
                    "对象类型": "全局筛选器",
                    "实际暴露维度": exposed,
                }
            )
        return {
            "图表编号": chart_code,
            "范围版本": self.get_master(chart_code)["可见范围版本"],
            "图表配置": {
                "对象编号": chart_code,
                "对象类型": "图表配置主记录",
                "可见团队": chart_teams,
                "角色裁决": decisions,
            },
            "数据看板面板": {
                "对象编号": PANEL_ID,
                "对象类型": "数据看板面板",
                "引用图表编号": chart_code,
                "授权状态": panel["授权状态"],
                "可见团队": chart_teams,
                "角色裁决": panel_decisions,
            },
            "全局筛选器": {
                "对象编号": FILTER_ID,
                "对象类型": "全局筛选器",
                "关联图表编号": chart_code,
                "授权状态": filter_binding["授权状态"],
                "可见团队": chart_teams,
                "角色裁决": filter_decisions,
            },
        }

    def _visible_teams(self, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        team_map = {team["团队编号"]: team for team in store.auth_rows("team")}
        visible: dict[str, dict[str, Any]] = {}
        for decision in decisions:
            if not decision["可访问"]:
                continue
            team = team_map.get(decision["团队编号"])
            if team is None:
                continue
            visible.setdefault(
                team["团队编号"],
                {"团队编号": team["团队编号"], "团队名称": team["团队名称"], "角色": []},
            )
            visible[team["团队编号"]]["角色"].append(
                {
                    "角色编号": decision["角色编号"],
                    "权限级别": decision["权限级别"],
                    "允许维度": decision["允许维度"],
                    "继承来源": decision["裁决说明"],
                }
            )
        return list(visible.values())

    # ---------- 可见范围变更 ----------
    def update_scope(
        self,
        grants: list[dict[str, Any]],
        *,
        operator_role: str,
        remark: str = "",
        chart_code: str = CHART_ID,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        master = self.get_master(chart_code)
        if not auth_engine.can_edit(chart_code, operator_role):
            return None, [f"角色 {operator_role} 只有查看权或无授权，不能调整可见范围"]

        errors = self._validate_grants(grants)
        if errors:
            return None, errors

        new_scope_version = _next_scope_version(master["可见范围版本"])
        now = _now()

        # 旧授权整体失效，新授权携带新范围版本生效（保留历史可追溯）
        for grant in store.auth_find_all("chart_grant", 图表编号=chart_code):
            grant["状态"] = "已失效"
        for item in grants:
            store.auth_rows("chart_grant").append(
                {
                    "id": store.next_auth_id("chart_grant"),
                    "图表编号": chart_code,
                    "团队编号": item["团队编号"],
                    "角色编号": item.get("角色编号"),
                    "允许维度": list(item["允许维度"]),
                    "权限级别": item["权限级别"],
                    "是否拒绝": bool(item.get("是否拒绝", False)),
                    "授权方式": item.get("授权方式", "direct" if item.get("角色编号") else "default"),
                    "范围版本": new_scope_version,
                    "状态": "生效",
                    "创建时间": now,
                }
            )

        master["可见范围版本"] = new_scope_version
        master["授权状态"] = "待核对"
        self._append_version(
            master, "可见范围调整", new_scope_version, remark or "可见范围变更，触发相邻模块授权核对", now
        )
        tasks = self._spawn_check_tasks(chart_code, new_scope_version, now)
        return {
            "图表编号": chart_code,
            "范围版本": new_scope_version,
            "授权状态": master["授权状态"],
            "生成核对任务": tasks,
        }, []

    def _validate_grants(self, grants: list[dict[str, Any]]) -> list[str]:
        errors: list[str] = []
        team_codes = {team["团队编号"] for team in store.auth_rows("team")}
        role_codes = {role["角色编号"] for role in store.auth_rows("role")}
        if not grants:
            return ["授权清单不能为空，不能用全局开关替代逐角色授权"]
        seen: set[tuple[str, str | None]] = set()
        for index, item in enumerate(grants, start=1):
            team_code = item.get("团队编号")
            role_code = item.get("角色编号")
            if team_code not in team_codes:
                errors.append(f"第{index}条授权的团队 {team_code} 不存在")
                continue
            if role_code is not None and role_code not in role_codes:
                errors.append(f"第{index}条授权的角色 {role_code} 不存在")
            if item.get("权限级别") not in GRANT_LEVELS:
                errors.append(f"第{index}条授权级别必须是 editor 或 viewer")
            illegal = [dim for dim in item.get("允许维度", []) if dim not in ALL_DIMENSIONS]
            if illegal:
                errors.append(f"第{index}条授权包含数据集 {DATASET_ID} 之外的维度：{'、'.join(illegal)}")
            key = (team_code, role_code)
            if key in seen:
                errors.append(f"第{index}条与前面的团队/角色授权重复：{key}")
            seen.add(key)
        return errors

    def _spawn_check_tasks(self, chart_code: str, scope_version: str, now: str) -> list[dict[str, Any]]:
        specs = [
            ("数据看板面板", PANEL_ID, "panel_binding"),
            ("全局筛选器", FILTER_ID, "filter_binding"),
        ]
        created: list[dict[str, Any]] = []
        for object_type, object_code, table in specs:
            binding = store.auth_find(table)
            if binding is not None:
                binding["授权状态"] = "待核对"
            task = {
                "id": store.next_auth_id("check_task"),
                "任务编号": f"CHK-{scope_version}-{object_code}",
                "图表编号": chart_code,
                "对象类型": object_type,
                "对象编号": object_code,
                "范围版本": scope_version,
                "状态": "待核对",
                "核对结论": "",
                "创建时间": now,
                "完成时间": None,
            }
            store.auth_rows("check_task").append(task)
            created.append(task["任务编号"])
        return created

    # ---------- 核对任务结果回写 ----------
    def complete_check_task(
        self, task_id: int, conclusion: str, *, operator_role: str
    ) -> tuple[dict[str, Any] | None, str]:
        if not auth_engine.can_edit(CHART_ID, operator_role):
            return None, f"角色 {operator_role} 无权回写核对任务"
        task = store.auth_find("check_task", id=task_id)
        if task is None:
            return None, f"核对任务 {task_id} 不存在"
        if task["状态"] == "已完成":
            return None, "该任务已完成，不能重复回写"
        task["状态"] = "已完成"
        task["核对结论"] = conclusion
        task["完成时间"] = _now()

        table = "panel_binding" if task["对象类型"] == "数据看板面板" else "filter_binding"
        binding = store.auth_find(table)
        if binding is not None:
            binding["授权状态"] = "已同步"
            binding["最近核对时间"] = task["完成时间"]

        # 所有任务回写完毕后，图表主记录与看板面板才恢复「已核对/已同步」
        pending = store.auth_find_all("check_task", 图表编号=CHART_ID, 状态="待核对")
        master = self.get_master(CHART_ID)
        if not pending:
            master["授权状态"] = "已核对"
        return task, "核对结果已同步回图表配置与引用对象"

    def list_check_tasks(self, scope_version: str | None = None) -> list[dict[str, Any]]:
        rows = store.auth_rows("check_task")
        if scope_version:
            rows = [row for row in rows if row.get("范围版本") == scope_version]
        return rows

    # ---------- 发布校验 ----------
    def publish_validate(
        self, chart_code: str = CHART_ID, *, operator_role: str = "ROLE-ADMIN"
    ) -> dict[str, Any]:
        """发布时校验「角色 × 联动维度 × 数据集」组合，任一越权组合则拒绝发布。"""
        master = self.get_master(chart_code)
        dataset = store.auth_find("auth_dataset", 数据集编号=master["数据集编号"])
        checks: list[dict[str, Any]] = []
        passed = True

        if not auth_engine.can_edit(chart_code, operator_role):
            return {
                "通过": False,
                "图表编号": chart_code,
                "校验项": checks,
                "错误": [f"角色 {operator_role} 无编辑权，不能发起发布校验"],
            }

        for decision in auth_engine.all_role_decisions(chart_code):
            if not decision["可访问"]:
                continue
            # 维度必须在数据集维度集合内
            out_of_dataset = [
                dim for dim in decision["允许维度"] if dim not in dataset["维度列表"]
            ]
            # 筛选器联动维度对该角色的实际暴露必须落在授权维度内（防御性不变量）；
            # 配置中存在但被角色范围隐藏的维度属于预期裁剪，记为信息项，不算越权
            filter_binding = store.auth_find("filter_binding", 关联图表编号=chart_code)
            exposed_link = [
                dim
                for dim in filter_binding["联动维度"]
                if dim in decision["允许维度"]
            ]
            hidden_link = [
                dim
                for dim in filter_binding["联动维度"]
                if dim not in decision["允许维度"]
            ]
            illegal_exposure = [dim for dim in exposed_link if dim not in decision["允许维度"]]
            ok = not out_of_dataset and not illegal_exposure
            passed = passed and ok
            checks.append(
                {
                    "角色编号": decision["角色编号"],
                    "团队编号": decision["团队编号"],
                    "权限级别": decision["权限级别"],
                    "授权维度": decision["允许维度"],
                    "数据集维度": dataset["维度列表"],
                    "筛选器实际暴露": exposed_link,
                    "筛选器隐藏维度": hidden_link,
                    "越权联动维度": illegal_exposure,
                    "数据集外维度": out_of_dataset,
                    "通过": ok,
                }
            )

        pending_tasks = store.auth_find_all("check_task", 状态="待核对")
        if pending_tasks:
            passed = False
        result = {
            "通过": passed,
            "图表编号": chart_code,
            "当前配置版本": master["图表配置版本"],
            "待核对任务数": len(pending_tasks),
            "校验项": checks,
            "错误": [] if passed else ["存在越权维度组合或未完成的授权核对任务，禁止发布"],
        }
        return result

    # ---------- 绑定调整（属于图表配置主记录） ----------
    def update_binding(
        self,
        *,
        横轴字段: str,
        纵轴字段: str,
        operator_role: str,
        chart_code: str = CHART_ID,
    ) -> tuple[dict[str, Any] | None, str]:
        master = self.get_master(chart_code)
        if not auth_engine.can_edit(chart_code, operator_role):
            return None, f"角色 {operator_role} 只能查看不能改动，受控维度与坐标轴绑定拒绝修改"
        dataset = store.auth_find("auth_dataset", 数据集编号=master["数据集编号"])
        if 横轴字段 not in dataset["维度列表"]:
            return None, f"横轴字段 {横轴字段} 不在数据集 {dataset['数据集编号']} 维度内"
        if 纵轴字段 not in dataset["指标列表"]:
            return None, f"纵轴字段 {纵轴字段} 不在数据集 {dataset['数据集编号']} 指标内"
        master["横轴字段"] = 横轴字段
        master["纵轴字段"] = 纵轴字段
        new_version = _next_config_version(master["图表配置版本"])
        master["图表配置版本"] = new_version
        now = _now()
        self._append_version(master, "绑定调整", master["可见范围版本"], "坐标轴绑定变更", now)
        return master, f"图表绑定已更新，配置版本递增为 {new_version}；看板仅引用主记录无需改动"

    def _append_version(
        self, master: dict[str, Any], change_type: str, scope_version: str, note: str, now: str
    ) -> None:
        store.auth_rows("chart_version").append(
            {
                "id": store.next_auth_id("chart_version"),
                "图表编号": master["图表编号"],
                "版本号": master["图表配置版本"],
                "范围版本": scope_version,
                "变更类型": change_type,
                "绑定快照": {
                    "横轴字段": master["横轴字段"],
                    "纵轴字段": master["纵轴字段"],
                    "数据集编号": master["数据集编号"],
                },
                "说明": note,
                "创建时间": now,
            }
        )


chart_config_service = ChartConfigService()
