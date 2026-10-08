# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Verify public package snapshots, populated upgrades and backup restores.

Run with Python 3.12. All environments, games and credentials are disposable.
Only the final evidence/ directory is suitable for sharing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import venv
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY = "https://github.com/an0n-b1nary/evennia-contribs-staging.git"
# Includes the spend ledger, but predates chargen's additive catalog migration.
OLD_REVISION = "1939b8aa80d8e90c408715d68ca18a379d1699b4"
ROOT = Path(__file__).resolve().parents[1]
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def run(command, *, cwd, log, timeout=1200, environment=None):
    """Keep subprocess output local and fail closed on nonzero status/timeouts."""
    with log.open("a", encoding="utf-8") as stream:
        result = subprocess.run(
            [str(part) for part in command],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                **(environment or {}),
            },
            **HIDDEN,
        )
    if result.returncode:
        raise RuntimeError(f"{command[0]} exited {result.returncode}; see {log.name}")


def requirements(snapshot, revision):
    """Put every hard sibling and selected web extra in one resolver invocation."""
    result = ["evennia==6.0.0", "psutil==7.1.0", "playwright==1.62.0"]
    packages = {}
    for path in sorted((snapshot / "contribs").glob("*/*/pyproject.toml")):
        metadata = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        name = metadata["name"]
        extra = "[web]" if "web" in metadata.get("optional-dependencies", {}) else ""
        relative = path.parent.relative_to(snapshot).as_posix()
        result.append(f"{name}{extra} @ git+{REPOSITORY}@{revision}#subdirectory={relative}")
        packages[name] = {"version": metadata["version"], "directory": relative}
    if not packages:
        raise ValueError("Snapshot contains no contribs")
    return "\n".join(result) + "\n", packages


