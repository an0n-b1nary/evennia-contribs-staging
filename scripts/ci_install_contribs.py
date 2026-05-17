"""Iterate contribs, pip-install each, append app labels to INSTALLED_APPS.

Invoked by `.github/workflows/ci.yml` from the repo root with one argument:
the path to the throwaway Evennia game directory created by `evennia --init`.
"""

import pathlib
import subprocess
import sys

CONTRIBS_ROOT = pathlib.Path("contribs")


def main(game_dir: pathlib.Path) -> int:
    """Install each contrib and append its app label to the game's settings.

    Args:
        game_dir: Path to the Evennia game directory created by `evennia --init`.

    Returns:
        int: Process exit code (0 on success).
    """
    settings_path = game_dir / "server" / "conf" / "settings.py"
    if not settings_path.exists():
        print(f"settings.py not found at {settings_path}", file=sys.stderr)
        return 1

    labels: list[str] = []
    for contrib in sorted(CONTRIBS_ROOT.glob("*/*/")):
        if not (contrib / "pyproject.toml").exists():
            continue
        print(f"Installing {contrib}")
        subprocess.run(["pip", "install", "-e", str(contrib)], check=True)
        labels.append(contrib.name)

    if not labels:
        print("No contribs to install yet.")
        return 0

    with settings_path.open("a", encoding="utf-8") as f:
        f.write("\n# Auto-added by scripts/ci_install_contribs.py\n")
        f.write("INSTALLED_APPS += [\n")
        for label in labels:
            f.write(f'    "{label}",\n')
        f.write("]\n")
    print(f"Registered {len(labels)} contrib app(s) in {settings_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ci_install_contribs.py <game-dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(pathlib.Path(sys.argv[1])))
