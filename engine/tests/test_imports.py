"""The import rule, mechanically enforced."""

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
PACKAGE = ENGINE / "tube_engine"

# Named so a failure says what kind of mistake was made rather than just reporting an
# unexpected module. Not the definition of the rule - the rule is "standard library
# only", which is strictly stronger and is what the tests actually assert. This list
# only improves the error message.
FORBIDDEN = {
    "alembic": "database",
    "asyncpg": "database",
    "fastapi": "web",
    "geoalchemy2": "database",
    "httpx": "web",
    "psycopg": "database",
    "pydantic": "web",
    "redis": "database",
    "sqlalchemy": "database",
    "starlette": "web",
    "uvicorn": "web",
}

# Standard library, and forbidden anyway. The allowlist below permits anything in the
# standard library, which is stronger than the list above for every third-party package
# and weaker for exactly these: they are how filesystem, environment and network access
# get into a package that claims to do none of it.
FORBIDDEN_STDLIB = {
    "os": "environment and filesystem",
    "pathlib": "filesystem",
    "shutil": "filesystem",
    "socket": "network",
    "subprocess": "process control",
    "urllib": "network",
}


# Top-level names only - `os.path` and `import os` both give `os`, which is the
# granularity the rule is written at. Uses ast.walk rather than reading module-level
# statements, so an import hidden inside a function is found too.
def imported_modules(path: Path) -> set[str]:
    """Every top-level module name a file imports, relative imports excluded."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        # node.level > 0 is `from .network import Network`, the package importing
        # itself, which is always allowed. node.module is None only for `from . import
        # x`, which is the same case.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])

    return modules


def offences(
    directory: Path, allowed: set[str], *, ban_io: bool = False
) -> dict[str, set[str]]:
    """Every import under a directory that breaks the rule, by file name."""
    found: dict[str, set[str]] = {}

    for path in sorted(directory.glob("*.py")):
        outside = {
            module
            for module in imported_modules(path)
            if module not in allowed
            and (
                module not in sys.stdlib_module_names
                or (ban_io and module in FORBIDDEN_STDLIB)
            )
        }
        if outside:
            found[path.name] = outside

    return found


# Asserting that sqlalchemy is absent would pass a file importing django. The engine has
# no dependencies at all, so the standard library is the entire permitted surface and
# anything else is a finding, including a package nobody has thought to forbid yet.
def test_the_engine_imports_only_the_standard_library() -> None:
    """An allowlist, not a blocklist, with a short blocklist inside it."""
    found = offences(PACKAGE, allowed={"tube_engine"}, ban_io=True)

    offences_found = []
    for name, modules in found.items():
        for module in sorted(modules):
            offences_found.append(f"{name} imports {module}" + _why(module))

    assert found == {}, "\n".join(offences_found)


def _why(module: str) -> str:
    """The reason an import is refused, for the failure message."""
    if module in FORBIDDEN:
        return f": {FORBIDDEN[module]}, which engine/ must not know about"
    if module in FORBIDDEN_STDLIB:
        return f": {FORBIDDEN_STDLIB[module]}, and engine/ does no I/O"
    return ""


def test_the_tests_are_as_constrained_as_the_code() -> None:
    """The tests are as constrained as the code."""
    # A suite that reached for a database would break the standalone property just as
    # completely as the package doing it, and would be easier to justify at the time.
    # pytest is the one exception, and only because the runner has to exist for any of
    # this to run at all.
    found = offences(ENGINE / "tests", allowed={"tube_engine", "fixtures", "pytest"})

    assert found == {}


def test_the_engine_declares_no_dependencies() -> None:
    """The engine declares no dependencies."""
    # The scan above catches an import. This catches the step before it: a dependency
    # added to pyproject.toml and not yet used. `pip install tube-engine` pulling in
    # half a web stack would contradict the claim the package makes about itself even if
    # no module imported any of it.
    manifest = tomllib.loads((ENGINE / "pyproject.toml").read_text(encoding="utf-8"))

    assert manifest["project"]["dependencies"] == []


# The scans read source. This runs it: a transitive import - engine module imports a
# helper that imports something heavy - would satisfy a per-file scan and still mean
# `import tube_engine` pulls a database driver into memory.
def test_importing_the_engine_drags_in_nothing_third_party() -> None:
    """The runtime counterpart to the static scan."""
    probe = (
        "import sys;"
        "before = set(sys.modules);"
        "import tube_engine;"
        "print('\\n'.join(sorted(n for n in set(sys.modules) - before "
        "if '.' not in n and n not in sys.stdlib_module_names)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=ENGINE,
    )

    assert result.stdout.split() == ["tube_engine"]
