# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Allowlisted failure evidence; raw exceptions and subprocess output stay private."""

from __future__ import annotations

import ast
import json
import math
import re
import subprocess
import time

PHASES = {"setup", "fresh", "populate", "upgrade", "restore"}
STEPS = {
    "unknown",
    "clone",
    "snapshots",
    "migration-history",
    "fixtures",
    "environments",
    "install-old",
    "install-new",
    "browser-install",
    "worker",
    "provenance",
    "integration",
    "host-prepare",
    "database-preservation",
    "host-start",
    "workflows",
    "live-cases",
    "backup",
    "normal-cases",
    "web-and-models",
    "cross-links",
    "cleanup",
    "server-logs",
    "phase-result",
}
KINDS = {"timeout", "nonzero_exit", "assertion", "error"}


def known_test_ids(game):
    """Read names from public source without importing tests or evaluating values."""
    names = set()
    for path in game.rglob("*.py"):
        module = ".".join(path.relative_to(game).with_suffix("").parts)
        if module.endswith(".__init__"):
            module = module.removesuffix(".__init__")
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, OSError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(
                        method, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ) and method.name.startswith("test"):
                        names.add(f"{module}.{node.name}.{method.name}")
    return names


def test_summary(count):
    return f"Ran {count} test" + ("" if count == 1 else "s")


def test_diagnostics(text, known):
    """Rebuild summaries, dropping tracebacks, messages and subtest parameters."""
    result = {}
    counts = re.findall(r"^Ran ([0-9]{1,9}) tests?(?:\s|$)", text, re.M)
    if counts:
        result["test_count"] = int(counts[-1])
        result["test_summary"] = test_summary(int(counts[-1]))
    identifiers = re.findall(
        r"^(?:FAIL|ERROR): (test\w*) \(([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\)(?:\s|$)",
        text,
        re.M,
    )
    result["failing_test_ids"] = sorted(
        {
            identifier
            for method, identifier in identifiers
            if identifier in known and identifier.rsplit(".", 1)[-1] == method
        }
    )[:100]
    return result


def public_failure(value, known=()):
    """Project onto fixed tokens, finite numbers and source-verified test names."""
    if not isinstance(value, dict):
        value = {}

    def token(key, allowed, default):
        item = value.get(key)
        return item if isinstance(item, str) and item in allowed else default

    result = {
        "phase": token("phase", PHASES, "setup"),
        "step": token("step", STEPS, "unknown"),
        "kind": token("kind", KINDS, "error"),
    }
    for key in ("elapsed_seconds", "budget_seconds"):
        number = value.get(key)
        if type(number) in (int, float) and 0 <= number <= 10**9 and math.isfinite(number):
            result[key] = round(number, 1) if key == "elapsed_seconds" else number
    code = value.get("exit_code")
    if type(code) is int and -(2**31) <= code < 2**32:
        result["exit_code"] = code
    if value.get("timeout_scope") in ("phase", "step"):
        result["timeout_scope"] = value["timeout_scope"]
    count = value.get("test_count")
    if type(count) is int and 0 <= count < 10**9:
        result["test_count"] = count
        result["test_summary"] = test_summary(count)
    ids = value.get("failing_test_ids", [])
    if isinstance(ids, list):
        result["failing_test_ids"] = sorted(
            {item for item in ids if isinstance(item, str) and item in known}
        )[:100]
    return result


def failure(phase, step, exc, elapsed, *, diagnostics=None, budget=None):
    value = {"phase": phase, "step": step, "elapsed_seconds": elapsed, "kind": "error"}
    if isinstance(exc, subprocess.TimeoutExpired):
        value.update(
            kind="timeout",
            budget_seconds=exc.timeout if budget is None else budget,
            timeout_scope="step",
        )
    elif isinstance(exc, subprocess.CalledProcessError):
        value.update(kind="nonzero_exit", exit_code=exc.returncode)
    elif isinstance(exc, AssertionError):
        value["kind"] = "assertion"
    # Diagnostics are already projected from a private log against public source.
    result = public_failure(value)
    if diagnostics:
        result.update(diagnostics)
    return result


def describe(value):
    text = f"{value['phase']} / {value['step']}: {value['kind']}"
    if "budget_seconds" in value:
        text += f" (budget {value['budget_seconds']:g}s, elapsed {value['elapsed_seconds']:g}s"
        text += f", {value.get('timeout_scope', 'step')} timeout)"
    elif "exit_code" in value:
        text += f" (exit {value['exit_code']})"
    if "test_summary" in value:
        text += f"; {value['test_summary']}"
    if value.get("failing_test_ids"):
        text += "; failing tests: " + ", ".join(value["failing_test_ids"])
    return text


class GateFailure(RuntimeError):
    def __init__(self, summary):
        self.summary = summary
        super().__init__(describe(summary))


class Progress:
    """Atomically checkpoint a worker's current step outside its result file."""

    def __init__(self, directory, phase):
        self.path = directory / (phase + "-status.json")
        self.phase = phase
        self.start("worker")

    def start(self, step):
        if step not in STEPS:
            raise ValueError("Unknown gate step")
        self.step = step
        self.started = time.monotonic()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"step": step}), encoding="utf-8")
        temporary.replace(self.path)

    def failed(self, exc):
        return failure(self.phase, self.step, exc, time.monotonic() - self.started)


def recorded_step(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        step = value.get("step")
        return step if isinstance(step, str) and step in STEPS else "worker"
    except (OSError, ValueError, AttributeError, TypeError):
        return "worker"
