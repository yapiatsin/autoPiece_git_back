"""Analyse et suppression des fichiers static non utilisés (ecom, stock, Userauths)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
APPS = ["ecom", "stock", "Userauths"]
BASES = [
    ROOT / "ecom/templates/e_autopiece/base_ecom.html",
    ROOT / "Userauths/templates/page/base_compt.html",
    ROOT / "stock/templates/mag/base_mag_ecom.html",
]
SETTINGS = ROOT / "magazin_piece/settings.py"

STATIC_TAG = re.compile(r"\{%\s*static\s+['\"]([^'\"]+)['\"]")
STATIC_PATH = re.compile(r"static/([a-zA-Z0-9_./ -]+)")
QUOTED_ASSET = re.compile(r"['\"]((?:apps|e_assets)/[^'\"]+)['\"]")
URL_REF = re.compile(r"url\(\s*['\"]?([^)'\"]+?)['\"]?\s*\)", re.IGNORECASE)
IMPORT_REF = re.compile(r"@import\s+['\"]([^'\"]+)['\"]", re.IGNORECASE)

# Fichiers protégés (hors scope apps mais référencés ailleurs)
PROTECTED = {"a.png"}


def normalize_ref(ref: str) -> str:
    return ref.strip().lstrip("/").replace("\\", "/")


def collect_static_files() -> list[str]:
    return sorted(
        p.relative_to(STATIC).as_posix()
        for p in STATIC.rglob("*")
        if p.is_file()
    )


def collect_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for app in APPS:
        for ext in ("*.html", "*.py", "*.js", "*.css"):
            for f in (ROOT / app).rglob(ext):
                try:
                    sources[str(f)] = f.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    pass
    for f in BASES:
        try:
            sources[str(f)] = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass
    if SETTINGS.exists():
        sources[str(SETTINGS)] = SETTINGS.read_text(encoding="utf-8", errors="ignore")
    return sources


def add_ref(used: set[str], ref: str) -> None:
    ref = normalize_ref(ref)
    if not ref or ref.startswith(("http://", "https://", "//")):
        return
    if ref.startswith("static/"):
        ref = ref[7:]
    used.add(ref)


def extract_refs(text: str) -> set[str]:
    refs: set[str] = set()
    for pat in (STATIC_TAG, STATIC_PATH, QUOTED_ASSET):
        for m in pat.finditer(text):
            add_ref(refs, m.group(1))
    return refs


def resolve_relative(file_rel: str, url: str, used: set[str]) -> None:
    url = url.strip().split("?")[0].split("#")[0]
    if not url or url.startswith(("data:", "http://", "https://", "#", "//")):
        return
    if url.startswith("/"):
        add_ref(used, url.lstrip("/"))
        return
    base = (STATIC / file_rel).parent
    try:
        resolved = (base / url).resolve()
        rel = resolved.relative_to(STATIC.resolve()).as_posix()
        add_ref(used, rel)
    except (ValueError, OSError):
        pass


def transitive_closure(used: set[str]) -> set[str]:
    queue = [u for u in used if (STATIC / u).is_file() and u.endswith((".css", ".js"))]
    seen = set(queue)
    while queue:
        rel = queue.pop(0)
        try:
            text = (STATIC / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ref in extract_refs(text):
            if ref not in used:
                used.add(ref)
                if (STATIC / ref).is_file() and ref.endswith((".css", ".js")) and ref not in seen:
                    queue.append(ref)
                    seen.add(ref)
        for m in URL_REF.finditer(text):
            before = len(used)
            resolve_relative(rel, m.group(1), used)
            for ref in list(used):
                if ref not in seen and (STATIC / ref).is_file() and ref.endswith((".css", ".js")):
                    queue.append(ref)
                    seen.add(ref)
        for m in IMPORT_REF.finditer(text):
            resolve_relative(rel, m.group(1), used)
    return used


def is_used(rel: str, used: set[str]) -> bool:
    rel = normalize_ref(rel)
    if rel in PROTECTED or any(rel.endswith("/" + p) for p in PROTECTED):
        return True
    if rel in used:
        return True
    for u in used:
        u = normalize_ref(u)
        if rel == u or rel.endswith("/" + u) or u.endswith("/" + rel):
            return True
    return False


def main() -> None:
    import sys
    dry_run = "--apply" not in sys.argv
    static_files = collect_static_files()
    used: set[str] = set()
    for text in collect_sources().values():
        used.update(extract_refs(text))
    used = transitive_closure(used)

    unused = [f for f in static_files if not is_used(f, used)]
    used_files = [f for f in static_files if is_used(f, used)]

    print(f"Total: {len(static_files)} | Utilisés: {len(used_files)} | À supprimer: {len(unused)}")
    for f in unused:
        print(f"DELETE\t{f}")

    deleted = 0
    for rel in unused:
        path = STATIC / rel
        if path.is_file():
            if dry_run:
                continue
            path.unlink()
            deleted += 1
    if not dry_run:
        for d in sorted(STATIC.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    mode = "DRY-RUN" if dry_run else "APPLIQUÉ"
    print(f"\n{mode}: {deleted if not dry_run else len(unused)} fichiers")
    if dry_run:
        print("Relancer avec --apply pour supprimer.")


if __name__ == "__main__":
    main()
