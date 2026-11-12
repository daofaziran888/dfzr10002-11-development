"""图表配置角色授权域的示例数据。

与通用 SEED_ROWS 分开存放：这里的数据围绕主对象「图表配置 CFG-0005」组织，
覆盖团队归属、角色授权、只读副本、看板/筛选器引用与授权核对任务。
"""
from __future__ import annotations

from typing import Any

# 维度常量：全链路（授权、筛选器、查询拦截）都用同一套维度标识
DIM_REGION = "地区"
DIM_CHANNEL = "渠道"
DIM_DATE = "日期"
ALL_DIMENSIONS = [DIM_REGION, DIM_CHANNEL, DIM_DATE]

CHART_ID = "CFG-0005"
PANEL_ID = "DASH-0002"
FILTER_ID = "FILT-0003"
DATASET_ID = "DS-SALES"

AUTH_SEED_ROWS: dict[str, list[dict[str, Any]]] = {
    # 团队树：总公司下设财务、运营、外部评审三个团队
    "team": [
        {"id": 1, "团队编号": "TEAM-ROOT", "团队名称": "总公司", "父团队编号": None},
        {"id": 2, "团队编号": "TEAM-FIN", "团队名称": "财务团队", "父团队编号": "TEAM-ROOT"},
        {"id": 3, "团队编号": "TEAM-OPS", "团队名称": "运营团队", "父团队编号": "TEAM-ROOT"},
        {"id": 4, "团队编号": "TEAM-REVIEW", "团队名称": "外部评审团队", "父团队编号": "TEAM-ROOT"},
    ],
    # 角色按团队归属：主管在总公司，财务/运营分析师各归其队，评审专家归属外部团队
    "role": [
        {"id": 1, "角色编号": "ROLE-ADMIN", "角色名称": "数据主管", "团队编号": "TEAM-ROOT"},
        {"id": 2, "角色编号": "ROLE-FIN", "角色名称": "财务分析师", "团队编号": "TEAM-FIN"},
        {"id": 3, "角色编号": "ROLE-OPS", "角色名称": "运营分析师", "团队编号": "TEAM-OPS"},
        {"id": 4, "角色编号": "ROLE-REVIEWER", "角色名称": "外部评审专家", "团队编号": "TEAM-REVIEW"},
    ],
    # 数据集与维度：发布校验时核对「角色 × 联动维度 × 数据集」组合
    "auth_dataset": [
        {
            "id": 1,
            "数据集编号": DATASET_ID,
            "数据集名称": "销售明细数据集",
            "维度列表": list(ALL_DIMENSIONS),
            "指标列表": ["销售额"],
            "可见团队": ["TEAM-ROOT", "TEAM-FIN", "TEAM-OPS"],
        }
    ],
    "auth_dimension": [
        {"id": 1, "维度编号": "DIM-REGION", "维度名称": DIM_REGION, "数据集编号": DATASET_ID},
        {"id": 2, "维度编号": "DIM-CHANNEL", "维度名称": DIM_CHANNEL, "数据集编号": DATASET_ID},
        {"id": 3, "维度编号": "DIM-DATE", "维度名称": DIM_DATE, "数据集编号": DATASET_ID},
    ],
    # 图表配置主记录：可见范围、可视化图表绑定（坐标轴）、配置版本都挂在主记录上
    "chart_config": [
        {
            "id": 1,
            "图表编号": CHART_ID,
            "图表名称": "销售额趋势图",
            "图表类型": "折线图",
            "数据集编号": DATASET_ID,
            "横轴字段": DIM_DATE,       # 坐标轴绑定属于图表配置主记录
            "纵轴字段": "销售额",
            "图表配置版本": "V1",        # 绑定/发布变更时递增
            "可见范围版本": "SCOPE-V1",  # 可见范围每次调整递增
            "状态": "草稿",
            "授权状态": "已核对",
            "归属团队编号": "TEAM-ROOT",
            "负责人角色": "ROLE-ADMIN",
            "只读": False,
        }
    ],
    # 版本流水：图表配置版本必须可追溯，范围调整与绑定调整分别留痕
    "chart_version": [
        {
            "id": 1,
            "图表编号": CHART_ID,
            "版本号": "V1",
            "范围版本": "SCOPE-V1",
            "变更类型": "初始建档",
            "绑定快照": {"横轴字段": DIM_DATE, "纵轴字段": "销售额", "数据集编号": DATASET_ID},
            "说明": "CFG-0005 初始建档，确定可见范围、可视化图表绑定与配置版本",
            "创建时间": "2026-11-01 09:00",
        }
    ],
    # 可见范围授权：角色维度的多条授权，替代原来的单一绑定关系
    # 财务只能看销售额图表的地区维度；运营只能看渠道维度；主管全权且可编辑
    "chart_grant": [
        {
            "id": 1,
            "图表编号": CHART_ID,
            "团队编号": "TEAM-ROOT",
            "角色编号": "ROLE-ADMIN",
            "允许维度": list(ALL_DIMENSIONS),
            "权限级别": "editor",
            "是否拒绝": False,
            "授权方式": "direct",
            "范围版本": "SCOPE-V1",
            "状态": "生效",
            "创建时间": "2026-11-01 09:00",
        },
        {
            "id": 2,
            "图表编号": CHART_ID,
            "团队编号": "TEAM-FIN",
            "角色编号": None,  # None 表示团队默认授权，团队内角色默认继承
            "允许维度": [DIM_REGION, DIM_DATE],
            "权限级别": "viewer",
            "是否拒绝": False,
            "授权方式": "default",
            "范围版本": "SCOPE-V1",
            "状态": "生效",
            "创建时间": "2026-11-01 09:00",
        },
        {
            "id": 3,
            "图表编号": CHART_ID,
            "团队编号": "TEAM-OPS",
            "角色编号": None,
            "允许维度": [DIM_CHANNEL, DIM_DATE],
            "权限级别": "viewer",
            "是否拒绝": False,
            "授权方式": "default",
            "范围版本": "SCOPE-V1",
            "状态": "生效",
            "创建时间": "2026-11-01 09:00",
        },
    ],
    # 数据看板面板：只引用图表配置，不持有图表主记录，授权状态随图表范围变更刷新
    "panel_binding": [
        {
            "id": 1,
            "面板编号": PANEL_ID,
            "面板名称": "销售作战看板",
            "引用图表编号": CHART_ID,
            "授权状态": "已同步",
            "最近核对时间": "2026-11-01 09:05",
        }
    ],
    # 全局筛选器：联动维度的实际暴露范围按角色与图表授权取交集
    "filter_binding": [
        {
            "id": 1,
            "筛选器编号": FILTER_ID,
            "筛选器名称": "销售全局筛选器",
            "关联图表编号": CHART_ID,
            "联动维度": [DIM_REGION, DIM_CHANNEL],
            "授权状态": "已同步",
            "最近核对时间": "2026-11-01 09:05",
        }
    ],
    # 只读评审副本：创建时冻结维度与范围版本，之后不随在线范围变化
    "review_snapshot": [],
    # 授权核对任务：每次可见范围变更按引用对象逐个生成，结果回写图表与看板
    "check_task": [],
    # 可查询的销售明细：演示越权维度在查询入口被拦截，图表结果不被改变
    "chart_data": [
        {"id": 1, DIM_REGION: "华东", DIM_CHANNEL: "线上", DIM_DATE: "2026-11-01", "销售额": 12000},
        {"id": 2, DIM_REGION: "华东", DIM_CHANNEL: "线下", DIM_DATE: "2026-11-01", "销售额": 8000},
        {"id": 3, DIM_REGION: "华北", DIM_CHANNEL: "线上", DIM_DATE: "2026-11-01", "销售额": 9000},
        {"id": 4, DIM_REGION: "华北", DIM_CHANNEL: "线下", DIM_DATE: "2026-11-02", "销售额": 7000},
        {"id": 5, DIM_REGION: "华南", DIM_CHANNEL: "线上", DIM_DATE: "2026-11-02", "销售额": 11000},
        {"id": 6, DIM_REGION: "华南", DIM_CHANNEL: "线下", DIM_DATE: "2026-11-02", "销售额": 6500},
        {"id": 7, DIM_REGION: "华东", DIM_CHANNEL: "线上", DIM_DATE: "2026-11-03", "销售额": 15000},
        {"id": 8, DIM_REGION: "华北", DIM_CHANNEL: "线下", DIM_DATE: "2026-11-03", "销售额": 7200},
    ],
}
