"""Run `evennia test` against every installed contrib app label.

Invoked by `.github/workflows/ci.yml` from inside the throwaway game directory.
Discovers contribs the same way ci_install_contribs.py does, then hands their
app labels to `evennia test`. Exits 0 trivially if no contribs exist yet, so
CI on a freshly-scaffolded repo isn't perpetually red.
"""

import pathlib
import subprocess
import sys

CONTRIBS_ROOT = pathlib.Path("../contribs")


def main() -> int:
    """Discover contrib app labels and invoke `evennia test`.

    Returns:
        int: Process exit code (0 on success, propagated from `evennia test`).
    """
    labels = [c.name for c in sorted(CONTRIBS_ROOT.glob("*/*/")) if (c / "pyproject.toml").exists()]
    if not labels:
        print("No contribs to test yet — passing trivially.")
        return 0

    print(f"Running tests for: {', '.join(labels)}")
    result = subprocess.run(
        ["evennia", "test", "--settings=server.conf.settings", *labels],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
