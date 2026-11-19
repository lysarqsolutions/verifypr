"""Regression tests from the Phase 3 review."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from tests.ai_helpers import classify_by_file, fake_ai, intent_reply
from tests.detector_helpers import changeset, modify_diff
from tests.gitrepo import Repo
from verifypr.cli import app
from verifypr.config import Config
from verifypr.intent.classifier import IntentRequest, run_ai_checks
from verifypr.intent.contract import IntentContract, PathRules
from verifypr.llm.anthropic_client import AnthropicLLM
from verifypr.llm.base import MAX_OUTPUT_TOKENS, ProviderConfig, Usage
from verifypr.llm.fake import FakeLLM
from verifypr.llm.openai_compat import OpenAICompatLLM
from verifypr.llm.setup import LLMChoice, LLMSettings, SendSummary, choose_llm
from verifypr.models import InputLevel

runner = CliRunner()
FAKE_GH = "ghp_" + "Ab1" * 12
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"
ALL_FINE = classify_by_file({}, default=("intended", "t", "ok"))


def _diff() -> str:
    return modify_diff("src/a.py", "x = 1\n", "x = 2\n")


def _run(llm: Any, request: IntentRequest, **cs: Any) -> Any:
    changes = replace(changeset(_diff()), **cs)
    return run_ai_checks(
        llm, changes, request, LLMSettings(), Config().ignore_globs, lambda s: True, set()
    )


# ---- 1. nothing secret reaches the AI, whatever its source ---------------------------------
def test_commit_messages_and_branch_are_redacted() -> None:
    llm = fake_ai(intent_reply("g"), ALL_FINE)
    _run(
        llm,
        IntentRequest(InputLevel.AUTO),
        commit_messages=(f"fix login, token={FAKE_GH}",),
        branch=f"fix/{FAKE_AWS}",
    )
    sent = "\n".join(u for _s, u in llm.prompts)
    assert FAKE_GH not in sent
    assert FAKE_AWS not in sent
    assert "[REDACTED GitHub token]" in sent


def test_description_and_scope_are_redacted() -> None:
    contract = IntentContract(
        goal="g",
        allowed=PathRules(behaviors=(f"use key {FAKE_AWS}",)),
        assumptions=(f"token {FAKE_GH}",),
    )
    llm = fake_ai(ALL_FINE)
    _run(
        llm,
        IntentRequest(InputLevel.DESCRIBE, description=f"rotate {FAKE_GH}", contract=contract),
    )
    sent = llm.prompts[0][1]
    assert FAKE_GH not in sent
    assert FAKE_AWS not in sent


# ---- 2. generous output limits (thinking counts against them) ------------------------------
def test_every_ai_call_allows_enough_output() -> None:
    llm = fake_ai(intent_reply("g"), ALL_FINE)
    _run(llm, IntentRequest(InputLevel.AUTO))
    assert llm.max_tokens == [MAX_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS]
    assert MAX_OUTPUT_TOKENS >= 16_000


# ---- 3. prompt caching: shared prefix sent separately and marked for caching ----------------
class _Spy:
    provider, model = "anthropic", "claude-opus-5-5"

    def __init__(self) -> None:
        self.usage = Usage()
        self.calls: list[dict[str, Any]] = []
        self.inner = fake_ai(intent_reply("g"), ALL_FINE)

    def complete_json(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self.inner.complete_json(**kwargs)


def test_classify_sends_task_and_context_as_a_cacheable_prefix() -> None:
    spy = _Spy()
    _run(spy, IntentRequest(InputLevel.AUTO), branch="feature/x")
    classify = spy.calls[1]
    assert "Branch name: feature/x" in classify["prefix"]
    assert "<untrusted_change" not in classify["prefix"]
    assert classify["user"].lstrip().startswith("<untrusted_change")


def test_anthropic_marks_system_and_prefix_for_caching() -> None:
    calls: list[dict[str, Any]] = []
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="{}")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )

    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return response

    sdk: Any = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    llm = AnthropicLLM(ProviderConfig("anthropic", "claude-opus-5-5", "k"), sdk=sdk)
    llm.complete_json(system="SYS", user="CHANGES", schema={}, max_tokens=10, prefix="TASK")
    call = calls[0]
    assert call["system"] == [
        {"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}
    ]
    assert call["messages"][0]["content"] == [
        {"type": "text", "text": "TASK", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "CHANGES"},
    ]


# ---- 4. token parameter name per provider ---------------------------------------------------
@pytest.mark.parametrize(
    ("provider", "param"),
    [("openai", "max_completion_tokens"), ("ollama", "max_tokens"), ("openrouter", "max_tokens")],
)
def test_openai_compat_token_parameter(provider: str, param: str) -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        body = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        return httpx.Response(200, json=body)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    OpenAICompatLLM(ProviderConfig(provider, "m", "k"), http=http).complete_json(
        system="s", user="u", schema={}, max_tokens=99, prefix="p-"
    )
    assert seen[0][param] == 99
    assert seen[0]["messages"][1]["content"] == "p-u"


# ---- 5. intent init: honest wording, no base branch needed ----------------------------------
def test_intent_init_wording_and_works_without_a_base_branch(
    repo_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = Repo(repo_dir, branch="trunk")
    repo.write("src/a.py", "x = 1\n")
    repo.commit()
    proposal = {
        "goal": "g",
        "allowed_paths": [],
        "forbidden_paths": [],
        "allowed_behaviors": [],
        "forbidden_behaviors": [],
    }
    llm = fake_ai(proposal)
    monkeypatch.setattr("verifypr.cli.choose_llm", lambda *a, **k: LLMChoice(llm, True))
    out = runner.invoke(app, ["intent", "init", "Do a thing", "--repo", str(repo_dir)]).output
    assert "Your description and the names of your project's top folders (no code)" in out
    assert "0 changed files" not in out
    assert "goal: g" in out


def test_summary_describe_with_custom_what() -> None:
    text = SendSummary("anthropic", "claude-opus-5-5", 0, 10, 10, 10, what="Your text").describe()
    assert text.startswith("Your text would be sent to anthropic (claude-opus-5-5).")


# ---- 6. Anthropic sign-in without an API key ------------------------------------------------
def test_auth_token_counts_as_signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    assert choose_llm(LLMSettings()).client is None
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "oauth-token-value")
    assert choose_llm(LLMSettings()).client is not None
    status = runner.invoke(app, ["key", "status"]).output
    assert "anthropic: signed in through the ANTHROPIC_AUTH_TOKEN environment variable" in status
    assert "oauth-token-value" not in status


def test_ant_auth_login_profile_counts_as_signed_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "cfg"
    (config / "anthropic").mkdir(parents=True)
    (config / "anthropic" / "profiles.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    assert choose_llm(LLMSettings()).client is not None


# ---- 7. formatting-only changes are not sent; 8. cost is reported ---------------------------
def test_formatting_only_changes_are_not_sent() -> None:
    diff = modify_diff("src/a.py", "x = 1\n", "x = 2\n") + modify_diff(
        "src/b.py", "a\nb\n", "a\r\nb\r\n"
    )
    llm = fake_ai(intent_reply("g"), ALL_FINE)
    result = run_ai_checks(
        llm, changeset(diff), IntentRequest(InputLevel.AUTO), LLMSettings(),
        Config().ignore_globs, lambda s: True, set(),
    )  # fmt: skip
    assert 'file="src/b.py"' not in llm.prompts[1][1]
    assert result.skipped == [
        "1 formatting-only change was not sent to the AI (already covered by the tidy-up check)"
    ]


def test_report_shows_tokens_and_cost(repo_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = Repo(repo_dir)
    repo.write("a.py", "x = 1\n")
    repo.commit()
    repo.branch("f")
    repo.write("a.py", "x = 2\n")
    llm: FakeLLM = fake_ai(intent_reply("g"), ALL_FINE)
    monkeypatch.setattr("verifypr.cli.choose_llm", lambda *a, **k: LLMChoice(llm, True))
    data = json.loads(
        runner.invoke(app, ["check", "--repo", str(repo_dir), "--format", "json"]).stdout
    )
    assert data["ai_tokens"] > 0
    assert data["ai_cost"] == "under $0.01"
