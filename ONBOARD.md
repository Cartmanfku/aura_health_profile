# Aura Health Profile Onboarding (First Install)

Use this checklist when a user installs the skill for the first time.

## 1) Environment check and dependency install

From the skill root (`{baseDir}`: folder containing `SKILL.md` and `scripts/`):

```bash
cd "/path/to/aura_health_profile"
python3 --version
python3 -m venv .venv
./.venv/bin/python3 --version
./.venv/bin/pip --version
./.venv/bin/pip install -r requirements.txt
```

Expected:
- Python is available.
- `pip install -r requirements.txt` completes without errors.

If install fails, fix environment first (Python, venv, or network) before continuing.

## 2) Ask user for API key, configure it, and verify model access

Ask the user for a valid DashScope key (do not print full key in logs/screenshots).

Choose one config method:

- Environment variable (session-level):

```bash
export DASHSCOPE_API_KEY="sk-REPLACE_WITH_YOUR_KEY"
```

- Config file (`~/.aura-health/config.json`):

```json
{
  "dashscope_api_key": "sk-REPLACE_WITH_YOUR_KEY"
}
```

Then verify API connectivity with a tiny model call:

```bash
./.venv/bin/python3 -c "from scripts.config import chat_completions; print(chat_completions([{'role':'user','content':'Reply with: OK'}], max_tokens=16).strip())"
```

Expected:
- Command returns a short response (e.g. `OK` or similar).
- No authentication / HTTP error.

## 3) Recommend and choose default PDF tool, then verify availability

Recommend this priority to the user and confirm which default they want:
1. Installed `pdf-generator` skill (preferred when available)
2. `pandoc`
3. `scripts/md_to_pdf.py` fallback

Check tools:

```bash
pandoc --version
./.venv/bin/python3 -c "import fpdf; print('fpdf2 OK')"
```

Guidance:
- If `pandoc` exists, PDF output quality (especially Chinese/CJK and complex Markdown) is usually better.
- If `pandoc` is missing, `md_to_pdf.py` still works via `fpdf2` fallback.

## 4) Ask user for preferred language and configure it (default: Simplified Chinese)

Default is Simplified Chinese unless user asks otherwise.

Recommended config (`~/.aura-health/config.json`):

```json
{
  "dashscope_api_key": "sk-REPLACE_WITH_YOUR_KEY",
  "preferred_language": "zh-CN"
}
```

Alternative via environment:

```bash
export AURA_USER_LANGUAGE="zh-CN"
```

Notes:
- `zh-CN` selects Chinese template/reference (`*_cn.md`) for build/update.
- If language is not Chinese, system falls back to English assets.

## 5) Onboarding complete: introduce features and run examples from README

After steps 1-4 are done:
- Briefly explain shipped features (Mode 1 build, Mode 2 update).
- Point user to `README.md`, then `SKILL.md` / `SKILL_CN.md` for full details.
- Run a minimal example with user-provided image folder:

```bash
./.venv/bin/python3 scripts/vision_parser.py "/absolute/path/to/images"
./.venv/bin/python3 scripts/build_profile.py
./.venv/bin/python3 scripts/md_to_pdf.py "$HOME/Documents/AuraHealth/health_profile_$(date +%Y%m%d).md"
```

If user adds new images later:

```bash
./.venv/bin/python3 scripts/vision_parser.py "/absolute/path/to/new_images"
./.venv/bin/python3 scripts/update_profile.py
```

---

Safety reminder: this workflow organizes user-provided medical records for personal documentation and does not provide diagnosis or treatment advice.
