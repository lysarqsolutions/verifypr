"""``intent init``: turn a plain-English description into a proposed Review Contract, and keep
saved contracts in the tool's state folder (never in the repository).

Public interface: ``propose_contract(llm, description, files)``, ``saved_contract(root)``,
``save_contract(root, contract)``, ``clear_contract(root)``, ``contract_yaml(contract)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from verifypr.analysis.redaction import redact
from verifypr.intent.contract import IntentContract, PathRules
from verifypr.intent.prompts import load_prompt, render, untrusted
from verifypr.llm.base import LLMClient, ask_json
from verifypr.state import read_json, repo_key, write_json

CONTRACTS_FILE = "contracts.json"
CONTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "allowed_paths": {"type": "array", "items": {"type": "string"}},
        "forbidden_paths": {"type": "array", "items": {"type": "string"}},
        "allowed_behaviors": {"type": "array", "items": {"type": "string"}},
        "forbidden_behaviors": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "goal",
        "allowed_paths",
        "forbidden_paths",
        "allowed_behaviors",
        "forbidden_behaviors",
    ],
    "additionalProperties": False,
}


class _Proposal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    goal: str
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    allowed_behaviors: list[str] = Field(default_factory=list)
    forbidden_behaviors: list[str] = Field(default_factory=list)


def _top_folders(files: list[str], depth: int = 2, limit: int = 80) -> list[str]:
    folders = sorted({"/".join(p.split("/")[:depth]) for p in files if "/" in p})
    return folders[:limit]


def _clean(items: list[str], limit: int) -> tuple[str, ...]:
    return tuple(i.strip()[:120] for i in items if i.strip())[:limit]


def propose_contract(llm: LLMClient, description: str, files: list[str]) -> IntentContract:
    folders = _top_folders(files)
    user = render(
        "propose_contract",
        task=untrusted("description", redact(description)),
        folders=untrusted("context", "\n".join(f"- {f}" for f in folders) or "(none)"),
    )
    proposal = ask_json(
        llm,
        system=load_prompt("system"),
        user=user,
        schema=CONTRACT_SCHEMA,
        model=_Proposal,
    )
    return IntentContract(
        goal=proposal.goal.strip()[:300] or description,
        allowed=PathRules(
            paths=_clean(proposal.allowed_paths, 20),
            behaviors=_clean(proposal.allowed_behaviors, 4),
        ),
        forbidden=PathRules(
            paths=_clean(proposal.forbidden_paths, 20),
            behaviors=_clean(proposal.forbidden_behaviors, 4),
        ),
    )


def contract_yaml(contract: IntentContract) -> str:
    data: dict[str, Any] = contract.model_dump(mode="json", exclude_defaults=False)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def saved_contract(root: Path) -> IntentContract | None:
    raw = read_json(CONTRACTS_FILE).get(repo_key(root))
    if not isinstance(raw, dict):
        return None
    try:
        return IntentContract.model_validate(raw)
    except ValidationError:
        return None


def save_contract(root: Path, contract: IntentContract) -> None:
    data = read_json(CONTRACTS_FILE)
    data[repo_key(root)] = contract.model_dump(mode="json")
    write_json(CONTRACTS_FILE, data)


def clear_contract(root: Path) -> bool:
    data = read_json(CONTRACTS_FILE)
    if data.pop(repo_key(root), None) is None:
        return False
    write_json(CONTRACTS_FILE, data)
    return True
