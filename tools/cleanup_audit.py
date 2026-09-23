"""Workspace Cleanup Audit Tool (STD-019).

Scans the repository for files that match known generated/temporary/obsolete
patterns and produces a workspace_cleanup_audit.md report.

Usage:
    python tools/cleanup_audit.py [--root <repo-root>] [--output <output-file>]
"""
from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

# File categories: (pattern-suffix-or-name, category, reason)
FILE_RULES: list[tuple[str, str, str]] = [
    # Acceptance ZIPs at repo root are ARCHIVE
    (".zip", "ARCHIVE", "Acceptance delivery ZIP - keep in .artifacts/packages/"),
    # Old versioned packaging scripts
    ("package_acceptance_v", "OBSOLETE", "Versioned packaging script superseded by package_acceptance.py"),
    # pytest cache
    (".pytest_cache", "GENERATED", "pytest cache directory - safe to delete"),
    # Playwright reports
    ("playwright-report", "GENERATED", "Playwright HTML report - gitignored output"),
    ("test-results", "GENERATED", "Playwright test-results directory"),
    # Video/screenshot residuals at root
    (".webm", "GENERATED", "Playwright video recording"),
    # Old acceptance staging dirs at repo root (e.g. Acceptance-AI-HUB-DEV-005-v0.5.0/)
    ("Acceptance-", "ARCHIVE", "Legacy acceptance staging directory at repo root"),
    # PDF reports
    (".pdf", "GENERATED", "Generated PDF report"),
    # __pycache__
    ("__pycache__", "GENERATED", "Python bytecode cache"),
]

KEEP_PATTERNS: set[str] = {".git", ".venv", "venv", "env", ".gitignore", ".gitkeep"}


def classify(path: Path, root: Path) -> tuple[str, str]:
    rel = str(path.relative_to(root))
    name = path.name
    for pattern, category, reason in FILE_RULES:
        if name.startswith(pattern) or name.endswith(pattern) or pattern in name:
            return category, reason
    return "KEEP", "No matching rule - retained"


def scan(root: Path) -> list[dict]:
    results = []
    for item in sorted(root.iterdir()):
        if item.name in KEEP_PATTERNS or item.name.startswith(".") and item.name not in {".pytest_cache", ".artifacts"}:
            if item.name not in (".pytest_cache",):
                continue
        if item.name == ".artifacts":
            continue  # Skip artifact workspace itself
        category, reason = classify(item, root)
        size = 0
        if item.is_file():
            size = item.stat().st_size
        elif item.is_dir():
            size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
        results.append({
            "path": str(item.relative_to(root)),
            "type": "DIR" if item.is_dir() else "FILE",
            "size_mb": round(size / 1024 / 1024, 2),
            "category": category,
            "reason": reason,
        })
    return results


def render_report(results: list[dict], root: Path) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Workspace Cleanup Audit Report",
        f"",
        f"**Generated**: {now}  ",
        f"**Repository**: {root}  ",
        f"**Standard**: STD-019 Artifact & Workspace Hygiene  ",
        f"",
        f"## Summary",
        f"",
    ]
    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    for cat, items in sorted(by_cat.items()):
        total_mb = sum(i["size_mb"] for i in items)
        lines.append(f"- **{cat}**: {len(items)} items ({total_mb:.2f} MB)")
    lines += ["", "## Detail", "",
               "| Category | Type | Size (MB) | Path | Reason |",
               "|----------|------|-----------|------|--------|"]
    for r in sorted(results, key=lambda x: (x["category"], x["path"])):
        lines.append(f"| {r['category']} | {r['type']} | {r['size_mb']} | `{r['path']}` | {r['reason']} |")
    lines += ["",
               "## Recommended Actions",
               "",
               "- **ARCHIVE**: Move to `.artifacts/packages/` or external storage.",
               "- **GENERATED**: Safe to delete; regenerated on next run.",
               "- **OBSOLETE**: Delete after confirming no references.",
               "- **TEMP**: Delete after cross-session handoff confirmed.",
               "- **KEEP**: No action required.",
               ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Workspace cleanup audit (STD-019)")
    parser.add_argument("--root", default=".", help="Repository root directory")
    parser.add_argument("--output", default="workspace_cleanup_audit.md", help="Output report file")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output = Path(args.output)

    print(f"[audit] Scanning {root} ...")
    results = scan(root)
    report = render_report(results, root)

    output.write_text(report, encoding="utf-8")
    print(f"[audit] Report written to {output}")

    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    for cat, items in sorted(by_cat.items()):
        total_mb = sum(i["size_mb"] for i in items)
        print(f"  {cat:12s}: {len(items):3d} items  {total_mb:8.2f} MB")


if __name__ == "__main__":
    main()