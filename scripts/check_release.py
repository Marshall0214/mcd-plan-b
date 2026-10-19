"""Validate required contest files and the public ZIP without accessing credentials."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DECLARATION_HASH = "cd28101bcb29cc8fb24b372fe91ce6b42c4a1487a54e01f7ade0c8c6a84241b7"
REQUIRED = {"README.md", "CONTEST_DECLARATION.md", "MCP_INTEGRATION.md",
            "mcp-config.example.json", "SKILL.md", "pyproject.toml", "LICENSE"}
SECRET_PATTERNS = [re.compile(rb"Bearer\s+[A-Za-z0-9_-]{16,}"),
                   re.compile(rb"MCD_MCP_TOKEN\s*=\s*[\"']?[A-Za-z0-9_-]{16,}")]


def validate(entries):
    missing = REQUIRED - entries.keys()
    if missing:
        raise ValueError("Required files missing: " + ", ".join(sorted(missing)))
    normalized = entries["CONTEST_DECLARATION.md"].replace(b"\r\n", b"\n")
    if sha256(normalized).hexdigest() != DECLARATION_HASH:
        raise ValueError("The official contest declaration has changed.")
    config = json.loads(entries["mcp-config.example.json"])
    server = config["mcpServers"]["mcd-mcp"]
    if server["url"] != "https://mcp.mcd.cn" or server["headers"] != {"Authorization": "Bearer ${MCD_MCP_TOKEN}"}:
        raise ValueError("The MCP example must use only the documented environment placeholder.")
    for name, data in entries.items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe archive path: " + name)
        if set(path.parts) & {"private", ".git", "__pycache__", ".venv"} or path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            raise ValueError("Private file included: " + name)
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise ValueError("Possible credential in public file: " + name)


def main():
    with ZipFile(ROOT / "dist" / "mcd-plan-b.zip") as archive:
        entries = {}
        for name in archive.namelist():
            parts = PurePosixPath(name).parts
            if not parts or parts[0] != "mcd-plan-b":
                raise ValueError("Unexpected ZIP root: " + name)
            entries[str(PurePosixPath(*parts[1:]))] = archive.read(name)
        validate(entries)
        print(f"Release archive: {len(entries)} public files, contest declaration unchanged, no credential patterns found.")
    # Check only this project's own Git index, never the surrounding activity repository.
    if (ROOT / ".git").is_dir():
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
        sources = {name: (ROOT / name).read_bytes() for name in tracked if name}
        validate(sources)
        print(f"Git index: {len(sources)} public files checked.")


if __name__ == "__main__":
    main()
