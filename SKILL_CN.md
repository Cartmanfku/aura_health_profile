---
name: aura_health_profile(奥拉健康档案)
description: "**将繁琐的病历管理，变为安心的日常陪伴。** 一款专为慢性病患者设计的智能健康助手技能，基于阿里云百炼 Qwen 与 Wan 模型，帮你把散乱的化验单、病历、药盒说明变成清晰易懂的健康档案与复诊简报。"
version: 1.1.0
author: cartman
metadata:
  openclaw:
    emoji: ""
    requires:
      bins:
        - python3
      env:
        - DASHSCOPE_API_KEY
        - AURA_VISION_MODEL
        - AURA_TEXT_MODEL
        - AURA_STATE_HOME
        - AURA_OUTPUT_DIR
      config:
        - ~/.aura-health/config.json
    primaryEnv: DASHSCOPE_API_KEY
    homepage: https://github.com/Cartmanfku/aura_health_profile
---

# Aura Health Profile（简体中文说明）

> 与英文版 `SKILL.md` 内容对应；命令与路径与英文版一致。

慢性病护理工作流：**解析图片与 PDF 页面 → 结构化记录与指标 → 完整档案 MD/PDF → 复诊简报（基于 profile 的摘要，生成 MD/PDF + 样式化图片）**。请优先运行 `{baseDir}/scripts/` 下随附的 Python 脚本，不要随意手写重复调用 API。


## 环境与首次配置

**所需条件**

