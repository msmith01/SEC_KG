"""
Flexible LLM client that supports Ollama (local), Anthropic, and OpenAI.
Switch provider via LLM_PROVIDER env var or by instantiating directly.

Usage:
    from models.llm_client import LLMClient

    client = LLMClient()                          # uses config default
    client = LLMClient(provider="anthropic")      # force Claude
    client = LLMClient(provider="ollama", model="gpt-oss:20b")

    response = client.complete("Extract entities from: ...")
    response = client.complete(prompt, system="You are an NLP expert...")
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
import config
from typing import Optional

# Retry settings for Ollama (model reload can take 10–60 s after VRAM eviction)
_OLLAMA_MAX_RETRIES = 5
_OLLAMA_BACKOFF_BASE = 5   # seconds; doubles each retry: 5, 10, 20, 40, 80


class LLMClient:
    """
    Unified interface over Ollama, Anthropic, and OpenAI.
    All methods are synchronous to keep the pipeline straightforward.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.provider = provider or config.LLM_PROVIDER
        self._client = None

        if self.provider == "ollama":
            self.model = model or config.OLLAMA_MODEL
            self._init_ollama()
        elif self.provider == "anthropic":
            self.model = model or config.ANTHROPIC_MODEL
            self._init_anthropic()
        elif self.provider == "openai":
            self.model = model or config.OPENAI_MODEL
            self._init_openai()
        else:
            raise ValueError(
                f"Unknown provider '{self.provider}'. "
                "Choose from: ollama, anthropic, openai"
            )

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_ollama(self):
        try:
            import ollama
            self._ollama = ollama
        except ImportError:
            raise ImportError("pip install ollama")

    def _init_anthropic(self):
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        except ImportError:
            raise ImportError("pip install anthropic")

    def _init_openai(self):
        try:
            import openai
            self._client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        except ImportError:
            raise ImportError("pip install openai")

    # ── Public interface ──────────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        system: str = "You are a financial NLP specialist working with SEC 10-K filings.",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        """
        Send a prompt and return the model's text response.

        Args:
            prompt:     The user-facing prompt.
            system:     System / instruction message.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0 = deterministic).

        Returns:
            The model's response as a plain string.
        """
        if self.provider == "ollama":
            return self._complete_ollama(prompt, system, max_tokens, temperature)
        elif self.provider == "anthropic":
            return self._complete_anthropic(prompt, system, max_tokens, temperature)
        elif self.provider == "openai":
            return self._complete_openai(prompt, system, max_tokens, temperature)

    # ── Provider implementations ──────────────────────────────────────────────

    def _complete_ollama(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> str:
        last_exc: Exception | None = None
        for attempt in range(_OLLAMA_MAX_RETRIES):
            try:
                response = self._ollama.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": prompt},
                    ],
                    options={
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                    # Pin model in VRAM indefinitely — never auto-evict mid-run.
                    keep_alive=-1,
                )
                return response["message"]["content"].strip()
            except Exception as e:
                last_exc = e
                wait = _OLLAMA_BACKOFF_BASE * (2 ** attempt)
                print(
                    f"[llm] Ollama attempt {attempt + 1}/{_OLLAMA_MAX_RETRIES} "
                    f"failed: {e}. Retrying in {wait}s…",
                    file=sys.stderr,
                )
                time.sleep(wait)
        raise RuntimeError(
            f"Ollama failed after {_OLLAMA_MAX_RETRIES} attempts"
        ) from last_exc

    def _complete_anthropic(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    def _complete_openai(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip()

    def __repr__(self) -> str:
        return f"LLMClient(provider={self.provider!r}, model={self.model!r})"
