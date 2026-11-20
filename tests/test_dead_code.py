"""Bug 6c: dead code and unused imports.

Code that never runs misleads whoever reads it: modules nobody imports
(models/alarm.py, manual.py, plan.py, seasonal.py, descriptions.py, a
datetime platform that is never set up, empty services.py and
diagnostics.py), imports nobody uses, unique ids built from the
Zigbee2MQTT name although the base entity always uses the IEEE address,
and branches that can never be taken.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

from custom_components.sonoff_swv import PLATFORMS

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "custom_components" / "sonoff_swv"

# Loaded by Home Assistant by name, not imported by the integration.
HA_ENTRY_POINTS = {"__init__", "config_flow", *PLATFORMS}


def modules() -> dict[str, Path]:
    found = {}
    for path in PACKAGE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        name = ".".join(path.relative_to(PACKAGE).with_suffix("").parts)
        found[name.removesuffix(".__init__") if name != "__init__" else name] = path
    return found


def relative_imports(name: str, path: Path) -> set[str]:
    """Modules of the package imported by one module."""
    package = name.split(".")[:-1] if path.name != "__init__.py" else name.split(".")
    if name == "__init__":
        package = []
    imported = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level:
            base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
            target = ".".join([*base, *(node.module.split(".") if node.module else [])])
            if target:
                imported.add(target)
            for alias in node.names:
                imported.add(".".join(filter(None, [target, alias.name])))
    return imported


def test_every_module_is_used():
    found = modules()
    reachable = set()
    todo = [m for m in HA_ENTRY_POINTS if m in found]
    while todo:
        name = todo.pop()
        if name in reachable:
            continue
        reachable.add(name)
        for target in relative_imports(name, found[name]):
            for candidate in (target, target.rsplit(".", 1)[0]):
                if candidate in found and candidate not in reachable:
                    todo.append(candidate)

    unused = sorted(set(found) - reachable)
    assert unused == [], f"modules never imported nor loaded: {unused}"


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")
def test_no_unused_imports():
    result = subprocess.run(
        ["ruff", "check", "--no-cache", "--select", "F401", "--output-format", "concise", str(PACKAGE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout


def test_no_unique_id_overridden_by_the_base_entity():
    """SonoffSWVEntity.unique_id (IEEE based) ignores _attr_unique_id."""
    offenders = [
        f"{path.name}:{number}"
        for path in PACKAGE.glob("*.py")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "self._attr_unique_id" in line
    ]
    assert offenders == [], f"unique ids that are never used: {offenders}"


def test_no_branch_that_can_never_run():
    """`x = {}` immediately followed by `if x:`."""
    dead = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list):
                continue
            for first, second in zip(body, body[1:]):
                if (
                    isinstance(first, ast.Assign)
                    and isinstance(first.value, ast.Dict)
                    and not first.value.keys
                    and len(first.targets) == 1
                    and isinstance(first.targets[0], ast.Name)
                    and isinstance(second, ast.If)
                    and isinstance(second.test, ast.Name)
                    and second.test.id == first.targets[0].id
                ):
                    dead.append(f"{path.name}:{second.lineno}")
    assert dead == [], f"branches that never run: {dead}"
