# STD-035 文档体系迁移指南 (STD-035 Documentation Migration Guide)

## 1. 迁移目标
帮助已有受管工程平滑升级至 STD-035 规范，实现：
1. 统一维护最新全量文档事实源（蓝图、产品基线、架构）。
2. 将旧版本碎片化文档、验收记录移动至 `docs/archive/<VERSION>/`，杜绝丢失历史决策。
3. 为正式文档添加 YAML Frontmatter 元数据头并通过自动化校验。
4. 建立 `docs/DOCUMENT-INDEX.md` 作为项目主入口。

## 2. 四步迁移法
### Step 1: 资产盘点 (Inventory)
扫描现有 `docs/` 下的所有文档，统计其类型、版本、是否包含冻结决策或过时内容。

### Step 2: 凝练权威最新文档 (Consolidate Living Docs)
将散落的多个增量报告正文合并入统一权威入口（如 `docs/PRODUCT-BASELINE.md`），确保没有遗漏已交付的产品职责。

### Step 3: 归档历史快照 (Archive Historical Snapshots)
创建 `docs/archive/<OLD_VERSION>/` 目录，将历史版本文档归档，修改其元数据 `status: "ARCHIVED"`, `primary_entrypoint: false`。

### Step 4: 建立索引与门禁测试 (Index & Verification)
创建 `docs/DOCUMENT-INDEX.md`，运行规范检查脚本验证元数据合规性。
