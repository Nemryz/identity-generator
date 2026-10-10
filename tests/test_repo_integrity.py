"""
Repository integrity guards: these tests do not cover a feature but the shape of the repository itself, so a change that breaks a file nobody imports, a dependency nobody declared, or a README claim that stopped being true fails here with a message naming the offender.

I wrote the first of these after a docstring edit broke the indentation inside tools/build_datasets.py, which the whole suite missed because nothing imports that script.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = [
    "applog.py",
    "email_api.py",
    "exporter.py",
    "generator.py",
    "history.py",
    "main.py",
    "schema.py",
    "tools/build_datasets.py",
]

# I map the import name to the distribution that ships it, since a couple of
# them differ (none today, but the guard should survive that day).
IMPORT_TO_DISTRIBUTION = {
    "colorama": "colorama",
    "faker": "faker",
    "hypothesis": "hypothesis",
    "jsonschema": "jsonschema",
    "pyperclip": "pyperclip",
    "pytest": "pytest",
    "requests": "requests",
}


def _all_python_files() -> list[Path]:
    """I gather every Python file the repository ships, skipping caches."""
    return [
        path
        for path in REPO_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts and ".git" not in path.parts
    ]


# The modules this repository ships, which are first-party imports and
# therefore never belong in a requirements file.
LOCAL_MODULES = {
    "applog",
    "email_api",
    "exporter",
    "generator",
    "history",
    "main",
    "schema",
}


def _top_level_imports(path: Path) -> set[str]:
    """I return the third-party modules a file imports, leaving the standard library and our own modules out."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return {
        name
        for name in found
        if name not in sys.stdlib_module_names and name not in LOCAL_MODULES
    }


def _declared(file_name: str) -> set[str]:
    """I read the distribution names declared in a requirements file."""
    lines = (REPO_ROOT / file_name).read_text(encoding="utf-8").splitlines()
    return {
        line.split("==")[0].split(">=")[0].split("<")[0].strip().lower()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    }


@pytest.mark.parametrize(
    "path", _all_python_files(), ids=lambda p: p.name
)
def test_every_python_file_compiles(path):
    """I compile every file the repository ships, including the ones no test imports, so a syntax error cannot hide in tools/."""
    ast.parse(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", SOURCE_FILES)
def test_source_modules_compile(name):
    """I name the modules explicitly too, so the failure says which module broke instead of only which file."""
    ast.parse((REPO_ROOT / name).read_text(encoding="utf-8"))


def test_runtime_dependencies_are_declared():
    """I check every third-party import of the source modules appears in requirements.txt, so a fresh clone cannot miss one."""
    imported = set()
    for name in SOURCE_FILES:
        imported |= _top_level_imports(REPO_ROOT / name)
    declared = _declared("requirements.txt")
    for module in sorted(imported):
        distribution = IMPORT_TO_DISTRIBUTION.get(module, module)
        assert distribution in declared, f"{module} is imported but not in requirements.txt"


def test_test_dependencies_are_declared():
    """I check every third-party import used only by the tests appears in requirements-dev.txt, so a contributor who installs it can actually run the suite."""
    source_imports = set()
    for name in SOURCE_FILES:
        source_imports |= _top_level_imports(REPO_ROOT / name)
    test_imports = set()
    for path in (REPO_ROOT / "tests").glob("*.py"):
        test_imports |= _top_level_imports(path)
    dev = _declared("requirements-dev.txt")
    for module in sorted(test_imports - source_imports):
        distribution = IMPORT_TO_DISTRIBUTION.get(module, module)
        assert distribution in dev, f"{module} is used in tests but not in requirements-dev.txt"


def test_runtime_dependencies_are_all_used():
    """I catch the stale entry too, so requirements.txt never lists something the code stopped importing."""
    imported = set()
    for name in SOURCE_FILES:
        imported |= _top_level_imports(REPO_ROOT / name)
    distributions = {IMPORT_TO_DISTRIBUTION.get(m, m) for m in imported}
    for declared in _declared("requirements.txt"):
        assert declared in distributions, f"{declared} is in requirements.txt but never imported"


def test_every_test_module_is_listed_in_the_readme():
    """I keep the README testing table honest, since a module missing from it is a module nobody knows exists."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for path in (REPO_ROOT / "tests").glob("test_*.py"):
        assert path.name in readme, f"{path.name} is not listed in the README testing section"


def test_every_source_module_is_documented_in_the_readme():
    """I check the Source files section of the README describes every module that ships, which is the section a new contributor reads first."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for name in SOURCE_FILES:
        assert name in readme, f"{name} is not described in the README"


def test_readme_has_no_bold_and_no_semicolons():
    """I enforce the two house rules of this README, plain text and no semicolons, so a future edit cannot reintroduce them."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "**" not in readme, "the README must not use bold"
    assert ";" not in readme, "the README must not use semicolons"


def test_readme_paragraphs_are_not_wrapped():
    """I enforce one paragraph per line in the README, matching the convention the whole file already follows."""
    lines = (REPO_ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    offenders = []
    for index in range(1, len(lines)):
        line, previous = lines[index], lines[index - 1]
        if not line or not previous:
            continue
        if line.startswith("#") or line.startswith("    "):
            continue
        if previous.startswith("#") or previous.startswith("    "):
            continue
        if re.match(r"^[a-z(]", line) and not re.match(r"^\s*[-*]\s", line):
            offenders.append((index + 1, line[:60]))
    assert not offenders, f"wrapped prose at lines {offenders}"