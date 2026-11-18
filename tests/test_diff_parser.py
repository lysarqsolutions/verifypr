from __future__ import annotations

from verifypr.analysis.diff_parser import parse_diff, unquote_git_path
from verifypr.models import ChangeKind

MODIFY = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
 def total(a, b):
-    return a + b
+    return a + b + 0
+
 # end
"""


def test_modify_with_line_numbers() -> None:
    [parsed] = parse_diff(MODIFY)
    assert parsed.change.path == "src/app.py"
    assert parsed.change.change_kind is ChangeKind.MODIFY
    assert parsed.change.language == "python"
    [hunk] = parsed.hunks
    assert hunk.removed == ("    return a + b",)
    assert hunk.removed_at == (2,)
    assert hunk.added == ("    return a + b + 0", "")
    assert hunk.added_at == (2, 3)
    assert parsed.change.added_lines == 2
    assert parsed.change.removed_lines == 1


def test_hunk_ids_are_stable_and_unique() -> None:
    first = parse_diff(MODIFY)[0].hunks[0].id
    assert first == parse_diff(MODIFY)[0].hunks[0].id
    twice = MODIFY + MODIFY.split("\n", 4)[4].replace("@@ -1,3 +1,4 @@", "@@ -10,3 +11,4 @@")
    ids = [h.id for h in parse_diff(twice)[0].hunks]
    assert len(ids) == 2
    assert len(set(ids)) == 2


def test_new_deleted_renamed_moved() -> None:
    text = """\
diff --git a/new.txt b/new.txt
new file mode 100644
index 0000000..3b18e51
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+hello
diff --git a/old.txt b/old.txt
deleted file mode 100644
index 3b18e51..0000000
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
diff --git a/a/x.py b/a/y.py
similarity index 100%
rename from a/x.py
rename to a/y.py
diff --git a/a/z.py b/b/z.py
similarity index 100%
rename from a/z.py
rename to b/z.py
"""
    files = {p.change.path: p.change for p in parse_diff(text)}
    assert files["new.txt"].change_kind is ChangeKind.ADD
    assert files["old.txt"].change_kind is ChangeKind.DELETE
    assert files["a/y.py"].change_kind is ChangeKind.RENAME
    assert files["a/y.py"].old_path == "a/x.py"
    assert files["b/z.py"].change_kind is ChangeKind.MOVE


def test_mode_binary_submodule() -> None:
    text = """\
diff --git a/run.sh b/run.sh
old mode 100644
new mode 100755
diff --git a/logo.bin b/logo.bin
index 1111111..2222222 100644
Binary files a/logo.bin and b/logo.bin differ
diff --git a/libs/core b/libs/core
index 1111111..2222222 160000
--- a/libs/core
+++ b/libs/core
@@ -1 +1 @@
-Subproject commit 1111111111111111111111111111111111111111
+Subproject commit 2222222222222222222222222222222222222222
"""
    files = {p.change.path: p.change for p in parse_diff(text)}
    assert files["run.sh"].change_kind is ChangeKind.MODE_CHANGE
    assert (files["run.sh"].old_mode, files["run.sh"].new_mode) == ("100644", "100755")
    assert files["logo.bin"].binary
    assert files["libs/core"].change_kind is ChangeKind.SUBMODULE


def test_crlf_and_no_newline_marker_are_preserved() -> None:
    text = (
        "diff --git a/w.txt b/w.txt\n--- a/w.txt\n+++ b/w.txt\n@@ -1 +1 @@\n"
        "-line\n\\ No newline at end of file\n+line\r\n"
    )
    [hunk] = parse_diff(text)[0].hunks
    assert hunk.removed == ("line",)
    assert hunk.added == ("line\r",)


def test_quoted_paths() -> None:
    assert unquote_git_path('"caf\\303\\251 menu.txt"') == "café menu.txt"
    assert unquote_git_path('"tab\\there"') == "tab\there"
    assert unquote_git_path("plain.txt") == "plain.txt"
    text = (
        'diff --git "a/my file.txt" "b/my file.txt"\n'
        "new file mode 100644\n--- /dev/null\n"
        '+++ "b/my file.txt"\n@@ -0,0 +1 @@\n+x\n'
    )
    assert parse_diff(text)[0].change.path == "my file.txt"


def test_header_paths_used_when_no_content() -> None:
    text = (
        "diff --git a/dir with space/f.sh b/dir with space/f.sh\nold mode 100644\nnew mode 100755\n"
    )
    assert parse_diff(text)[0].change.path == "dir with space/f.sh"


def test_lfs_pointer_detected() -> None:
    text = (
        "diff --git a/big.psd b/big.psd\nnew file mode 100644\n--- /dev/null\n+++ b/big.psd\n"
        "@@ -0,0 +1,3 @@\n+version https://git-lfs.github.com/spec/v1\n+oid sha256:abc\n+size 9\n"
    )
    assert parse_diff(text)[0].change.lfs_pointer


def test_empty_input() -> None:
    assert parse_diff("") == []
