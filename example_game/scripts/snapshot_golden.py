"""Build the public golden database from a fresh, isolated sandbox copy.

Run with the sandbox venv's Python from any directory. No live database or
secret settings are copied. Credentials stay in gitignored ci_game/.
"""

import argparse
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
ROOT = GAME.parent


def audit(snapshot):
    """Fail closed before publishing a snapshot, including its binary contents."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from _anonymity_patterns import load_patterns

    patterns = load_patterns()  # Missing local policy is an error.
    text = snapshot.read_bytes().decode("utf-8", errors="ignore")
    if any(pattern.search(text) for pattern in patterns):
        raise ValueError("Snapshot failed the anonymity guard")
    with sqlite3.connect(snapshot) as database:
        if database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Snapshot failed SQLite integrity checking")
        if database.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Snapshot contains broken foreign keys")
        accounts = database.execute(
            "SELECT username, email, password FROM accounts_accountdb"
        ).fetchall()
        if len(accounts) != 1 or accounts[0][:2] != ("admin", ""):
            raise ValueError(
                "Snapshot must contain only the purpose-made admin with an empty email"
            )
        if not accounts[0][2].startswith("pbkdf2_sha256$"):
            raise ValueError("Snapshot must use the production PBKDF2 hasher")


def build(scratch):
    """Worker: initialize Evennia without starting a portal/server."""
    os.chdir(scratch)
    sys.path.insert(0, str(scratch))
    os.environ["DJANGO_SETTINGS_MODULE"] = "server.conf.settings"
    import django

    django.setup()
    import evennia

    evennia._init()
    from django.core.management import call_command
    from django.db import connections
    from evennia.accounts.models import AccountDB
    from evennia.server import initial_setup
    from evennia.server.models import ServerConfig

    credentials = json.loads((scratch / "credentials.json").read_text(encoding="utf-8"))
    call_command("migrate", interactive=False, verbosity=0)
    AccountDB.objects.create_superuser(**credentials)
    initial_setup.create_objects()
    initial_setup.at_initial_setup()
    ServerConfig.objects.conf("last_initial_setup_step", "done")
    call_command("seed_sandbox", verbosity=0)
    connections.close_all()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        build(args.worker.resolve())
        return
    # This is intentionally a new directory every time, never an existing game.
    scratch = ROOT / "ci_game" / f"golden-{uuid.uuid4().hex}"
    shutil.copytree(
        GAME,
        scratch,
        ignore=shutil.ignore_patterns(
            "*.db3*",
            "secret_settings.py",
            "__pycache__",
            "*.pyc",
            "*.log*",
            "*.pid",
            "*.restart",
            ".static",
            ".media",
        ),
    )
    (scratch / "credentials.json").write_text(
        json.dumps({"username": "admin", "email": "", "password": secrets.token_urlsafe(48)}),
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", str(scratch)],
        stdin=subprocess.DEVNULL,
        check=True,
    )
    snapshot = scratch / "golden.db3"
    with (
        sqlite3.connect(scratch / "server/evennia.db3") as source,
        sqlite3.connect(snapshot) as target,
    ):
        source.backup(target)
        target.execute("VACUUM")
    audit(snapshot)
    destination = GAME / "server/evennia_default.db3"
    temporary = destination.with_suffix(".db3.tmp")
    shutil.copyfile(snapshot, temporary)
    temporary.replace(destination)
    print(f"Golden database: {destination}")
    print(f"Generated credentials (ignored): {scratch / 'credentials.json'}")


if __name__ == "__main__":
    main()
