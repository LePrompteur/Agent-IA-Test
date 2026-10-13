"""Client Claude : un appel Messages API par tour de boucle."""

from __future__ import annotations

from dataclasses import dataclass, field

import anthropic


class LLMError(RuntimeError):
    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        # fatal : inutile de poursuivre la campagne (authentification, requête invalide).
        self.fatal = fatal


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    calls: int = 0

    def add(self, usage) -> None:
        self.calls += 1
        for name in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            setattr(self, name, getattr(self, name) + (getattr(usage, name, 0) or 0))

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class ClaudeClient:
    config: dict
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self):
        llm = self.config.get("llm", {})
        self.model = llm.get("model", "claude-opus-5-5")
        self.max_tokens = int(llm.get("max_tokens", 16000))
        self.effort = llm.get("effort", "high")
        self.fallbacks = llm.get("refusal_fallbacks", True)
        try:
            self.client = anthropic.Anthropic(max_retries=int(llm.get("max_retries", 3)))
        except anthropic.AnthropicError as exc:
            raise LLMError(f"Client Anthropic non initialisable : {exc}", fatal=True) from exc

    def create(self, system: str, messages: list[dict], tools: list[dict]):
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            # Mise en cache automatique du préfixe (outils + system + historique).
            cache_control={"type": "ephemeral"},
        )
        try:
            if self.fallbacks:
                response = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            else:
                response = self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise LLMError(
                "Authentification Anthropic refusée : définissez ANTHROPIC_API_KEY "
                "(ou connectez-vous avec `ant auth login`).", fatal=True
            ) from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Requête refusée par l'API (400) : {exc.message}", fatal=True) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Limite de débit atteinte après plusieurs tentatives (429).") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Erreur API {exc.status_code} : {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Connexion à l'API impossible : {exc}") from exc
        except anthropic.AnthropicError as exc:
            raise LLMError(str(exc)) from exc
        except TypeError as exc:
            # Levée par le SDK quand aucun identifiant n'est configuré.
            if "authentication" not in str(exc):
                raise
            raise LLMError(
                "Aucun identifiant Anthropic : définissez ANTHROPIC_API_KEY "
                "(ou connectez-vous avec `ant auth login`).", fatal=True
            ) from exc
        self.usage.add(response.usage)
        return response
