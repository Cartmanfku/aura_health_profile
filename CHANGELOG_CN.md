# 更新日志

English: [`CHANGELOG.md`](CHANGELOG.md).

**aura_health_profile** 的用户可见变更记录在此（简体中文）。`SKILL.md` / `SKILL_CN.md` frontmatter 中的 `version` 应与最新条目一致。每个版本请与 `CHANGELOG.md` 保持同步。

## [1.1.0] - 2026-04-21

### 新增

- **PDF 解析**：支持 PDF 文档；将 PDF **每页转为图片**，由图片理解模型逐页理解，长文档可**合并为 bundle** 后再参与档案构建。
- **档案构建双模式**：**快速合并**（`build_profile.py` / `update_profile.py`）与**分期汇总**（`build_profile_sharded.py` / `update_profile_sharded.py`）。多年累积、或图片与 PDF 较多时，推荐使用**分期汇总**。

### 变更

- **Markdown → PDF**：升级 `md_to_pdf.py` 等导出路径，改进**中文字体**下的版式与转换质量（系统字体或 `AURA_PDF_FONT` 等，见 `SKILL.md` / `SKILL_CN.md`）。

### 修复

- 中间稿格式异常、**日期识别幻觉**等与中间文件 / 元数据相关的问题。

## [1.0.7] 及更早

此前版本未在本文件逐条列出；可查 Git 历史或 ClawHub 包说明。
