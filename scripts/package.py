"""Build a self-contained Skill ZIP using an explicit public-file allowlist."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
FILES = ("SKILL.md", "README.md", "MCP_INTEGRATION.md", "CONTEST_DECLARATION.md",
         "mcp-config.example.json", "pyproject.toml", ".gitignore", ".env.example", "LICENSE")
DIRECTORIES = ("mcd_plan_b", "scripts", "references", "tests", "docs", ".github")


def package():
    sources = [ROOT / name for name in FILES]
    for name in DIRECTORIES:
        sources.extend(path for path in (ROOT / name).rglob("*") if path.is_file()
                       and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"))
    target = ROOT / "dist" / "mcd-plan-b.zip"
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for source in sorted(sources):
            archive.write(source, Path("mcd-plan-b") / source.relative_to(ROOT))
    return target


if __name__ == "__main__":
    print(package())
