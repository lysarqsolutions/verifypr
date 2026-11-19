"""Basic behavior watch (v0.1 preview of Phase 5): simple, rule-based patterns only.

Public interface: ``detect(ctx)``.
- U18 access rules: role/permission checks, auth decorators, route guards, feature flags.
- U17 hidden or removed UI: routes, menu entries, buttons/links removed or newly conditional.
Every finding says "Basic check" so users know it's a simple pattern match.
"""

from __future__ import annotations

import re

from verifypr.analysis.globs import any_match
from verifypr.detectors.base import DetectorContext, hunk_evidence
from verifypr.detectors.common import (
    changed_lines,
    is_code_file,
    is_test_file,
    looks_like_code,
    without_strings,
)
from verifypr.models import Finding, Hunk, Severity

BASIC = "Basic check: "

_ACCESS = re.compile(
    r"(?i)\b(?:roles?|is_?admin|has_?roles?|has_?perm(?:ission)?s?|permissions?|can_?access|"
    r"is_?staff|is_?superuser|authori[sz]ed?|preauthorize|rolesallowed|login_required|"
    r"permission_required|requires_auth|canactivate|canload|auth_?guard|authori[sz]ation_?polic\w*|"
    r"feature_?flags?|is_?feature_?enabled|feature_?toggles?)\b"
)
_ACCESS_KEY = re.compile(r"""["']?\b(?:roles?|permissions?|allowed_?roles)\b["']?\s*[:=]""", re.I)
_AUTH_REQUIRED = re.compile(
    r"@login_required|@permission_required|@PreAuthorize|@RolesAllowed|@Secured|\[Authorize\b|"
    r"\brequires_auth\b|\bcanActivate\s*:|@UseGuards|\bIsAuthenticated\b|\bauthenticate\s*\(|"
    r"\bensure_logged_in\b|\brequire_login\b|\bAuthGuard\b"
)
UI_GLOBS = (
    "*.jsx",
    "*.tsx",
    "*.vue",
    "*.svelte",
    "*.html",
    "*.cshtml",
    "*.razor",
    "*.erb",
    "*.hbs",
    "*.jinja",
    "*.j2",
    "*.blade.php",
    "*.ts",
    "*.js",
)
MENU_GLOBS = ("*menu*", "*nav*", "*sidebar*", "*Menu*", "*Nav*", "*Sidebar*")
_ROUTE = re.compile(r"""(?:\bpath\s*:\s*|<Route\b[^>]*?\bpath\s*=\s*\{?\s*)['"`]([^'"`]+)['"`]""")
_MENU_ITEM = re.compile(r"""\b(?:label|title|text|name)\s*:\s*['"`]([^'"`]{2,60})['"`]""")
_UI_TAG = re.compile(
    r"<\s*(button|Button|a|Link|NavLink|MenuItem|IconButton|v-btn|mat-button|DropdownItem|"
    r"Tab|ListItem|ToolbarButton)\b"
)
_TEXT = re.compile(r">\s*([^<>{}]{2,60}?)\s*<|(?:aria-label|title|label)\s*=\s*['\"]([^'\"]{2,60})")
_CONDITION = re.compile(
    r"&&\s*[(<]?|\?\s*\(?\s*$|\bv-if\s*=|\bv-show\s*=|\*ngIf\s*=|@if\s*\(|\{#if\b"
)


def _ui_label(line: str) -> str:
    m = _TEXT.search(line)
    if m:
        return (m.group(1) or m.group(2)).strip()
    tag = _UI_TAG.search(line)
    return tag.group(1) if tag else line.strip()[:40]


def _is_access_line(line: str) -> bool:
    """Role/permission words in actual code (keys and values like ``roles: [...]`` count;
    the same words in comments, docstrings or inside other strings don't)."""
    if not looks_like_code(line):
        return False
    return bool(_ACCESS.search(without_strings(line)) or _ACCESS_KEY.search(line))


