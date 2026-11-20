"""Core data models shared by every pipeline stage.

Public interface: ``Hunk``, ``Evidence``, ``Finding``, ``Report`` and the enums
``ChangeKind``, ``Severity``, ``Classification``, ``Verdict``, ``InputLevel``.
Internal names live here; user-facing wording lives in ``verifypr.render.labels``.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1"


class ChangeKind(str, Enum):
    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"
    MOVE = "move"
    MODE_CHANGE = "mode_change"
    BINARY = "binary"
    SUBMODULE = "submodule"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def weight(self) -> int:
        return {"high": 3, "medium": 2, "low": 1}[self.value]


class Classification(str, Enum):
    INTENDED = "intended"
    SUPPORTING = "supporting"
    UNINTENDED = "unintended"
    UNCLEAR = "unclear"


class Verdict(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class InputLevel(str, Enum):
    AUTO = "auto"
    DESCRIBE = "describe"
    REQUIREMENTS = "requirements"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Hunk(_Model):
    """One contiguous change in one file. ``id`` must be stable across runs."""

    id: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    old_path: str | None = None
    change_kind: ChangeKind
    old_start: int = Field(ge=0)
    old_lines: int = Field(ge=0)
    new_start: int = Field(ge=0)
    new_lines: int = Field(ge=0)
    language: str | None = None
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    added_at: tuple[int, ...] = Field(
        default=(), description="New-file line number per added line."
    )
    removed_at: tuple[int, ...] = Field(
        default=(), description="Old-file line number per removed line."
    )
    raw: tuple[str, ...] = Field(
        default=(), repr=False, description="The hunk exactly as in the diff (for undo patches)."
    )


class FileChange(_Model):
    """File-level facts about one changed file (its hunks are separate ``Hunk`` objects)."""

    path: str = Field(min_length=1)
    old_path: str | None = None
    change_kind: ChangeKind
    language: str | None = None
    old_mode: str | None = None
    new_mode: str | None = None
    binary: bool = False
    untracked: bool = False
    lfs_pointer: bool = False
    added_lines: int = Field(default=0, ge=0)
    removed_lines: int = Field(default=0, ge=0)
    patch_header: tuple[str, ...] = Field(
        default=(), repr=False, description="The file's diff header lines (for undo patches)."
    )


class Evidence(_Model):
    """Where a finding comes from: a file and an inclusive line range."""

    file_path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    snippet: str | None = None
    file_level: bool = Field(
        default=False, description="About the whole file; line numbers are not meaningful."
    )

    @model_validator(mode="after")
    def _check_range(self) -> Evidence:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class Finding(_Model):
    """A single issue. ``problem_id`` (U-number) is internal and never shown to users."""

    id: str = Field(min_length=1)
    problem_id: str = Field(pattern=r"^U\d+$")
    category: str = Field(min_length=1)
    severity: Severity
    confidence: int = Field(ge=0, le=100)
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    title: str = Field(min_length=1, description="Plain-language one-liner for users.")
    why: str = Field(min_length=1, description="One-sentence plain-language explanation.")
    check_item: str | None = Field(
        default=None, description="Wording for the 'Please check before approving' list."
    )
    classification: Classification | None = None
    critical: bool = Field(
        default=False,
        description="Clear rule-based critical finding (e.g. committed secret); may FAIL in "
        "any mode.",
    )
    inferred: bool = Field(
        default=False, description="Depends on inferred intent: capped at WARN in Auto mode."
    )

    @property
    def priority(self) -> int:
        """Ranking key: severity weight x confidence (higher = more important)."""
        return self.severity.weight * self.confidence


def _worth_a_look(finding: Finding) -> bool:
    return finding.severity is Severity.HIGH and finding.confidence < 50


class ClassifiedChange(_Model):
    """How one change relates to what was asked (internal names; see render.labels)."""

    hunk_id: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    classification: Classification
    reason: str
    theme: str | None = None
    supports: str | None = Field(default=None, description="Hunk id this change supports.")
    confidence: int = Field(ge=0, le=100)
    ai: bool = Field(default=True, description="False when the AI couldn't check this part.")


class Progress(_Model):
    """Compared with the previous check of the same project ("Check again")."""

    fixed: int = Field(ge=0)
    still_open: int = Field(ge=0)
    new: int = Field(ge=0)
    previous: int = Field(ge=0)

    def text(self) -> str:
        issue = "issue" if self.new == 1 else "issues"
        return (
            f"Fixed {self.fixed} of {self.previous} · {self.still_open} still open · "
            f"{self.new} new {issue}"
        )


class Report(_Model):
    schema_version: str = SCHEMA_VERSION
    verdict: Verdict
    input_level: InputLevel = InputLevel.AUTO
    compared: str = Field(min_length=1, description="Plain description of what was compared.")
    base: str | None = Field(default=None, description="What the changes were compared with.")
    findings: tuple[Finding, ...] = ()
    skipped: tuple[str, ...] = ()
    notes: tuple[str, ...] = Field(default=(), description="Friendly notes, e.g. fallbacks used.")
    ai_used: bool = False
    file_count: int = Field(default=0, ge=0)
    allowed_count: int = Field(default=0, ge=0, description="Findings suppressed by allow rules.")
    changes: tuple[ClassifiedChange, ...] = ()
    intent: str | None = Field(default=None, description="What the change was checked against.")
    intent_inferred: bool = False
    ai_model: str | None = None
    ai_tokens: int = Field(default=0, ge=0)
    ai_cost: str | None = Field(default=None, description="Estimated cost of the AI calls.")
    kept_count: int = Field(default=0, ge=0, description="Findings marked 'It's fine'.")
    progress: Progress | None = None
    view_only: bool = False
    offline: bool = False
    attention_count: int = Field(
        default=0, ge=0, description="Findings that made the verdict WARN or FAIL."
    )

    def ranked(self) -> list[Finding]:
        """All findings, highest priority first; ties keep their original order."""
        return sorted(self.findings, key=lambda f: f.priority, reverse=True)

    def top_issues(self, limit: int = 3) -> list[Finding]:
        """Highest-priority findings first, leaving out the 'worth a look' ones."""
        return [f for f in self.ranked() if not _worth_a_look(f)][:limit]

    def worth_a_look(self) -> list[Finding]:
        """Possibly important but not sure (High and < 50% sure): shown apart, not hidden."""
        return [f for f in self.ranked() if _worth_a_look(f)]

    def count(self, classification: Classification) -> int:
        return sum(1 for c in self.changes if c.classification is classification)

    def check_items(self, limit: int = 10) -> list[str]:
        """Deduplicated 'Please check before approving' items, most important first."""
        items: list[str] = []
        for finding in self.ranked():
            if finding.check_item and finding.check_item not in items:
                items.append(finding.check_item)
        return items[:limit]
