# Changelog

简体中文见 [`CHANGELOG_CN.md`](CHANGELOG_CN.md).

All notable changes to **aura_health_profile** are recorded here (English). The `version` field in `SKILL.md` / `SKILL_CN.md` frontmatter should match the latest entry. Keep this file aligned with `CHANGELOG_CN.md` for each release.

## [1.1.0] - 2026-04-21

### Added

- **PDF parsing**: Full PDF support — each page is **rasterized to an image**, processed by the vision model page by page, with optional **bundle** merging for long documents before profile build.
- **Two profile-build modes**: **Fast merge** (`build_profile.py` / `update_profile.py`) and **time-sharded merge** (`build_profile_sharded.py` / `update_profile_sharded.py`). For multi-year archives or large numbers of images/PDFs, **time-sharded merge** is recommended.

### Changed

- **Markdown → PDF**: Upgraded `md_to_pdf.py` and related export paths for better layout and conversion when using **CJK fonts** (system fonts or `AURA_PDF_FONT`; see `SKILL.md` / `SKILL_CN.md`).

### Fixed

- Intermediate file format issues, **date hallucination** in recognition, and related metadata/intermediate bugs.

## [1.0.7] and earlier

Earlier releases were not listed in this file; use Git history or ClawHub package notes if available.
