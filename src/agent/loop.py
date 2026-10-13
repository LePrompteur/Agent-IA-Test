"""
Boucle décisionnelle (Agent Loop) et exécuteur d'outils.

Les garde-fous sont appliqués ici, par le code, et non par le prompt :
- plafond strict d'itérations (appels au modèle) ;
- arrêt après N actions consécutives sans effet observable (DOM inchangé et
  aucune requête réseau émise).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from agent.config import redact
from tools.browser import BrowserSession, ToolInputError, ToolOutcome
from tools.code_tools import CodeWorkspace
from tools.schemas import MUTATING_TOOLS, tools_for

TERMINAL_TOOLS = {"report_result", "report_diagnosis"}
BROWSER_TOOL_NAMES = {t["name"] for t in tools_for("browser")} - {"assert_condition", "report_result"}
CODE_TOOL_NAMES = {t["name"] for t in tools_for("code")}


def _short(value: Any, limit: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


class ToolExecutor:
    """Exécute les appels d'outils de Claude et tient le journal d'actions."""

    def __init__(
        self,
        tools: list[dict],
        browser: BrowserSession | None = None,
        workspace: CodeWorkspace | None = None,
        no_change_limit: int = 3,
        secrets: set[str] | None = None,
        screenshot_on_failure: bool = True,
        log: Callable[[str], None] = print,
    ):
        self.schemas = {t["name"]: t for t in tools}
        self.browser = browser
        self.workspace = workspace
        self.no_change_limit = no_change_limit
        self.secrets = secrets or set()
        self.screenshot_on_failure = screenshot_on_failure
        self.log = log
        self.actions: list[dict] = []
        self.assertions: list[dict] = []
        self.final: dict | None = None
        self.final_tool: str | None = None
        self.no_change_streak = 0
        self.iteration = 0
        self._auto_screenshots = 0

    # ------------------------------------------------------------------ validation
    def _validate(self, name: str, tool_input: dict) -> dict:
        schema = self.schemas.get(name)
        if schema is None:
            raise ToolInputError(f"Outil inconnu ou indisponible dans ce mode : {name}")
        if not isinstance(tool_input, dict):
            raise ToolInputError("Les paramètres doivent être un objet JSON.")
        props = schema["input_schema"].get("properties", {})
        missing = [k for k in schema["input_schema"].get("required", []) if k not in tool_input]
        if missing:
            raise ToolInputError(f"Paramètres obligatoires manquants : {missing}")
        for key, spec in props.items():
            if key in tool_input and "enum" in spec and tool_input[key] not in spec["enum"]:
                raise ToolInputError(f"{key} doit valoir l'une de ces valeurs : {spec['enum']}")
        return {k: v for k, v in tool_input.items() if k in props}

    # ------------------------------------------------------------------ exécution
    def execute(self, name: str, tool_input: dict) -> ToolOutcome:
        started = time.monotonic()
        effect: bool | None = None
        try:
            args = self._validate(name, tool_input)
            if name == "assert_condition":
                outcome = self._assert(args)
            elif name in TERMINAL_TOOLS:
                self.final = args
                self.final_tool = name
                outcome = ToolOutcome("Résultat enregistré. Fin de la session.")
            elif name in CODE_TOOL_NAMES:
                if not self.workspace:
                    raise ToolInputError("Aucun dossier source fourni (--source-dir).")
                outcome = getattr(self.workspace, name)(**args)
            elif name in BROWSER_TOOL_NAMES:
                if not self.browser:
                    raise ToolInputError("Aucun navigateur actif dans ce mode.")
                if name in MUTATING_TOOLS:
                    outcome, effect = self._run_mutating(name, args)
                else:
                    outcome = getattr(self.browser, name)(**args)
            else:
                raise ToolInputError(f"Outil non pris en charge : {name}")
        except ToolInputError as exc:
            outcome = ToolOutcome(f"Erreur : {exc}", is_error=True)
        except PlaywrightTimeout as exc:
            outcome = ToolOutcome(f"Délai dépassé : {str(exc).splitlines()[0]}", is_error=True)
        except PlaywrightError as exc:
            outcome = ToolOutcome(f"Erreur navigateur : {str(exc).splitlines()[0]}", is_error=True)

        if name in MUTATING_TOOLS and self.browser:
            if outcome.is_error or effect is False:
                self.no_change_streak += 1
            else:
                self.no_change_streak = 0
            if effect is False and not outcome.is_error:
                outcome.text += " ⚠ Aucun changement observable (DOM identique, aucune requête réseau)."

        if outcome.is_error and self.browser and self.screenshot_on_failure and self._auto_screenshots < 5:
            self._auto_screenshots += 1
            path = self.browser.screenshot(f"error_{name}")
            if path:
                outcome.text += f"\n(Capture d'écran : {path})"

        outcome.text = redact(outcome.text, self.secrets)
        entry = {
            "n": len(self.actions) + 1,
            "iteration": self.iteration,
            "tool": name,
            "input": redact(tool_input, self.secrets),
            "ok": not outcome.is_error,
            "effect": effect,
            "result": _short(outcome.text, 500),
            "duration_s": round(time.monotonic() - started, 2),
        }
        self.actions.append(entry)
        self.log(f"   {'✓' if entry['ok'] else '✗'} {name} {_short(entry['input'], 120)}")
        return outcome

    def _run_mutating(self, name: str, args: dict) -> tuple[ToolOutcome, bool]:
        before = self.browser.fingerprint()
        requests_before = len(self.browser.network)
        outcome = getattr(self.browser, name)(**args)
        self.browser.settle()
        after = self.browser.fingerprint()
        effect = before != after or len(self.browser.network) != requests_before
        return outcome, effect

    def _assert(self, args: dict) -> ToolOutcome:
        record = {**args, "iteration": self.iteration}
        if self.browser:
            record["url"] = self.browser.page.url
        self.assertions.append(record)
        return ToolOutcome(f"Assertion enregistrée : {args['status']}.")

    def guard_violation(self) -> str | None:
        if self.browser and self.no_change_streak >= self.no_change_limit:
            return (
                f"{self.no_change_streak} actions consécutives sans effet observable "
                "(DOM inchangé, aucune requête réseau)."
            )
        return None


@dataclass
class LoopResult:
    stop_reason: str  # finished | end_turn | max_iterations | no_progress | refusal | max_tokens | llm_error
    iterations: int
    final_text: str = ""
    error: str | None = None
    messages: list = field(default_factory=list)


class AgentLoop:
    def __init__(self, llm, executor: ToolExecutor, tools: list[dict], max_iterations: int, log: Callable[[str], None] = print):
        self.llm = llm
        self.executor = executor
        self.tools = tools
        self.max_iterations = max_iterations
        self.log = log

    def run(self, system: str, user_content: str) -> LoopResult:
        from agent.llm import LLMError

        messages: list[dict] = [{"role": "user", "content": user_content}]
        guard_tripped: str | None = None
        for iteration in range(1, self.max_iterations + 1):
            self.executor.iteration = iteration
            self.log(f"── Tour {iteration}/{self.max_iterations}")
            try:
                response = self.llm.create(system=system, messages=messages, tools=self.tools)
            except LLMError as exc:
                if exc.fatal:
                    raise
                return LoopResult("llm_error", iteration, error=str(exc), messages=messages)
            messages.append({"role": "assistant", "content": response.content})
            text = "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
            if text:
                self.log(f"   💬 {_short(text, 200)}")

            if response.stop_reason == "refusal":
                return LoopResult("refusal", iteration, final_text=text, messages=messages)
            if response.stop_reason == "max_tokens":
                return LoopResult("max_tokens", iteration, final_text=text, messages=messages)

            tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                return LoopResult("end_turn", iteration, final_text=text, messages=messages)

            results: list[dict] = []
            for block in tool_uses:
                if guard_tripped and block.name not in TERMINAL_TOOLS:
                    outcome = ToolOutcome("Refusé : garde-fou déclenché, seul l'outil de rapport final est autorisé.", is_error=True)
                else:
                    outcome = self.executor.execute(block.name, block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": outcome.to_content(),
                    **({"is_error": True} if outcome.is_error else {}),
                })

            if self.executor.final is not None:
                messages.append({"role": "user", "content": results})
                return LoopResult("finished", iteration, final_text=text, messages=messages)

            if guard_tripped:
                messages.append({"role": "user", "content": results})
                return LoopResult("no_progress", iteration, final_text=text, error=guard_tripped, messages=messages)

            content: list[dict] = list(results)
            violation = self.executor.guard_violation()
            if violation:
                guard_tripped = violation
                self.log(f"   ⛔ Garde-fou : {violation}")
                content.append({"type": "text", "text": (
                    f"GARDE-FOU DÉCLENCHÉ : {violation} Arrêtez toute action. "
                    "Appelez immédiatement l'outil de rapport final avec le statut BLOCKED ou FAILED et la cause racine."
                )})
            elif iteration == self.max_iterations - 1:
                content.append({"type": "text", "text": (
                    "Il ne vous reste qu'un seul tour : appelez maintenant l'outil de rapport final avec votre meilleur verdict."
                )})
            messages.append({"role": "user", "content": content})

        return LoopResult(
            "no_progress" if guard_tripped else "max_iterations",
            self.max_iterations,
            error=guard_tripped or f"Plafond de {self.max_iterations} itérations atteint.",
            messages=messages,
        )