def snapshot(repository, revision, destination):
    """Export an immutable public branch ancestor, excluding local working changes."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Use full lowercase 40-character Git revisions")
    refs = subprocess.check_output(
        ["git", "branch", "-r", "--contains", revision],
        cwd=repository,
        text=True,
        **HIDDEN,
    ).strip()
    if not refs:
        raise ValueError(f"Revision {revision} is not reachable from a public remote branch")
    destination.mkdir()
    archive = destination.parent / (destination.name + ".tar")
    with archive.open("wb") as stream:
        subprocess.run(
            ["git", "archive", revision],
            cwd=repository,
            stdout=stream,
            stdin=subprocess.DEVNULL,
            check=True,
            **HIDDEN,
        )
    with tarfile.open(archive) as stream:
        stream.extractall(destination, filter="data")
    archive.unlink()


def environment(directory, source, revision, log):
    """Create a genuinely fresh, isolated environment with non-editable VCS pins."""
    venv.EnvBuilder(with_pip=True).create(directory / "venv")
    python = directory / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    pins, packages = requirements(source, revision)
    (directory / "requirements.txt").write_text(pins, encoding="utf-8")
    (directory / "packages.json").write_text(json.dumps(packages, indent=2), encoding="utf-8")
    run(
        [python, "-m", "pip", "install", "-r", directory / "requirements.txt"],
        cwd=directory,
        log=log,
        environment={
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{(directory.parent / 'repository').as_uri()}.insteadOf",
            "GIT_CONFIG_VALUE_0": REPOSITORY,
        },
    )
    run([python, "-m", "pip", "check"], cwd=directory, log=log)
    return python


def migration_history(old, new):
    """Reject deletion or rewriting of any migration in the old public tree."""
    checked = 0
    for path in (old / "contribs").glob("*/*/migrations/*.py"):
        if path.name == "__init__.py":
            continue
        target = new / path.relative_to(old)
        if not target.is_file() or target.read_bytes() != path.read_bytes():
            raise ValueError(f"Published migration changed: {path.relative_to(old)}")
        checked += 1
    if not checked:
        raise ValueError("No migration history found")
    return checked


def environment_ready(directory, revision):
    python = directory / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        return False
    code = (
        "import importlib.metadata as m,json,sys; "
        "packages=json.load(open(sys.argv[2])); "
        "assert {d.metadata['Name'].lower() for d in m.distributions() if d.metadata['Name'].lower().startswith('evennia-')}==set(packages); "
        "assert all(m.version(n)==p['version'] and json.loads(m.distribution(n).read_text('direct_url.json'))['vcs_info']['commit_id']==sys.argv[1] for n,p in packages.items())"
    )
    return (
        subprocess.run(
            [str(python), "-c", code, revision, str(directory / "packages.json")],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            **HIDDEN,
        ).returncode
        == 0
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-revision", default=OLD_REVISION)
    parser.add_argument("--new-revision", required=True)
    parser.add_argument(
        "--resume", type=Path, help="Retry an interrupted run with the same revisions"
    )
    parser.add_argument("--output-root", type=Path, default=ROOT / ".downstream-runs")
    args = parser.parse_args(argv)
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12, matching the reference runtime")
    if args.old_revision == args.new_revision:
        parser.error("Old and new revisions must differ")
    for revision in (args.old_revision, args.new_revision):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            parser.error("Use full lowercase 40-character Git revisions")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4)
    directory = args.resume.resolve() if args.resume else args.output_root.resolve() / stamp
    if args.resume:
        previous = json.loads((directory / "evidence/result.json").read_text(encoding="utf-8"))
        if (previous["old_revision"], previous["new_revision"]) != (
            args.old_revision,
            args.new_revision,
        ):
            parser.error("Resume revisions must match the original run")
    else:
        directory.mkdir(parents=True)
    evidence = directory / "evidence"
    evidence.mkdir(exist_ok=True)
    result = {"old_revision": args.old_revision, "new_revision": args.new_revision, "passed": False}
    print(f"Downstream gate: {directory}", flush=True)
    started = time.monotonic()
    try:
        repository = directory / "repository"
        if not args.resume:
            run(
                ["git", "clone", "--no-checkout", REPOSITORY, repository],
                cwd=directory,
                log=directory / "clone.log",
            )
        for name, revision in (("old", args.old_revision), ("new", args.new_revision)):
            phase = directory / name
            if not args.resume:
                phase.mkdir()
                snapshot(repository, revision, phase / "snapshot")
        result["unchanged_migration_files"] = migration_history(
            directory / "old/snapshot", directory / "new/snapshot"
        )
        if args.resume:
            interpreters = {
                name: directory
                / name
                / "venv"
                / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                for name in ("old", "new")
            }
            for name, revision in (("old", args.old_revision), ("new", args.new_revision)):
                if not environment_ready(directory / name, revision):
                    interpreters[name] = environment(
                        directory / name,
                        directory / name / "snapshot",
                        revision,
                        directory / name / "install.log",
                    )
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = {
                    name: pool.submit(
                        environment,
                        directory / name,
                        directory / name / "snapshot",
                        revision,
                        directory / name / "install.log",
                    )
                    for name, revision in (("old", args.old_revision), ("new", args.new_revision))
                }
                interpreters = {name: future.result() for name, future in jobs.items()}
        print("Both public snapshots installed in fresh environments", flush=True)
        run(
            [interpreters["new"], "-m", "playwright", "install", "chromium"],
            cwd=directory,
            log=directory / "browser-install.log",
        )
        worker = ROOT / "scripts/downstream_runtime.py"
        for mode, name, revision in (
            ("fresh", "new", args.new_revision),
            ("populate", "old", args.old_revision),
            ("upgrade", "new", args.new_revision),
            ("restore", "old", args.old_revision),
        ):
            print(f"Running {mode} at {revision}", flush=True)
            recorded = directory / (mode + ".json")
            completed = (
                json.loads(recorded.read_text(encoding="utf-8")) if recorded.exists() else {}
            )
            if not (
                args.resume and completed.get("passed") and completed.get("revision") == revision
            ):
                run(
                    [interpreters[name], worker, mode, directory, revision],
                    cwd=directory,
                    log=directory / (mode + ".log"),
                    timeout=1800,
                )
            phase_result = json.loads((directory / (mode + ".json")).read_text(encoding="utf-8"))
            if not phase_result.get("passed"):
                raise RuntimeError(f"{mode} did not record a successful result")
            result[mode] = phase_result
            shutil.copytree(phase_result["evidence"], evidence / mode, dirs_exist_ok=True)
        result["passed"] = True
    except Exception as exc:
        result["error"] = str(exc)
        print(f"Downstream gate failed: {exc}", file=sys.stderr, flush=True)
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 1)
        result["package_git_transport"] = (
            "Public requirement URLs; verified public clone may supply Git objects through a per-process URL rewrite"
        )
        # Paths and credentials stay in the private run directory.
        public = json.loads(json.dumps(result))
        if "error" in public:
            public["error"] = "Verification failed; inspect the private run logs."
        for mode in ("fresh", "populate", "upgrade", "restore"):
            recorded = directory / (mode + ".json")
            if mode not in public and recorded.exists():
                public[mode] = json.loads(recorded.read_text(encoding="utf-8"))
            if mode in public and Path(public[mode]["evidence"]).is_dir():
                shutil.copytree(public[mode]["evidence"], evidence / mode, dirs_exist_ok=True)
            if mode in public:
                public[mode].pop("evidence", None)
        (evidence / "result.json").write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
        report = "# Downstream snapshot verification\n\n"
        report += f"Old: `{args.old_revision}`\n\nNew: `{args.new_revision}`\n\n"
        report += "Result: " + ("PASS" if result["passed"] else "FAIL") + "\n\n"
        report += "\n".join(
            f"- {mode}: PASS"
            for mode in ("fresh", "populate", "upgrade", "restore")
            if mode in result
        )
        if "error" in result:
            report += "\n\nFailure details remain in the local run logs.\n"
        (evidence / "results.md").write_text(report + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
