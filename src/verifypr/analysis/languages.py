"""Map file paths to a language name. Public interface: ``language_for(path)``."""

from __future__ import annotations

from pathlib import PurePosixPath

_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".cs": "csharp",
    ".sql": "sql",
    ".rb": "ruby",
    ".php": "php",
    ".rs": "rust",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".csproj": "xml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".sh": "shell",
    ".ps1": "powershell",
    ".vue": "vue",
    ".gradle": "gradle",
}

_BY_NAME = {
    "Dockerfile": "docker",
    "Makefile": "make",
    "go.mod": "go-mod",
}


def language_for(path: str) -> str | None:
    p = PurePosixPath(path)
    if p.name in _BY_NAME:
        return _BY_NAME[p.name]
    return _BY_SUFFIX.get(p.suffix.lower())
