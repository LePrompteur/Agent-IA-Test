"""
Outils d'accès au code source applicatif, confinés au dossier --source-dir.

Les correctifs sont toujours enregistrés sous forme de diff ; ils ne sont écrits
sur disque que si apply=True (option --apply de la CLI).
"""

from __future__ import annotations

import difflib
import fnmatch
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from tools.browser import ToolInputError, ToolOutcome

IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "reports"}
MAX_FILE_BYTES = 1_000_000
MAX_READ_LINES = 400


@dataclass
class ProposedFix:
    path: str
    rationale: str
    diff: str
    applied: bool
    backup: str | None = None


class CodeWorkspace:
    def __init__(self, source_dir: Path, apply: bool, backup_dir: Path):
        self.root = source_dir.resolve()
        if not self.root.is_dir():
            raise ValueError(f"Dossier source introuvable : {self.root}")
        self.apply = apply
        self.backup_dir = backup_dir
        self.fixes: list[ProposedFix] = []

    def _resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise ToolInputError("Accès refusé : chemin hors du dossier source.")
        return path

    def _iter_files(self, glob: str | None):
        pattern = glob or "**/*"
        for path in self.root.rglob("*"):
            if not path.is_file() or any(part in IGNORED_DIRS for part in path.relative_to(self.root).parts):
                continue
            rel = path.relative_to(self.root).as_posix()
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(path.name, pattern):
                yield path, rel

    def list_source_files(self, glob: str | None = None) -> ToolOutcome:
        files = [rel for _, rel in self._iter_files(glob)]
        shown = files[:300]
        text = "\n".join(shown) or "Aucun fichier."
        if len(files) > len(shown):
            text += f"\n… {len(files) - len(shown)} fichiers supplémentaires : affinez le motif."
        return ToolOutcome(text)

    def search_code(self, pattern: str, glob: str | None = None) -> ToolOutcome:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise ToolInputError(f"Expression régulière invalide : {exc}") from exc
        hits = []
        for path, rel in self._iter_files(glob):
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    hits.append(f"{rel}:{i}:{line.strip()[:200]}")
                    if len(hits) >= 80:
                        return ToolOutcome("\n".join(hits) + "\n… résultats tronqués à 80.")
        return ToolOutcome("\n".join(hits) or "Aucune occurrence.")

    def read_source_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> ToolOutcome:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolInputError(f"Fichier introuvable : {path}")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise ToolInputError("Fichier trop volumineux pour être lu.")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line or 1))
        end = min(len(lines), int(end_line or start + MAX_READ_LINES - 1), start + MAX_READ_LINES - 1)
        body = "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(start, end + 1))
        suffix = f"\n… fichier de {len(lines)} lignes : lire la suite avec start_line={end + 1}." if end < len(lines) else ""
        return ToolOutcome(f"{path} (lignes {start}-{end} sur {len(lines)})\n{body}{suffix}")

    def propose_fix(self, path: str, old_string: str, new_string: str, rationale: str) -> ToolOutcome:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolInputError(f"Fichier introuvable : {path}")
        original = target.read_text(encoding="utf-8")
        count = original.count(old_string)
        if count != 1:
            raise ToolInputError(
                f"old_string doit apparaître exactement une fois dans {path} (trouvé {count} fois). "
                "Relisez le fichier et élargissez l'extrait."
            )
        updated = original.replace(old_string, new_string, 1)
        diff = "".join(difflib.unified_diff(
            original.splitlines(keepends=True), updated.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}",
        ))
        backup = None
        if self.apply:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = self.backup_dir / (path.replace("/", "__") + ".orig")
            shutil.copy2(target, backup_path)
            target.write_text(updated, encoding="utf-8")
            backup = str(backup_path)
        self.fixes.append(ProposedFix(path=path, rationale=rationale, diff=diff, applied=self.apply, backup=backup))
        state = f"APPLIQUÉ (sauvegarde : {backup})" if self.apply else "PROPOSÉ (non appliqué : relancer avec --apply pour l'écrire)"
        return ToolOutcome(f"Correctif {state}.\n{diff}")