- **Python 3** 及 `{baseDir}/requirements.txt` 中的包（通过下文命令安装）。
- **PDF（可选，强烈推荐）** — 将 Markdown 导出为 PDF 时，按以下顺序优先：**(1)** 若智能体已安装 **pdf-generator** 技能，按该技能说明生成 PDF；**(2)** 否则若 `PATH` 中有 [pandoc](https://pandoc.org)（**不是** pip 包，需单独安装可执行文件，例如 macOS：`brew install pandoc`），直接用 pandoc 转换；**(3)** 否则运行 `{baseDir}/scripts/md_to_pdf.py`（有 pandoc 则用 pandoc，否则 **mistune + ReportLab**：从 Markdown AST 直接排版 PDF；中文等 CJK 在找到系统字体或设置 `AURA_PDF_FONT` 指向 `.ttf`/`.ttc` 时嵌入）。复杂 Markdown 排版仍建议优先 (1) 或 (2)。
- **DashScope API key**（阿里云百炼 / 模型服务），由 `{baseDir}/scripts/config.py` 读取：  
  - 推荐：`export DASHSCOPE_API_KEY="sk-..."`  
  - 或：`~/.aura-health/config.json` 中配置 `{ "dashscope_api_key": "sk-..." }`
- **档案输出语言（可选）** — 用于 `build_profile.py` / `update_profile.py`：  
  - 环境变量：`AURA_USER_LANGUAGE=zh-CN`（或 `AURA_PROFILE_LANGUAGE=zh-CN`）可强制简体中文输出  
  - 配置文件：`~/.aura-health/config.json` 中加 `"preferred_language": "zh-CN"`（也兼容 `"common_language"` / `"language"`）
- **模型（参考）**  
  - 视觉 / 文本：OpenAI 兼容对话接口 — `qwen3.6-plus`，`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`  
  - 文生图（模式 3）：`wan2.7-image-pro`，`https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation`

**首次安装** — 请在技能根目录 `{baseDir}`（包含 `SKILL.md` 与 `scripts/`）直接按 `ONBOARD_CN.md` 执行。

`ONBOARD_CN.md` 已包含环境检查、API key 配置与连通性验证、PDF 工具选择、常用语言配置、以及安装完成后的示例流程。

## 构建模式选择

在执行合并脚本前，先选择模式（解析脚本在两种模式下相同）：

- **快速合并模式（默认）**  
  - 脚本：`build_profile.py` / `update_profile.py`  
  - 适用于资料规模较小、时间跨度有限的场景。
- **分期汇总模式**  
  - 脚本：`build_profile_sharded.py` / `update_profile_sharded.py`  
  - 适用于多年累积资料、PDF 较多或中间文件体量较大的场景。

经验规则：若中间文件较多（例如 >50）或跨多年，优先使用**分期汇总模式**。

## 路径说明

| 用途 | 路径 |
|------|------|
| 单张图或 PDF 单页对应的中间 Markdown | `~/.aura-health/intermediate/{date}_{type}_{hash8}.md` |
| 时序指标 | `~/.aura-health/metrics.json` |
| 已处理内容哈希（增量；整图文件或 PDF 按页摘要） | `~/.aura-health/processed.json` |
| 最近一次构建/更新的 QC（JSON） | `~/.aura-health/last_profile_qc.json` |
| 档案合并状态（更新模式） | `~/.aura-health/profile_merge_state.json` |
| 完整档案 MD/PDF | `~/Documents/AuraHealth/health_profile_YYYYMMDD.md` 及 `.pdf` |
| 简报相关资源 | `~/Documents/AuraHealth/revisit_brief_YYYYMMDD.md`、`~/Documents/AuraHealth/brief_YYYYMMDD.png`（给医生的样式化一页图）、`~/Documents/AuraHealth/brief_user_comic_YYYYMMDD.png`（6–9 格通俗漫画）、`~/Documents/AuraHealth/revisit_brief_YYYYMMDD.pdf` |

写入前请确保 `~/Documents/AuraHealth/` 与 `~/.aura-health/` 可用（脚本也会按需创建）。

## 技能包目录结构

- `{baseDir}/SKILL.md` — 英文主文档（ClawHub 以其中元数据为准）  
- `{baseDir}/SKILL_CN.md` — 本简体中文说明  
- `{baseDir}/ONBOARD.md`、`{baseDir}/README.md`、`{baseDir}/PUBLISHING_CN.md`、`{baseDir}/PUBLISHING.md`、`{baseDir}/CHANGELOG_CN.md`、`{baseDir}/CHANGELOG.md`、`{baseDir}/LICENSE` — 安装说明、发布指南、变更日志与许可（`LICENSE` 为 MIT-0）  
- `{baseDir}/requirements.txt` — Python 依赖  
- `{baseDir}/.clawhubignore` — 发布打包时排除的路径  
- `{baseDir}/scripts/` — 已包含：`config.py`、`vision_parse_common.py`、`vision_parser.py`、`pdf_vision_parser.py`、`pdf_bundle_builder.py`、`intermediate_qc.py`、`build_profile.py`、`build_profile_sharded.py`、`update_profile.py`、`update_profile_sharded.py`、`profile_merge_state.py`、`md_to_pdf.py`、`generate_brief.py`  
- `{baseDir}/references/medical_reference.md`、`{baseDir}/references/medical_reference_cn.md` — 英文 / 简体中文术语参考  
- `{baseDir}/assets/profile_template.md`、`{baseDir}/assets/profile_template_cn.md`、`{baseDir}/assets/brief_template.md`、`{baseDir}/assets/brief_template_cn.md` — 英文 / 简体中文模板  

合并档案时按用户常用语言选择模板与术语参考（`zh-CN` 优先使用 `*_cn.md`；若缺失则回退英文版本）。

## 模式一 — 首次构建完整档案（`build`）

**适用场景：** 第一次使用，或用户要求重建 / 初始化病历档案。

1. **解析输入（图片与 PDF 分两个脚本）**  
   - **栅格图**（`.jpg` / `.jpeg` / `.png` / `.webp`）：`{baseDir}/scripts/vision_parser.py`，每文件 → 一个中间 Markdown。`processed.json` 与 `metrics.json` 按 `--batch-size`（默认 `5`，建议不稳网络用 `1`）分批落盘；**每张图成功后会先写出 `.md` 再进入后续页**；若中途失败，已写出的 `.md` 仍保留。若进程在写出 `.md` 之后、尚未把哈希刷入 `processed.json` 就崩溃，下次运行仍会通过 `vision_parse_common.load_existing_intermediate_hashes()` 扫描注释头跳过重复。**Ctrl+C** 会保存当前内存中的状态。  
   - **PDF**：`{baseDir}/scripts/pdf_vision_parser.py`，**PyMuPDF** 逐页栅格化，**每页一个**中间稿。**每页成功后立即**写出该页 `.md` 并 **flush** `processed.json` / `metrics.json`，长报告中途失败时已完成页不丢；不加 `--force` 再跑即可只补未成功的页。**报告日期与文档类型**以 **第 1 页（封面）** 为准，并写回每一页的 `## Document metadata`（内页模型输出会被规范成与首页一致）。提示词与 RGB 渲染有助于减轻中文乱码。长文档可自动生成压缩 bundle（`--bundle-threshold-pages`、`--bundle-chunk-pages`，`--no-bundle` 可关闭），构建档案时可通过 `build_profile.py --pdf-input-mode auto|bundle` 优先使用 bundle。

   **图片 — 可执行命令**（在 `{baseDir}` 下，并已配置 API key）：

   ```bash
   cd "/path/to/aura_health_profile"   # 你的 {baseDir}
   export DASHSCOPE_API_KEY="sk-REPLACE_WITH_YOUR_KEY"
   ./.venv/bin/python3 scripts/vision_parser.py "/absolute/path/to/folder/with/photos"
   ./.venv/bin/python3 scripts/vision_parser.py --recursive "/absolute/path/to/folder/with/photos"
   ```

   可选：`--force`、`--model MODEL`、`--batch-size N`、`--quiet`。

   **PDF — 可执行命令**：

   ```bash
   ./.venv/bin/python3 scripts/pdf_vision_parser.py "/absolute/path/to/folder/with/pdfs"
   ./.venv/bin/python3 scripts/pdf_vision_parser.py --recursive "/absolute/path/to/folder/with/pdfs"
   ```

   可选：`--force`、`--model MODEL`、`--pdf-zoom Z`、`--quiet`。

2. **合并为完整 Markdown**  
   - 两种脚本都会生成 `health_profile_YYYYMMDD.md`，并写入合并状态。  
   - **注意：本步骤不会自动转 PDF**；PDF 需要执行第 3 步。

   **快速合并模式（`build_profile.py`）**
   - 读取全部 `~/.aura-health/intermediate/*.md`，一次性合并。
   - 在调用模型前会做 **QC**：重复或异常中间稿不参与合并；结果写入 `~/.aura-health/last_profile_qc.json`，并在输出 Markdown 末尾附 **Build QC** 表。

   **可执行命令（快速合并模式）**：

   ```bash
   cd "/path/to/aura_health_profile"
   export DASHSCOPE_API_KEY="sk-REPLACE_WITH_YOUR_KEY"
   ./.venv/bin/python3 scripts/build_profile.py
   ```

   脚本会在标准输出打印新生成的 `.md` 路径（默认文件名中的日期为**当天本地** `YYYYMMDD`）。

   显式指定输出日期：

   ```bash
   ./.venv/bin/python3 scripts/build_profile.py --date 20260413
   ```

   可选：`--model MODEL` 覆盖文本模型（默认 `qwen3.6-plus`，环境变量 `AURA_TEXT_MODEL`）。

   **分期汇总模式（`build_profile_sharded.py`）**
   - 先按时间分片（半年）生成阶段汇总，再做最终合并。
   - 会额外生成分片产物：`~/.aura-health/period_summaries/period_profile_YYYYH1.md` / `period_profile_YYYYH2.md`（及可能的 `period_profile_undated.md`）。

   **可执行命令（分期汇总模式）**：

   ```bash
   ./.venv/bin/python3 scripts/build_profile_sharded.py
   ```

   常用参数：`--shard-mode half-year`（`year` 已弃用，传入时会自动按 `half-year` 处理）、`--shard-max-chars N`、`--pdf-input-mode auto|raw|bundle`、`--pdf-bundle-threshold-pages N`、`--date YYYYMMDD`。

3. **导出 PDF**  
   - 将第 2 步的 Markdown 转为 `~/Documents/AuraHealth/health_profile_YYYYMMDD.pdf`（或你指定的路径）。**优先级：** **(1)** 若已安装 **pdf-generator** 技能，本步用该技能完成 Markdown → PDF。 **(2)** 否则若 `PATH` 中有 `pandoc`，直接对 `.md` 调用 pandoc（例如 `pandoc … -o …pdf`）。 **(3)** 否则运行 `{baseDir}/scripts/md_to_pdf.py`（有 pandoc 则用 pandoc，否则 **mistune + ReportLab**；CJK 依赖系统字体或环境变量 `AURA_PDF_FONT`；复杂排版请优先 (1) 或 (2)，或安装 [pandoc](https://pandoc.org)）。

   **可执行命令**（采用第 **(3)** 步、使用 `md_to_pdf.py` 时）— 使用 `build_profile.py` 打印的 `.md` 路径，或按当天日期拼路径：

   ```bash
   cd "/path/to/aura_health_profile"
   ./.venv/bin/python3 scripts/md_to_pdf.py \
     "$HOME/Documents/AuraHealth/health_profile_$(date +%Y%m%d).md"
   ```

   若不指定第二个参数，PDF 与 Markdown 同目录、同主文件名（例如 `health_profile_20260413.pdf`）。

   显式指定输入与输出：

   ```bash
   ./.venv/bin/python3 scripts/md_to_pdf.py \
     "$HOME/Documents/AuraHealth/health_profile_20260413.md" \
     "$HOME/Documents/AuraHealth/health_profile_20260413.pdf"
   ```

   成功时脚本会打印 PDF 路径。

## 模式二 — 增量更新（`update`）

**适用场景：** 用户追加了新图片。

1. **只解析新图或新 PDF 页**（哈希不在 `processed.json` 中）；追加中间 Markdown，并更新 `metrics.json` / `processed.json`。新图用 `{baseDir}/scripts/vision_parser.py`，新 PDF 用 `{baseDir}/scripts/pdf_vision_parser.py`（续跑、落盘规则与模式一第 1 步一致）。

   **新图**：

   ```bash
   cd "/path/to/aura_health_profile"
   export DASHSCOPE_API_KEY="sk-REPLACE_WITH_YOUR_KEY"
   ./.venv/bin/python3 scripts/vision_parser.py "/absolute/path/to/folder/with/new/photos"
   ./.venv/bin/python3 scripts/vision_parser.py --recursive "/absolute/path/to/folder/with/new/photos"
   ```

   **新 PDF**：

   ```bash
   ./.venv/bin/python3 scripts/pdf_vision_parser.py "/absolute/path/to/folder/with/new/pdfs"
   ./.venv/bin/python3 scripts/pdf_vision_parser.py --recursive "/absolute/path/to/folder/with/new/pdfs"
   ```

   可选：`--force`、`--model MODEL`；图片另可加 `--batch-size`、`--quiet`；PDF 另可加 `--pdf-zoom`、`--quiet`。

2. **再次合并**  
   - 两种更新脚本都会读取基线档案与新中间稿，写出新的 `health_profile_YYYYMMDD.md`。  
   - **注意：本步骤不会自动转 PDF**；PDF 需要执行第 3 步。

   **快速合并模式（`update_profile.py`）**
   - 基于 merge state 识别“未合并过”的新来源并合并。
   - 对本轮候选新中间稿执行 **QC**，排除项写入 `~/.aura-health/last_profile_qc.json`（`label=update`）。

   **可执行命令（快速合并模式）** — 在完成第 1 步且 `~/Documents/AuraHealth/` 下已有基线档案后：

   ```bash
   cd "/path/to/aura_health_profile"
   export DASHSCOPE_API_KEY="sk-REPLACE_WITH_YOUR_KEY"
   ./.venv/bin/python3 scripts/update_profile.py
   ```

   脚本会打印新 `.md` 路径（默认使用**当天本地** `YYYYMMDD`）。若无新内容可合并，会提示后退出。

   指定输出日期：

   ```bash
   ./.venv/bin/python3 scripts/update_profile.py --date 20260413
   ```

   指定基线档案（不用「最新」的 `health_profile_*.md`）：

   ```bash
   ./.venv/bin/python3 scripts/update_profile.py \
     --profile "$HOME/Documents/AuraHealth/health_profile_20260101.md"
   ```

   将**全部**中间文件再次发给模型做整体对齐（token 消耗更高）：

   ```bash
   ./.venv/bin/python3 scripts/update_profile.py --full
   ```

   不使用虚拟环境：

   ```bash
   cd "/path/to/aura_health_profile"
   python3 scripts/update_profile.py
   ```

   可选：`--model MODEL`（默认 `qwen3.6-plus`，环境变量 `AURA_TEXT_MODEL`）。

   **分期汇总模式（`update_profile_sharded.py`）**
   - 仅重算受影响时间分片，再做最终二次合并；适合多年累积的大体量资料。
   - 会复用/更新 `~/.aura-health/period_summaries/period_profile_YYYYH1.md`、`period_profile_YYYYH2.md`（及可能的 `period_profile_undated.md`）。

   **可执行命令（分期汇总模式）**：

   ```bash
   ./.venv/bin/python3 scripts/update_profile_sharded.py
   ```

   常用参数：`--shard-mode half-year`（`year` 已弃用，传入时会自动按 `half-year` 处理）、`--shard-max-chars N`、`--pdf-input-mode auto|raw|bundle`、`--pdf-bundle-threshold-pages N`、`--full`、`--profile PATH`、`--date YYYYMMDD`。

3. **PDF** — 与 **模式一 — 构建** 第 3 步相同：pdf-generator 技能 → pandoc → `md_to_pdf.py`，输入为第 2 步生成的 Markdown（`update_profile.py` 或 `update_profile_sharded.py` 打印的路径，或 `~/Documents/AuraHealth/health_profile_YYYYMMDD.md`）。`md_to_pdf.py` 的命令示例见上文 **模式一第 3 步**。

## 模式三 — 复诊简报（`brief`）

**本包状态：** 本模式已可用，入口脚本为 `{baseDir}/scripts/generate_brief.py`。

**适用场景：** 就诊前需要一页式摘要。

1. **摘要卡片**  
   - 读取最新完整档案 Markdown。  
   - 使用 `{baseDir}/assets/brief_template.md` 由 Qwen 摘要为一份简报 Markdown：`~/Documents/AuraHealth/revisit_brief_YYYYMMDD.md`。

2. **同源生成医生版样式图、用户版漫画图与 PDF**  
   - 以上述简报 Markdown 作为唯一内容源（正文面向医生，保留专业表述）。  
   - Wan 2.7 生成**医生向**样式化一页图（分区、重点高亮、轻量指标可视化）→ `~/Documents/AuraHealth/brief_YYYYMMDD.png`。  
   - Qwen 根据同一份简报生成 **6–9 格**通俗漫画分镜脚本，再由 Wan 出图，供患者/家属阅读 → `~/Documents/AuraHealth/brief_user_comic_YYYYMMDD.png`。  
   - 将同一份 Markdown 转 PDF → `~/Documents/AuraHealth/revisit_brief_YYYYMMDD.pdf`（编排脚本内部调用 `{baseDir}/scripts/md_to_pdf.py`）。
   - 编排入口：`{baseDir}/scripts/generate_brief.py`。若只需一张图、节省第二次出图费用，可加 `--skip-user-comic` 或设置环境变量 `AURA_BRIEF_SKIP_USER_COMIC=1`。

   **可执行命令**（默认：自动读取最新 `health_profile_*.md`、当天日期）：

   ```bash
   ./.venv/bin/python3 scripts/generate_brief.py
   ```

   指定档案与输出日期：

   ```bash
   ./.venv/bin/python3 scripts/generate_brief.py \
     --profile "$HOME/Documents/AuraHealth/health_profile_20260413.md" \
     --date 20260414
   ```

   可选：`--text-model MODEL`（默认 `qwen3.6-plus`）、`--image-model MODEL`（默认 `wan2.7-image-pro`）、`--size 1024*1024`、`--comic-size 1024*1792`、`--timeout SEC`、`--skip-user-comic`。

## 智能体执行注意

- 根据用户意图选择模式：全量重建、仅新图增量、或复诊简报。  
- **不要**在对话日志中暴露 API key；使用环境变量或 `~/.aura-health/config.json`。  
- **幂等：** 增量解析须跳过 `processed.json` 中已有哈希。  
- **PDF 导出：** 从 Markdown 生成健康档案 PDF 时，依次尝试：**(1)** 已安装的 **pdf-generator** 技能，**(2)** `PATH` 上的 **pandoc** 命令行，**(3)** `{baseDir}/scripts/md_to_pdf.py`。  
- **安全：** 医学内容仅供用户自备材料的整理辅助，**不是**诊断。若模板含免责声明，请在面向用户的输出中保留。

## OpenClaw 安装提示

将 `aura_health_profile/` 技能目录复制或符号链接到智能体工作区的 `skills/`（或 `skills.load.extraDirs` 所配路径），然后开启新会话，使 `openclaw skills list` 能看到 `aura_health_profile`。发布到 ClawHub 时若 slug 不接受下划线，可改用带连字符的目录名 — 见 `{baseDir}/PUBLISHING_CN.md`（英文：`{baseDir}/PUBLISHING.md`）。
