"""图表配置角色授权域的端到端验证（服务层直驱，无需 HTTP 依赖）。

覆盖：角色继承裁决、越权维度拦截、范围调整联动核对、发布校验、
只读副本冻结、看板授权状态刷新、越权改绑定拒绝等全部题面场景。
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app.services.auth_engine import auth_engine  # noqa: E402
from app.services.chart_config import chart_config_service  # noqa: E402
from app.services.chart_query import chart_query_service  # noqa: E402
from app.services.review_snapshot import review_snapshot_service  # noqa: E402
from app.store import store  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# 1. 主对象三要素先确定：CFG-0005 的可见范围、可视化绑定、配置版本
section("1. 图表配置主记录（主对象三要素）")
master_resp = chart_config_service.get_master()
check("主记录编号为 CFG-0005", master_resp["图表编号"] == "CFG-0005")
check("坐标轴绑定属于图表配置主记录", master_resp["横轴字段"] == "日期" and master_resp["纵轴字段"] == "销售额")
check("初始配置版本为 V1", master_resp["图表配置版本"] == "V1")
check("初始范围版本为 SCOPE-V1", master_resp["可见范围版本"] == "SCOPE-V1")
check("版本流水可追溯", len(chart_config_service.list_versions()) >= 1)

# 2. 三对象授权清单：分别列出可见团队与继承来源，不用全局开关
section("2. CFG-0005 / DASH-0002 / FILT-0003 授权清单")
manifest = chart_config_service.grant_manifest()
check("清单包含三个对象", all(k in manifest for k in ("图表配置", "数据看板面板", "全局筛选器")))
check("面板编号为 DASH-0002", manifest["数据看板面板"]["对象编号"] == "DASH-0002")
check("筛选器编号为 FILT-0003", manifest["全局筛选器"]["对象编号"] == "FILT-0003")
check("三个对象各自携带可见团队", all(manifest[k]["可见团队"] for k in ("图表配置", "数据看板面板", "全局筛选器")))
check("每个角色裁决保留继承来源", all(d["继承来源"] for d in manifest["图表配置"]["角色裁决"] if d["可访问"]))

# 3. 默认角色继承与冲突裁决
section("3. 团队继承与冲突裁决")
fin = auth_engine.effective_authorization("CFG-0005", "ROLE-FIN")
ops = auth_engine.effective_authorization("CFG-0005", "ROLE-OPS")
admin = auth_engine.effective_authorization("CFG-0005", "ROLE-ADMIN")
reviewer = auth_engine.effective_authorization("CFG-0005", "ROLE-REVIEWER")
check("财务角色可见地区维度", fin["可访问"] and "地区" in fin["允许维度"])
check("财务角色不可见渠道维度", "渠道" not in fin["允许维度"])
check("运营角色可见渠道维度", ops["可访问"] and "渠道" in ops["允许维度"])
check("运营角色不可见地区维度", "地区" not in ops["允许维度"])
check("主管为 editor 可改动", admin["权限级别"] == "editor")
check("外部评审默认无权访问在线图表", not reviewer["可访问"])
check("财务授权来源是团队默认继承", fin["裁决说明"] in ("团队默认", "上级继承"))

# 4. 越权维度查询必须拒绝，图表结果不被改变
section("4. 越权筛选拦截（结果必须拒绝）")
ok_result, ok_status, _ = chart_query_service.query_chart(role_code="ROLE-FIN", dimensions=["地区"])
check("财务按地区查询放行", ok_status == 200 and ok_result is not None)
bad_result, bad_status, bad_msg = chart_query_service.query_chart(
    role_code="ROLE-FIN", dimensions=["渠道"]
)
check("财务传渠道维度返回 403", bad_status == 403 and bad_result is None)
check("拒绝说明指出越权维度", "渠道" in bad_msg)
again, _, _ = chart_query_service.query_chart(role_code="ROLE-FIN", dimensions=["地区"])
check("越权请求后图表结果保持不变", again["行数"] == ok_result["行数"])
ops_bad, ops_status, _ = chart_query_service.query_chart(
    role_code="ROLE-OPS", dimensions=["地区", "渠道"]
)
check("运营传地区维度同样 403", ops_status == 403 and ops_bad is None)
rv_result, rv_status, _ = chart_query_service.query_chart(
    role_code="ROLE-REVIEWER", dimensions=["地区"]
)
check("无授权角色查询 403", rv_status == 403 and rv_result is None)

# 5. 筛选器暴露维度按角色裁剪
section("5. 全局筛选器维度暴露")
fin_filter = chart_query_service.filter_dimensions("ROLE-FIN")
ops_filter = chart_query_service.filter_dimensions("ROLE-OPS")
check(
    "财务筛选器只暴露地区、隐藏渠道",
    fin_filter["实际暴露维度"] == ["地区"] and "渠道" in fin_filter["被隐藏维度"],
)
check(
    "运营筛选器只暴露渠道、隐藏地区",
    ops_filter["实际暴露维度"] == ["渠道"] and "地区" in ops_filter["被隐藏维度"],
)

# 6. 可见范围调整 → 生成核对任务 → 看板显示新状态 → 结果回写
section("6. 可见范围调整与相邻模块核对任务")
grants_v2 = [
    {"团队编号": "TEAM-ROOT", "角色编号": "ROLE-ADMIN", "允许维度": ["地区", "渠道", "日期"], "权限级别": "editor"},
    {"团队编号": "TEAM-FIN", "角色编号": None, "允许维度": ["日期"], "权限级别": "viewer"},
    {"团队编号": "TEAM-OPS", "角色编号": None, "允许维度": ["渠道", "日期"], "权限级别": "viewer"},
]
tighten, errors = chart_config_service.update_scope(
    grants_v2, operator_role="ROLE-ADMIN", remark="主管收紧财务可见范围"
)
check("范围调整成功且无错误", tighten is not None and not errors, str(errors))
check("范围版本递增为 SCOPE-V2", tighten and tighten["范围版本"] == "SCOPE-V2")
check("生成两个核对任务（面板+筛选器）", tighten and len(tighten["生成核对任务"]) == 2)
panel = store.auth_find("panel_binding")
filter_binding = store.auth_find("filter_binding")
check("调整后看板面板授权状态为待核对", panel["授权状态"] == "待核对")
check("调整后筛选器授权状态为待核对", filter_binding["授权状态"] == "待核对")
check("图表主记录授权状态为待核对", chart_config_service.get_master()["授权状态"] == "待核对")
_, fin_after_status, _ = chart_query_service.query_chart(
    role_code="ROLE-FIN", dimensions=["地区"]
)
check("收紧后财务查地区立即被拒", fin_after_status == 403)
forbidden_result, forbidden_errors = chart_config_service.update_scope(
    grants_v2, operator_role="ROLE-FIN"
)
check("越权角色调整范围被拒", forbidden_result is None and forbidden_errors)
tasks = [t for t in chart_config_service.list_check_tasks() if t["状态"] == "待核对"]
for task in tasks:
    done, message = chart_config_service.complete_check_task(
        task["id"], f"{task['对象编号']} 可见团队与新范围一致", operator_role="ROLE-ADMIN"
    )
    check(f"核对任务 {task['任务编号']} 回写成功", done is not None, message)
check("核对完成后看板恢复已同步", store.auth_find("panel_binding")["授权状态"] == "已同步")
check("核对完成后图表恢复已核对", chart_config_service.get_master()["授权状态"] == "已核对")
check(
    "核对任务与可见团队保持同步",
    all(t["状态"] == "已完成" for t in chart_config_service.list_check_tasks()),
)

# 7. 只读评审副本：冻结维度，收紧不回溯，新增维度不可见
section("7. 只读评审副本快照")
copy, copy_errors = review_snapshot_service.create_copy(
    operator_role="ROLE-ADMIN",
    target_role="ROLE-REVIEWER",
    freeze_dimensions=["地区", "日期"],
)
check("评审副本创建成功", copy is not None and not copy_errors, str(copy_errors))
check("副本冻结范围版本为 SCOPE-V2", copy and copy["冻结范围版本"] == "SCOPE-V2")
check("副本为只读", copy and copy["只读"] is True)
# 在线范围放宽：财务恢复地区，运营新增地区（对在线配置生效）
grants_v3 = [
    {"团队编号": "TEAM-ROOT", "角色编号": "ROLE-ADMIN", "允许维度": ["地区", "渠道", "日期"], "权限级别": "editor"},
    {"团队编号": "TEAM-FIN", "角色编号": None, "允许维度": ["地区", "日期"], "权限级别": "viewer"},
    {"团队编号": "TEAM-OPS", "角色编号": None, "允许维度": ["地区", "渠道", "日期"], "权限级别": "viewer"},
]
chart_config_service.update_scope(grants_v3, operator_role="ROLE-ADMIN", remark="放宽在线范围")
leak_result, leak_status, leak_msg = chart_query_service.query_chart(
    role_code="ROLE-REVIEWER", dimensions=["渠道"], copy_id=copy["id"]
)
check("旧副本不能访问新增维度（403）", leak_status == 403 and "冻结范围不含" in leak_msg)
copy_ok, copy_ok_status, _ = chart_query_service.query_chart(
    role_code="ROLE-REVIEWER", dimensions=["地区"], copy_id=copy["id"]
)
check("旧副本仍可按冻结维度查询", copy_ok_status == 200 and copy_ok is not None)
check("旧副本保持原范围版本 SCOPE-V2", copy_ok and copy_ok["冻结范围版本"] == "SCOPE-V2")
ok_edit, edit_msg = review_snapshot_service.attempt_edit(copy, "ROLE-ADMIN")
check("主管也不能修改只读副本", ok_edit is False and "只读" in edit_msg)
ok_edit2, _ = review_snapshot_service.attempt_edit(copy, "ROLE-REVIEWER")
check("评审角色修改副本被拒", ok_edit2 is False)
_, copy_forbidden_status, _ = chart_query_service.query_chart(
    role_code="ROLE-OPS", dimensions=["地区"], copy_id=copy["id"]
)
check("非评审名单角色访问副本 403", copy_forbidden_status == 403)
# 外部评审仍然不能直接访问在线图表（副本不扩大在线权限）
_, live_status, _ = chart_query_service.query_chart(
    role_code="ROLE-REVIEWER", dimensions=["地区"]
)
check("评审角色在线图表仍无授权", live_status == 403)

# 8. 发布校验：角色 × 联动维度 × 数据集组合
section("8. 发布校验")
# 放宽范围产生的新核对任务未回写时，发布必须被拦截（防止未核对的授权流出）
publish_pending = chart_config_service.publish_validate(operator_role="ROLE-ADMIN")
check("存在待核对任务时发布被拦截", publish_pending["通过"] is False and publish_pending["待核对任务数"] > 0)
for task in [t for t in chart_config_service.list_check_tasks() if t["状态"] == "待核对"]:
    chart_config_service.complete_check_task(
        task["id"], f"{task['对象编号']} 放宽范围复核通过", operator_role="ROLE-ADMIN"
    )
publish = chart_config_service.publish_validate(operator_role="ROLE-ADMIN")
check("核对完成后组合校验通过", publish["通过"] is True)
check("逐角色列出组合校验项", len(publish["校验项"]) >= 2)
publish_forbidden = chart_config_service.publish_validate(operator_role="ROLE-FIN")
check("越权角色不能发起发布校验", publish_forbidden["通过"] is False)

# 9. 图表绑定属于主记录：越权角色只读不能改，改动递增配置版本
section("9. 可视化图表绑定与配置版本")
bind_deny, bind_msg = chart_config_service.update_binding(
    横轴字段="渠道", 纵轴字段="销售额", operator_role="ROLE-FIN"
)
check("越权角色改绑定被拒", bind_deny is None and "不能改动" in bind_msg)
bind_ok, bind_message = chart_config_service.update_binding(
    横轴字段="渠道", 纵轴字段="销售额", operator_role="ROLE-ADMIN"
)
check("主管改绑定成功", bind_ok is not None)
check("配置版本递增为 V2", bind_ok and bind_ok["图表配置版本"] == "V2")
check("版本流水记录绑定调整", any(v["变更类型"] == "绑定调整" for v in chart_config_service.list_versions()))
check(
    "看板面板只保存引用关系，不替代主记录",
    store.auth_find("panel_binding")["引用图表编号"] == "CFG-0005",
)

# 10. 显式拒绝与就近裁决
section("10. 显式拒绝优先与就近覆盖")
# 在 TEAM-ROOT 给财务角色加一条显式拒绝（跨团队直接授权模拟冲突），应一票否决
store.auth_rows("chart_grant").append(
    {
        "id": store.next_auth_id("chart_grant"),
        "图表编号": "CFG-0005",
        "团队编号": "TEAM-FIN",
        "角色编号": "ROLE-FIN",
        "允许维度": [],
        "权限级别": "viewer",
        "是否拒绝": True,
        "授权方式": "direct",
        "范围版本": "SCOPE-V3",
        "状态": "生效",
        "创建时间": "2026-11-10 10:00",
    }
)
denied = auth_engine.effective_authorization("CFG-0005", "ROLE-FIN")
check("显式拒绝一票否决团队默认允许", not denied["可访问"] and denied["权限级别"] == "deny")
check("裁决轨迹保留显式拒绝来源", any(t["来源类型"] == "显式拒绝" for t in denied["继承来源"]))

# 11. 数据集外维度在授权入口即被拒绝，非法组合进不了发布流程
section("11. 数据集外维度与非法授权拦截")
bad_grants = [
    {"团队编号": "TEAM-OPS", "角色编号": None, "允许维度": ["客户手机号"], "权限级别": "viewer"},
]
_, bad_errors = chart_config_service.update_scope(bad_grants, operator_role="ROLE-ADMIN")
check("数据集外维度被拒绝写入授权", bad_errors and "数据集 DS-SALES 之外" in bad_errors[0])
dup_grants = grants_v3 + [
    {"团队编号": "TEAM-OPS", "角色编号": None, "允许维度": ["渠道"], "权限级别": "viewer"}
]
_, dup_errors = chart_config_service.update_scope(dup_grants, operator_role="ROLE-ADMIN")
check("同团队同角色重复授权被拒绝", dup_errors and "重复" in dup_errors[0])

# 12. 就近覆盖：在角色所属团队放直接授权，可覆盖上级默认授权
section("12. 就近原则覆盖默认继承")
overridden, override_errors = chart_config_service.update_scope(
    grants_v3 + [
        {"团队编号": "TEAM-OPS", "角色编号": "ROLE-OPS", "允许维度": ["渠道"], "权限级别": "viewer"}
    ],
    operator_role="ROLE-ADMIN",
)
check("带直接授权的范围调整成功", overridden is not None and not override_errors, str(override_errors))
ops_direct = auth_engine.effective_authorization("CFG-0005", "ROLE-OPS")
check("角色直接授权就近覆盖团队默认", ops_direct["允许维度"] == ["渠道"])
check("覆盖来源标注为直接授权", ops_direct["裁决说明"] == "直接授权")

print(f"\n结果：通过 {PASS} 项，失败 {FAIL} 项")
sys.exit(1 if FAIL else 0)
