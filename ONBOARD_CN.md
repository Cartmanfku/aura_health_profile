# Aura Health Profile 首次安装引导（ONBOARD）

首次安装时，按本清单逐项完成。

## 1) 检查环境并安装依赖

在技能根目录执行（`{baseDir}`：包含 `SKILL.md` 与 `scripts/` 的目录）：

```bash
cd "/path/to/aura_health_profile"
python3 --version
python3 -m venv .venv
./.venv/bin/python3 --version
./.venv/bin/pip --version
./.venv/bin/pip install -r requirements.txt
```

预期结果：
- Python 可用；
- `pip install -r requirements.txt` 无报错完成。

若安装失败，请先修复环境问题（Python / venv / 网络）再继续。

## 2) 询问并配置 API Key，验证模型 API 可访问

向用户索取有效 DashScope Key（不要在日志/截图中暴露完整 key）。

选择一种配置方式：

- 环境变量（当前会话）：

```bash
export DASHSCOPE_API_KEY="sk-REPLACE_WITH_YOUR_KEY"
```

- 配置文件（`~/.aura-health/config.json`）：

```json
{
  "dashscope_api_key": "sk-REPLACE_WITH_YOUR_KEY"
}
```

然后用最小调用验证 API 连通性：

```bash
./.venv/bin/python3 -c "from scripts.config import chat_completions; print(chat_completions([{'role':'user','content':'Reply with: OK'}], max_tokens=16).strip())"
```

预期结果：
- 命令返回简短文本（如 `OK`）；
- 不出现认证错误或 HTTP 错误。

## 3) 推荐并选择默认 PDF 工具，再检查是否已安装

向用户推荐并确认默认顺序：
1. 已安装的 `pdf-generator` 技能（优先）
2. `pandoc`
3. `scripts/md_to_pdf.py` 回退

检查工具可用性：

```bash
pandoc --version
./.venv/bin/python3 -c "import mistune, reportlab; print('mistune + reportlab OK')"
```

建议：
- 若存在 `pandoc`，PDF 质量通常更好（尤其中文/CJK 和复杂 Markdown）。
- 若缺少 `pandoc`，仍可使用 `md_to_pdf.py` 的 **mistune + ReportLab** 回退（若无合适系统字体，请设置 `AURA_PDF_FONT` 为含中文的 `.ttf`/`.ttc`）。

## 4) 询问并配置常用语言（默认：简体中文）

默认使用简体中文，除非用户明确要求其他语言。

推荐配置（`~/.aura-health/config.json`）：

```json
{
  "dashscope_api_key": "sk-REPLACE_WITH_YOUR_KEY",
  "preferred_language": "zh-CN"
}
```

环境变量方式（可选）：

```bash
export AURA_USER_LANGUAGE="zh-CN"
```

说明：
- `zh-CN` 会让 build/update 优先使用中文模板与中文术语参考（`*_cn.md`）。
- 若不是中文，会自动回退/使用英文资产。

## 5) 首次安装时让用户选择合并模式（默认：快速合并模式）

解析脚本（`vision_parser.py` / `pdf_vision_parser.py`）在两种合并模式下相同；差异只在**合并档案**这一步用的脚本与策略。

默认使用**快速合并模式**，除非用户明确选择**分期汇总模式**。

### 快速合并模式 vs 分期汇总模式（关键差异）

| 维度 | 快速合并模式 | 分期汇总模式 |
|------|------|------|
| 构建脚本 | `scripts/build_profile.py` | `scripts/build_profile_sharded.py` |
| 更新脚本 | `scripts/update_profile.py` | `scripts/update_profile_sharded.py` |
| 合并策略 | 单次全量/增量直接合并 | 先按时间分片（半年）汇总，再做最终合并 |
| 分片产物 | 无 | `~/.aura-health/period_summaries/period_profile_YYYYH1.md`、`period_profile_YYYYH2.md`（及可能的 `period_profile_undated.md`） |
| PDF | **不自动生成**；合并后需单独运行 `md_to_pdf.py`（或 pandoc / pdf-generator） | 同上 |

两种模式都会生成 `~/Documents/AuraHealth/health_profile_YYYYMMDD.md`。

向用户说明并确认其选择：

- **快速合并模式（默认）：** `build_profile.py` / `update_profile.py` — 资料规模较小、时间跨度有限时优先。
- **分期汇总模式：** `build_profile_sharded.py` / `update_profile_sharded.py` — 多年累积、PDF 或中间文件较多时优先。

建议：
- 若资料体量大、跨多年、或 PDF 页数/数量较多，建议使用**分期汇总模式**。

## 6) 全部完成后：按 README 介绍功能并演示示例

完成前 1-5 步后：
- 简要介绍已支持功能（模式一 build、模式二 update）；
- 引导用户阅读 `README.md`，再看 `SKILL.md` / `SKILL_CN.md` 的完整说明；
- 使用用户提供的图片目录跑最小示例：

```bash
./.venv/bin/python3 scripts/vision_parser.py "/absolute/path/to/images"
./.venv/bin/python3 scripts/build_profile.py
./.venv/bin/python3 scripts/md_to_pdf.py "$HOME/Documents/AuraHealth/health_profile_$(date +%Y%m%d).md"
```

PDF 报告请用独立脚本（逐页解析）：

```bash
./.venv/bin/python3 scripts/pdf_vision_parser.py "/absolute/path/to/pdfs"
./.venv/bin/python3 scripts/build_profile.py
```

若后续用户新增图片：

```bash
./.venv/bin/python3 scripts/vision_parser.py "/absolute/path/to/new_images"
./.venv/bin/python3 scripts/update_profile.py
```

若用户选择了**分期汇总模式**，将合并命令替换为：

```bash
./.venv/bin/python3 scripts/build_profile_sharded.py
./.venv/bin/python3 scripts/update_profile_sharded.py
```

---

安全提醒：本流程仅用于整理用户自备医疗资料，不提供诊断或治疗建议。
