---
document_id: "DOC-PRODUCT-BASELINE-001"
document_version: "1.0.0"
project_id: "example-project"
document_type: "PRODUCT_BASELINE"
status: "ACTIVE"
applies_to_release: "v1.0.0"
last_updated: "2026-10-27"
supersedes: null
change_summary: "产品功能基线初始版本"
history_reference: null
primary_entrypoint: true
---

# 产品基线 (Product Baseline)

## 1. 产品定位与服务对象
- **服务角色**：
- **统一访问入口**：

## 2. 页面与菜单职责清单 (Menu & Page Responsibilities)
| 页面/菜单 | 路由路径 | 核心职责 | 数据来源 | 状态 |
|:---|:---|:---|:---|:---|
| 首页控制台 | `/` | 平台状态与核心指标总览 | `/health`, `/api/runtime/identity` | 正式生效 |

## 3. 功能特性清单 (Feature Inventory)
- **已交付特性 (Delivered)**：
- **冻结设计决策 (Frozen Decisions)**：严禁在后续迭代中未经 ADR 批准弱化或删除的功能。

## 4. 系统边界与资源所有权 (Resource Ownership)
- **本系统拥有的资源**：
- **外部依赖与调用边界**：

## 5. 验收标准与防退化门禁 (Acceptance Criteria)
