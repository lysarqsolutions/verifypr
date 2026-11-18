from __future__ import annotations

from pathlib import Path

import pytest

from tests.gitrepo import Repo
from verifypr.errors import NoBaseBranchError, NotAGitRepoError
from verifypr.models import ChangeKind
from verifypr.sources.local_git import CompareOptions, LocalGit


def _feature_repo(path: Path) -> Repo:
    repo = Repo(path)
    repo.write("app.py", "def total(a, b):\n    return a + b\n")
    repo.commit("initial")
    repo.branch("feature")
    repo.write("app.py", "def total(a, b):\n    return a + b\n\n\ndef avg(a, b):\n    return 1\n")
    repo.commit("add avg")
    repo.write("README.md", "unsaved\n")
    repo.git("add", "README.md")
    repo.write("notes/new.txt", "scratch\n")
    return repo


def test_default_includes_committed_unsaved_and_new_files(repo_dir: Path) -> None:
    _feature_repo(repo_dir)
    changes = LocalGit.open(repo_dir).collect(CompareOptions())
    paths = {f.path: f for f in changes.files}
    assert set(paths) == {"app.py", "README.md", "notes/new.txt"}
    assert paths["notes/new.txt"].untracked
    assert changes.compared == (
        "Your branch (1 commit) + unsaved changes + 1 new file, compared with `main`"
    )
    assert changes.base_label == "main"
    assert changes.read_new("notes/new.txt") == b"scratch\n"
    assert changes.read_old("app.py") == b"def total(a, b):\n    return a + b\n"
    assert changes.read_old("README.md") is None


def test_committed_only_and_head_and_staged(repo_dir: Path) -> None:
    _feature_repo(repo_dir)
    git = LocalGit.open(repo_dir)
    committed = git.collect(CompareOptions(committed_only=True))
    assert [f.path for f in committed.files] == ["app.py"]
    assert committed.compared == "1 commit, compared with `main`"
    head = git.collect(CompareOptions(head="feature"))
    assert [f.path for f in head.files] == ["app.py"]
    staged = git.collect(CompareOptions(staged=True))
    assert [f.path for f in staged.files] == ["README.md"]
    assert staged.read_new("README.md") == b"unsaved\n"


def test_not_a_git_folder(tmp_path: Path) -> None:
    with pytest.raises(NotAGitRepoError, match="isn't a git project"):
        LocalGit.open(tmp_path)


def test_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(NotAGitRepoError, match="doesn't exist"):
        LocalGit.open(tmp_path / "nope")