def _access_findings(hunks: list[Hunk]) -> list[Finding]:
    out: list[Finding] = []
    for hunk in hunks:
        gone, new = changed_lines(hunk)
        gone_access = [g for g in gone if _is_access_line(g)]
        new_access = [n for n in new if _is_access_line(n)]
        if not (gone_access or new_access):
            continue
        removed_auth = [g for g in gone if _AUTH_REQUIRED.search(without_strings(g))]
        if removed_auth and not any(_AUTH_REQUIRED.search(without_strings(n)) for n in new):
            line = max(hunk.new_start, 1)
            out.append(
                Finding(
                    id=f"access:removed:{hunk.id}",
                    problem_id="U18",
                    category="access_rules",
                    severity=Severity.HIGH,
                    confidence=70,
                    critical=True,
                    evidence=(hunk_evidence(hunk),),
                    title=f"A login or permission check was removed ({hunk.file_path}:{line})",
                    why=BASIC + f"`{removed_auth[0][:70]}` was removed, so this may now be open "
                    "to people who couldn't use it before.",
                    check_item=f"The code in {hunk.file_path} still requires the right login or "
                    "permission",
                )
            )
            continue
        idx = [i for i, a in enumerate(hunk.added) if a.strip() in new_access]
        ev = hunk_evidence(hunk, idx or None)
        out.append(
            Finding(
                id=f"access:changed:{hunk.id}",
                problem_id="U18",
                category="access_rules",
                severity=Severity.MEDIUM,
                confidence=70,
                evidence=(ev,),
                title=f"Access rules changed in {hunk.file_path}:{ev.start_line} — check who can "
                "still see this",
                why=BASIC + "a line that decides who can see or do something (roles, "
                "permissions, guards, or feature flags) changed.",
                check_item=f"The same people can still see and use what {hunk.file_path} controls",
            )
        )
    return out


def _ui_findings(hunks: list[Hunk]) -> list[Finding]:
    ui_hunks = [h for h in hunks if any_match(UI_GLOBS, h.file_path)]
    all_added = {a.strip() for h in hunks for a in h.added if a.strip()}
    added_routes = {m.group(1) for h in hunks for a in h.added for m in _ROUTE.finditer(a)}
    added_labels = {m.group(1) for h in hunks for a in h.added for m in _MENU_ITEM.finditer(a)}
    out: list[Finding] = []
    for hunk in ui_hunks:
        gone, _new = changed_lines(hunk)
        routes = sorted({m.group(1) for g in gone for m in _ROUTE.finditer(g)} - added_routes)
        if routes:
            out.append(
                _ui(
                    hunk,
                    "route",
                    f"A page was removed from the app's routes: {', '.join(routes[:3])}",
                    "People can no longer open this page by its address or link.",
                    f"Removing the page {routes[0]} was intended",
                    75,
                )
            )
        if any_match(MENU_GLOBS, hunk.file_path):
            items = sorted(
                {m.group(1) for g in gone for m in _MENU_ITEM.finditer(g)} - added_labels
            )
            if items:
                out.append(
                    _ui(
                        hunk,
                        "menu",
                        f"A menu item was removed: {', '.join(items[:3])}",
                        "People won't see this entry in the menu anymore.",
                        f"Removing the menu item '{items[0]}' was intended",
                        70,
                    )
                )
        removed_ui = [g for g in gone if _UI_TAG.search(g) and g not in all_added]
        newly_conditional = [
            a
            for a in hunk.added
            if _UI_TAG.search(a)
            and _CONDITION.search(a)
            and any(
                _ui_label(a) == _ui_label(r) and not _CONDITION.search(r)
                for r in hunk.removed
                if _UI_TAG.search(r)
            )
        ]
        wrapped = any(_CONDITION.search(a) for a in hunk.added) and any(
            r.strip() in all_added and _UI_TAG.search(r) for r in hunk.removed
        )
        if newly_conditional or (wrapped and not removed_ui):
            labels = [_ui_label(x) for x in newly_conditional] or [
                _ui_label(r) for r in hunk.removed if _UI_TAG.search(r)
            ]
            out.append(
                _ui(
                    hunk,
                    "conditional",
                    f"A button or link is now only shown sometimes: {labels[0]}",
                    "It's now wrapped in a condition, so some people may no longer see it.",
                    f"Everyone who needs '{labels[0]}' can still see it",
                    65,
                )
            )
            removed_ui = [g for g in removed_ui if _ui_label(g) not in labels]
        if removed_ui:
            labels = sorted({_ui_label(g) for g in removed_ui})
            out.append(
                _ui(
                    hunk,
                    "removed",
                    f"A button or link was removed: {', '.join(labels[:3])}",
                    "People can no longer click this in the app.",
                    f"Removing '{labels[0]}' was intended",
                    70,
                )
            )
    return out


def _ui(hunk: Hunk, kind: str, title: str, why: str, check: str, confidence: int) -> Finding:
    return Finding(
        id=f"ui:{kind}:{hunk.id}",
        problem_id="U17",
        category="ui_visibility",
        severity=Severity.MEDIUM,
        confidence=confidence,
        evidence=(hunk_evidence(hunk),),
        title=title,
        why=BASIC + why,
        check_item=check,
    )


def detect(ctx: DetectorContext) -> list[Finding]:
    hunks = [
        h
        for h in ctx.changes.hunks
        if not is_test_file(h.file_path)
        and (is_code_file(h.file_path) or any_match(UI_GLOBS, h.file_path))
    ]
    return _access_findings(hunks) + _ui_findings(hunks)
