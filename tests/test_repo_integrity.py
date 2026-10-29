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
PACKAGE_ROOT = REPO_ROOT / "identity_generator"
SOURCE_FILES = [
    "identity_generator/__init__.py",
    "identity_generator/applog.py",
    "identity_generator/email_api.py",
    "identity_generator/exporter.py",
    "identity_generator/generator.py",
    "identity_generator/history.py",
    "identity_generator/main.py",
    "identity_generator/paths.py",
    "identity_generator/schema.py",
    "main.py",
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
    "tomli": "tomli",
}

# Modules that ship with the standard library but only from a version newer
# than the minimum we support. sys.stdlib_module_names lists them on the
# interpreters that have them, so on 3.10 they would look like a missing
# third-party dependency when they are really a version difference.
NEWER_THAN_MINIMUM_STDLIB = {"tomllib": "3.11"}

# The modules this repository ships, which are first-party imports and
# therefore never belong in a requirements file.
LOCAL_MODULES = {
    "applog",
    "email_api",
    "exporter",
    "generator",
    "history",
    "identity_generator",
    "main",
    "paths",
    "schema",
}


def _all_python_files() -> list[Path]:
    """I gather every Python file the repository ships, skipping caches."""
    return [
        path
        for path in REPO_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts and ".git" not in path.parts
    ]


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
        if name not in sys.stdlib_module_names
        and name not in LOCAL_MODULES
        and name not in NEWER_THAN_MINIMUM_STDLIB
    }


def _declared(file_name: str) -> set[str]:
    """I read the distribution names declared in a requirements file, ignoring comments, version specifiers and environment markers."""
    lines = (REPO_ROOT / file_name).read_text(encoding="utf-8").splitlines()
    return {
        _requirement_name(line)
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

# --- packaging metadata: the guards that keep pyproject honest (A7b) -----------------


def _pyproject() -> dict:
    """I read pyproject.toml with tomllib, falling back to tomli on Python 3.10 where tomllib is not in the standard library yet."""
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _requirement_name(requirement: str) -> str:
    """I reduce a requirement line to the distribution name, dropping any version specifier and extras."""
    name = requirement.split(";")[0].strip()
    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
        name = name.split(separator)[0]
    return name.strip().lower().replace("_", "-")


def test_version_matches_the_package():
    """I check __version__ in the package matches pyproject.toml, because two sources of truth means publishing the wrong number at some point."""
    from identity_generator import __version__

    assert __version__ == _pyproject()["project"]["version"]


def test_pyproject_ships_the_entry_point_the_package_exposes():
    """I check the console script points at a function that actually exists, since a renamed entry point would break the install silently."""
    import importlib

    entry = _pyproject()["project"]["scripts"]["identity-generator"]
    module_name, _, attribute = entry.partition(":")
    module = importlib.import_module(module_name)
    assert callable(getattr(module, attribute))


def test_pyproject_ships_the_address_datasets():
    """I check the wheel configuration includes the package directory, because a pip install without data/addresses would fall back to Faker silently and nobody would know why the addresses changed."""
    wheel = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["identity_generator"]
    assert (PACKAGE_ROOT / "data" / "addresses").is_dir()
    assert list((PACKAGE_ROOT / "data" / "addresses").glob("*.json"))


def test_requirements_txt_matches_the_pyproject_dependencies():
    """I check requirements.txt and pyproject declare the same runtime dependencies, since contributors install from one and users from the other."""
    declared = _declared("requirements.txt")
    from_pyproject = {
        _requirement_name(item) for item in _pyproject()["project"]["dependencies"]
    }
    assert declared == from_pyproject


def test_requirements_dev_matches_the_pyproject_dev_extra():
    """I check requirements-dev.txt and the dev extra agree, which is what lets the README offer either way of installing the tooling."""
    declared = _declared("requirements-dev.txt")
    extra = _pyproject()["project"]["optional-dependencies"]["dev"]
    assert declared == {_requirement_name(item) for item in extra}


def test_pyproject_requires_the_python_the_ci_tests():
    """I check the declared minimum matches the oldest interpreter the CI matrix runs, so the claim on PyPI is one we actually test."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "3.10" in workflow
    assert _pyproject()["project"]["requires-python"] == ">=3.10"


def test_the_package_documents_itself_on_the_readme():
    """I check the README tells a reader both ways to run the tool, the launcher and the installed command, so the package layout is never a surprise."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "python -X utf8 main.py" in readme
    for document in ("CHANGELOG.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md"):
        assert document in readme, f"{document} exists but the README never mentions it"


# --- publication: the guards that keep the release path honest (B2) -------------------


def test_publish_workflow_ships_trusted_publishing_only():
    """I check the publish workflow needs no stored token, runs from the pypi environment on main and dies on an existing version, because a workflow file readable by every fork holding a PyPI password is the one leak this project cannot patch after the fact."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in workflow
    assert "environment: pypi" in workflow
    assert "refs/heads/main" in workflow
    assert "pypa/gh-action-pypi-publish" in workflow
    assert "TWINE_TOKEN" not in workflow
    assert "password" not in workflow


def test_the_release_instructions_name_the_workflow_that_exists():
    """I check CONTRIBUTING tells the maintainer to run the workflow file that actually is in the repository, so the release document and the `.github` tree cannot drift apart."""
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert (REPO_ROOT / ".github" / "workflows" / "publish.yml").is_file()
    assert "gh workflow run publish.yml" in contributing