def test_empty_repo_counts_everything_as_new(repo_dir: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("a.txt", "a\n")
    changes = LocalGit.open(repo_dir).collect(CompareOptions())
    assert [f.path for f in changes.files] == ["a.txt"]
    assert "no commits yet" in changes.compared
    assert any("no commits yet" in n for n in changes.notes)


def test_no_base_branch_found(repo_dir: Path) -> None:
    repo = Repo(repo_dir, branch="trunk")
    repo.write("a.txt", "a\n")
    repo.commit()
    with pytest.raises(NoBaseBranchError, match="Couldn't find a main branch") as info:
        LocalGit.open(repo_dir).collect(CompareOptions())
    assert info.value.hint is not None
    assert "--base" in info.value.hint


def test_unknown_base_branch(repo_dir: Path) -> None:
    _feature_repo(repo_dir)
    with pytest.raises(NoBaseBranchError, match="`nope`"):
        LocalGit.open(repo_dir).collect(CompareOptions(base="nope"))


def test_master_and_develop_fallback(repo_dir: Path) -> None:
    repo = Repo(repo_dir, branch="develop")
    repo.write("a.txt", "a\n")
    repo.commit()
    repo.branch("feature")
    assert LocalGit.open(repo_dir).collect(CompareOptions()).base_label == "develop"


def test_detached_head_note(repo_dir: Path) -> None:
    repo = _feature_repo(repo_dir)
    repo.git("checkout", "-q", "--detach")
    changes = LocalGit.open(repo_dir).collect(CompareOptions())
    assert any("detached HEAD" in n for n in changes.notes)


def test_shallow_clone_falls_back_with_note(tmp_path: Path) -> None:
    origin = Repo(tmp_path / "origin")
    origin.write("a.txt", "1\n")
    origin.commit("one")
    origin.write("a.txt", "2\n")
    origin.commit("two")
    origin.branch("feature")
    origin.write("b.txt", "feature\n")
    origin.commit("feature work")
    origin.git("checkout", "-q", "main")
    origin.write("a.txt", "3\n")
    origin.commit("three")
    clone = tmp_path / "clone"
    Repo(tmp_path, init=False).git(
        "clone",
        "-q",
        "--depth",
        "1",
        "--no-single-branch",
        (tmp_path / "origin").as_uri(),
        str(clone),
    )
    cloned = Repo(clone, init=False)
    cloned.git("checkout", "-q", "feature")
    changes = LocalGit.open(clone).collect(CompareOptions(base="origin/main"))
    assert any("shallow clone" in n for n in changes.notes)
    assert any("fetch-depth: 0" in n for n in changes.notes)


def test_submodule_pointer_change(tmp_path: Path) -> None:
    lib = Repo(tmp_path / "lib")
    lib.write("x.txt", "1\n")
    lib.commit("lib one")
    app = Repo(tmp_path / "app")
    app.write("a.txt", "a\n")
    app.commit()
    app.git(
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        (tmp_path / "lib").as_uri(),
        "libs/lib",
    )
    app.commit("add submodule")
    app.branch("feature")
    lib.write("x.txt", "2\n")
    lib.commit("lib two")
    Repo(tmp_path / "app" / "libs" / "lib", init=False).git("pull", "-q")
    changes = LocalGit.open(tmp_path / "app").collect(CompareOptions())
    sub = next(f for f in changes.files if f.path == "libs/lib")
    assert sub.change_kind is ChangeKind.SUBMODULE


def test_untracked_lfs_pointer_and_binary(repo_dir: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("a.txt", "a\n")
    repo.commit()
    repo.branch("feature")
    repo.write("art.psd", "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 3\n")
    repo.write("tool.bin", b"\x00\x01\x02")
    files = {f.path: f for f in LocalGit.open(repo_dir).collect(CompareOptions()).files}
    assert files["art.psd"].lfs_pointer
    assert files["tool.bin"].binary


def test_sparse_checkout_note(repo_dir: Path) -> None:
    repo = _feature_repo(repo_dir)
    repo.git("config", "core.sparseCheckout", "true")
    changes = LocalGit.open(repo_dir).collect(CompareOptions())
    assert any("Sparse checkout" in n for n in changes.notes)


def test_crlf_flip_is_visible(repo_dir: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("w.txt", "one\ntwo\n")
    repo.commit()
    repo.branch("feature")
    repo.write("w.txt", "one\r\ntwo\r\n")
    [hunk] = LocalGit.open(repo_dir).collect(CompareOptions()).hunks
    assert hunk.added == ("one\r", "two\r")


def test_agent_commits_on_main_are_compared_with_remote_copy(tmp_path: Path) -> None:
    origin = Repo(tmp_path / "origin")
    origin.write("a.txt", "a\n")
    origin.commit("one")
    Repo(tmp_path, init=False).git("clone", "-q", (tmp_path / "origin").as_uri(), "work")
    work = Repo(tmp_path / "work", init=False)
    work.git("config", "core.autocrlf", "false")
    work.write(".env", "DEBUG=1\n")
    work.commit("agent work on main")
    changes = LocalGit.open(tmp_path / "work").collect(CompareOptions())
    assert changes.base_label == "origin/main"
    assert [f.path for f in changes.files] == [".env"]
    assert changes.compared == "Your branch (1 commit), compared with `origin/main`"


def test_on_main_without_remote_copy_says_so(repo_dir: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("a.txt", "a\n")
    repo.commit()
    repo.write("b.txt", "b\n")
    repo.commit("work on main")
    changes = LocalGit.open(repo_dir).collect(CompareOptions())
    assert any("no remote copy" in n and "--base HEAD~3" in n for n in changes.notes)


def test_linked_worktree(repo_dir: Path, tmp_path: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("a.txt", "a\n")
    repo.commit()
    worktree = tmp_path / "wt"
    repo.git("worktree", "add", "-q", "-b", "feature", str(worktree))
    (worktree / "a.txt").write_bytes(b"b\n")
    changes = LocalGit.open(worktree).collect(CompareOptions())
    assert [f.path for f in changes.files] == ["a.txt"]
    assert changes.base_label == "main"


def test_case_only_rename(repo_dir: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("Readme.md", "hello\n")
    repo.commit()
    repo.branch("feature")
    repo.git("mv", "Readme.md", "README.md")
    repo.commit("rename")
    [change] = LocalGit.open(repo_dir).collect(CompareOptions()).files
    assert change.change_kind is ChangeKind.RENAME
    assert (change.old_path, change.path) == ("Readme.md", "README.md")
