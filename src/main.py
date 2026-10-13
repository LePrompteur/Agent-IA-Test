"""
CLI de l'agent de test autonome Claude.

  python src/main.py --scenario scenarios/01_e2e_auth_nominal.json
  python src/main.py --run-all [--filter E2E]
  python src/main.py --debug <URL_OU_FICHIER_SOURCE> [--source-dir ./app] [--apply]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

from agent.config import load_config  # noqa: E402
from agent.llm import LLMError  # noqa: E402
from agent.runner import Runner  # noqa: E402
from tools.browser import BrowserLaunchError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent de test autonome Claude : tests E2E, débug et correction de code.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scenario", type=Path, help="Fichier JSON du scénario à exécuter.")
    mode.add_argument("--run-all", action="store_true", help="Exécuter tous les scénarios du dossier scenarios/.")
    mode.add_argument("--debug", metavar="URL_OU_FICHIER", help="Diagnostiquer une URL ou un fichier source et proposer un correctif.")
    parser.add_argument("--source-dir", type=Path, help="Code source de l'application testée : active l'analyse de cause racine dans le code et les correctifs.")
    parser.add_argument("--apply", action="store_true", help="Écrire les correctifs sur disque (sinon : diff proposé uniquement).")
    parser.add_argument("--filter", help="Avec --run-all : ne garder que les scénarios dont le nom contient ce texte.")
    parser.add_argument("--scenarios-dir", type=Path, default=ROOT / "scenarios")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "config.json")
    parser.add_argument("--headed", action="store_true", help="Afficher le navigateur.")
    parser.add_argument("--model", help="Surcharger le modèle Claude défini dans la configuration.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env")
    config = load_config(args.config)
    if args.headed:
        config["headless"] = False
    if args.model:
        config.setdefault("llm", {})["model"] = args.model
    if args.apply and not args.source_dir and not (args.debug and not args.debug.startswith("http")):
        print("--apply nécessite --source-dir (ou --debug sur un fichier source).", file=sys.stderr)
        return 2
    source_dir = args.source_dir.resolve() if args.source_dir else None
    runner = Runner(config, source_dir=source_dir, apply_fixes=args.apply)
    try:
        if args.scenario:
            result = runner.run_scenario(args.scenario)
            return 0 if result["status"] == "PASSED" else 1
        if args.run_all:
            results = runner.run_all(args.scenarios_dir, only=args.filter)
            failed = [r for r in results if r["status"] not in ("PASSED", "SKIPPED") and not r.get("eval_conform")]
            return 0 if not failed else 1
        report = runner.debug_target(args.debug)
        return 0 if report["verdict"]["status"] == "DIAGNOSED" else 1
    except LLMError as exc:
        print(f"Erreur Claude : {exc}", file=sys.stderr)
        return 3
    except BrowserLaunchError as exc:
        print(f"Navigateur : {exc}", file=sys.stderr)
        return 4
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        runner.shutdown()


if __name__ == "__main__":
    sys.exit(main())
