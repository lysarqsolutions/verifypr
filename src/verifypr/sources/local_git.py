"""Read-only access to a local git repository.

Public interface: ``CompareOptions``, ``LocalGit.open(path)``, ``LocalGit.collect(options)``.

Every git call goes through ``LocalGit._run``, which uses ``--no-optional-locks`` so even
``git status`` never rewrites the index. Only read commands are used (``rev-parse``,
``diff``, ``ls-files``, ``ls-tree``, ``cat-file``, ``merge-base``, ``rev-list``, ``status``,
``symbolic-ref``, ``config --get``). No command here may write to the repo or ``.git``.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from verifypr.analysis.changes import ChangeSet
from verifypr.analysis.diff_parser import ParsedFile, parse_diff
from verifypr.analysis.languages import language_for
from verifypr.errors import GitError, NoBaseBranchError, NotAGitRepoError, VerifyPRError
from verifypr.models import ChangeKind, FileChange, Hunk

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
BASE_CANDIDATES = ("main", "master", "develop")
MAX_UNTRACKED_BYTES = 1_000_000
_LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"

_GIT_PREFIX = (
    "git",
    "--no-optional-locks",
    "-c",
    "core.quotepath=off",
    "-c",
    "color.ui=never",
    "-c",
    "diff.noprefix=false",
    "-c",
    "diff.mnemonicPrefix=false",
)

_DIFF_ARGS = (
    "diff",
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--find-renames",
    "-U3",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "--submodule=short",
)


@dataclass(frozen=True)
class CompareOptions:
    base: str | None = None
    head: str | None = None
    staged: bool = False
    committed_only: bool = False


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class LocalGit:
    def __init__(self, root: Path) -> None:
        self.root = root

    # ---- low level -------------------------------------------------------------
    @staticmethod
    def _env() -> dict[str, str]:
        env = dict(os.environ)
        env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
        return env

    @classmethod
    def _exec(
        cls, cwd: Path, args: tuple[str, ...] | list[str], stdin: bytes | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                [*_GIT_PREFIX, *args],
                cwd=cwd,
                env=cls._env(),
                input=stdin,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise VerifyPRError(
                "Git isn't installed or isn't on your PATH.",
                hint="Install Git from https://git-scm.com and try again.",
            ) from exc

    def _run(self, *args: str, ok_codes: tuple[int, ...] = (0,)) -> bytes:
        proc = self._exec(self.root, args)
        if proc.returncode not in ok_codes:
            detail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise GitError(
                "Git couldn't read this project.",
                hint=detail[-1] if detail else f"git {args[0]} failed",
            )
        return proc.stdout

    def _try(self, *args: str) -> str | None:
        proc = self._exec(self.root, args)
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", errors="replace").strip()

    # ---- discovery -------------------------------------------------------------
    @classmethod
    def open(cls, path: Path) -> LocalGit:
        if not path.is_dir():
            raise NotAGitRepoError(f"The folder {path} doesn't exist.")
        proc = cls._exec(path, ("rev-parse", "--show-toplevel"))
        if proc.returncode != 0:
            raise NotAGitRepoError(
                "This folder isn't a git project.",
                hint="Open your project folder (the one with a .git folder) and run "
                "VerifyPR there.",
            )
        root = Path(proc.stdout.decode("utf-8", errors="replace").strip())
        return cls(root)

    def has_commits(self) -> bool:
        return self._try("rev-parse", "--verify", "-q", "HEAD^{commit}") is not None

    def current_branch(self) -> str | None:
        return self._try("symbolic-ref", "-q", "--short", "HEAD") or None

    def is_shallow(self) -> bool:
        return self._try("rev-parse", "--is-shallow-repository") == "true"

    def ref_exists(self, ref: str) -> bool:
        return self._try("rev-parse", "--verify", "-q", f"{ref}^{{commit}}") is not None

    def detect_base(self, preferred: str | None) -> str:
        if preferred:
            if self.ref_exists(preferred):
                return preferred
            raise NoBaseBranchError(
                f"Couldn't find the branch `{preferred}` to compare with.",
                hint="Check the name, or pick another one with --base <branch>.",
            )
        candidates: list[str] = list(BASE_CANDIDATES)
        origin_head = self._try("symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
        if origin_head:
            candidates.append(origin_head)
        candidates.extend(f"origin/{name}" for name in BASE_CANDIDATES)
        for ref in candidates:
            if self.ref_exists(ref):
                return ref
        raise NoBaseBranchError(
            "Couldn't find a main branch to compare with.",
            hint="Pick one with --base <branch>, for example: verifypr --base develop",
        )

    def _remote_copy(self, branch: str, notes: list[str]) -> str:
        """When you're on the base branch itself, compare with its remote copy so commits
        that haven't been pushed yet (often an agent working directly on main) are seen."""
        upstream = self._try(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch}@{{upstream}}"
        )
        for candidate in (upstream, f"origin/{branch}"):
            if candidate and self.ref_exists(candidate):
                return candidate
        notes.append(
            f"You're on `{branch}` and it has no remote copy to compare with, so only "
            "unsaved changes and new files were checked. To check commits too, compare with "
            "an earlier point, e.g. `verifypr --base HEAD~3`."
        )
        return branch

    # ---- reading ---------------------------------------------------------------
    def _diff(self, *revs: str, cached: bool = False) -> list[ParsedFile]:
        args = [*_DIFF_ARGS, *(("--cached",) if cached else ()), *revs, "--"]
        raw = self._run(*args)
        return parse_diff(raw.decode("utf-8", errors="replace"))

    def _cat(self, spec: str) -> bytes | None:
        proc = self._exec(self.root, ("cat-file", "blob", spec))
        return proc.stdout if proc.returncode == 0 else None

    def _cat_many(self, specs: dict[str, str]) -> dict[str, bytes | None]:
        """Read many blobs (``{path: "rev:path"}``) through one ``git cat-file --batch``."""
        result: dict[str, bytes | None] = {path: None for path in specs}
        usable = {p: spec for p, spec in specs.items() if "\n" not in spec}
        if not usable:
            return result
        order = list(usable)
        stdin = "".join(usable[p] + "\n" for p in order).encode("utf-8")
        proc = self._exec(self.root, ("cat-file", "--batch"), stdin=stdin)
        if proc.returncode != 0:
            return {p: self._cat(spec) for p, spec in specs.items()}
        out = proc.stdout
        pos = 0
        for path in order:
            end = out.find(b"\n", pos)
            if end == -1:
                break
            header = out[pos:end].split()
            pos = end + 1
            if len(header) != 3 or not header[2].isdigit():
                continue  # "<spec> missing" / "ambiguous"
            size = int(header[2])
            if header[1] == b"blob":
                result[path] = out[pos : pos + size]
            pos += size + 1
        return result

    def _worktree(self, path: str) -> bytes | None:
        full = (self.root / path).resolve()
        if not full.is_relative_to(self.root.resolve()) or not full.is_file():
            return None
        return full.read_bytes()

    def _untracked(self) -> list[str]:
        raw = self._run("ls-files", "-z", "--others", "--exclude-standard")
        return [p for p in raw.decode("utf-8", errors="replace").split("\0") if p]

    def _has_unsaved(self) -> bool:
        out = self._run("status", "--porcelain", "--untracked-files=no")
        return bool(out.strip())

    def _untracked_file(self, path: str) -> ParsedFile:
        full = self.root / path
        size = full.stat().st_size if full.is_file() else 0
        head = b""
        if full.is_file():
            with full.open("rb") as fh:
                head = fh.read(8192)
        binary = size > MAX_UNTRACKED_BYTES or b"\0" in head
        lfs = head.startswith(_LFS_HEADER)
        lines: list[str] = []
        if not binary and full.is_file():
            text = full.read_bytes().decode("utf-8", errors="replace")
            lines = text.split("\n")
            if lines and lines[-1] == "":
                lines.pop()
        kind = ChangeKind.ADD
        change = FileChange(
            path=path,
            change_kind=kind,
            language=language_for(path),
            binary=binary or lfs,
            untracked=True,
            lfs_pointer=lfs,
            added_lines=len(lines),
        )
        hunks: tuple[Hunk, ...] = ()
        if lines and not lfs:
            digest = hashlib.sha1(
                ("\0".join([path, "", "\n".join(lines)])).encode("utf-8", errors="surrogatepass"),
                usedforsecurity=False,
            ).hexdigest()[:12]
            hunks = (
                Hunk(
                    id=f"{path}@{digest}",
                    file_path=path,
                    change_kind=kind,
                    old_start=0,
                    old_lines=0,
                    new_start=1,
                    new_lines=len(lines),
                    language=language_for(path),
                    added=tuple(lines),
                    added_at=tuple(range(1, len(lines) + 1)),
                ),
            )
        return ParsedFile(change=change, hunks=hunks)

    # ---- main entry ------------------------------------------------------------
    def collect(self, options: CompareOptions) -> ChangeSet:
        notes: list[str] = []
        if self._try("config", "--get", "core.sparseCheckout") == "true":
            notes.append(
                "Sparse checkout is on: only files present in this folder could be checked."
            )
        if not self.has_commits():
            return self._collect_no_commits(notes)

        branch = self.current_branch()
        if options.staged:
            parsed = self._diff("HEAD", cached=True)
            return self._changeset(
                parsed,
                "your last commit",
                "Staged changes, compared with your last commit",
                notes,
                old_rev="HEAD",
                new_rev=":",
            )

        base = self.detect_base(options.base)
        if options.base is None and branch is not None and base == branch:
            base = self._remote_copy(branch, notes)
        head = options.head or "HEAD"
        if options.head and not self.ref_exists(options.head):
            raise NoBaseBranchError(
                f"Couldn't find `{options.head}`.", hint="Check the branch or commit name."
            )
        if branch is None and not options.head:
            notes.append(
                f"You're not on a branch right now (detached HEAD) — comparing this commit "
                f"with `{base}`."
            )
        start = self._merge_base(base, head, notes)

        if options.head or options.committed_only:
            parsed = self._diff(start, head)
            commits = self._commit_count(start, head)
            label = f"`{options.head}`" if options.head else _plural(commits, "commit")
            compared = f"{label[0].upper()}{label[1:]}, compared with `{base}`"
            return self._changeset(parsed, base, compared, notes, old_rev=start, new_rev=head)

        parsed = self._diff(start)
        untracked = [self._untracked_file(p) for p in self._untracked()]
        commits = self._commit_count(start, "HEAD")
        parts: list[str] = []
        if commits:
            parts.append(f"your branch ({_plural(commits, 'commit')})")
        if self._has_unsaved():
            parts.append("unsaved changes")
        if untracked:
            parts.append(_plural(len(untracked), "new file"))
        what = " + ".join(parts) if parts else "no changes"
        compared = f"{what[0].upper()}{what[1:]}, compared with `{base}`"
        return self._changeset(
            parsed + untracked, base, compared, notes, old_rev=start, new_rev=None
        )

    def _collect_no_commits(self, notes: list[str]) -> ChangeSet:
        notes.append("This project has no commits yet, so every file counts as new.")
        parsed = self._diff(EMPTY_TREE, cached=True)
        tracked = {p.change.path for p in parsed}
        untracked = [self._untracked_file(p) for p in self._untracked() if p not in tracked]
        total = len(parsed) + len(untracked)
        compared = f"{_plural(total, 'new file')} in a project with no commits yet"
        return self._changeset(
            parsed + untracked, "an empty project", compared, notes, old_rev=None, new_rev=None
        )

    def _merge_base(self, base: str, head: str, notes: list[str]) -> str:
        found = self._try("merge-base", base, head)
        if found:
            return found
        if self.is_shallow():
            notes.append(
                f"This is a shallow clone, so the point where your branch split from `{base}` "
                f"couldn't be found. Compared with the latest `{base}` instead. "
                "In CI, check out with full history (for GitHub Actions: fetch-depth: 0)."
            )
        else:
            notes.append(
                f"Your branch and `{base}` share no history. Compared with the latest `{base}`."
            )
        return base

    def _commit_count(self, start: str, end: str) -> int:
        out = self._try("rev-list", "--count", f"{start}..{end}")
        return int(out) if out and out.isdigit() else 0

    def _changeset(
        self,
        parsed: list[ParsedFile],
        base_label: str,
        compared: str,
        notes: list[str],
        *,
        old_rev: str | None,
        new_rev: str | None,
    ) -> ChangeSet:
        def read_old(path: str) -> bytes | None:
            return self._cat(f"{old_rev}:{path}") if old_rev else None

        def read_new(path: str) -> bytes | None:
            if new_rev == ":":
                return self._cat(f":{path}")
            if new_rev:
                return self._cat(f"{new_rev}:{path}")
            return self._worktree(path)

        return ChangeSet(
            files=tuple(p.change for p in parsed),
            hunks=tuple(h for p in parsed for h in p.hunks),
            base_label=base_label,
            compared=compared,
            notes=tuple(notes),
            read_old=read_old,
            read_new=read_new,
            list_files=lambda: self._list_files(new_rev),
            read_new_many=lambda paths: self._read_many(paths, new_rev),
        )

    def _read_many(self, paths: list[str], rev: str | None) -> dict[str, bytes | None]:
        if rev is None:
            return {p: self._worktree(p) for p in paths}
        prefix = ":" if rev == ":" else f"{rev}:"
        return self._cat_many({p: prefix + p for p in paths})

    def _list_files(self, rev: str | None) -> list[str]:
        """Every project file after the change (read-only), for 'who uses this file?'."""
        if rev is None:
            raw = self._run("ls-files", "-z", "--cached", "--others", "--exclude-standard")
        elif rev == ":":
            raw = self._run("ls-files", "-z", "--cached")
        else:
            raw = self._run("ls-tree", "-r", "-z", "--name-only", rev)
        return sorted({p for p in raw.decode("utf-8", errors="replace").split("\0") if p})
