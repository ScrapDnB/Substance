"""Run each Qt test module in its own process to isolate native Qt lifetimes."""
from pathlib import Path
import os
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    failed = []
    for path in sorted((root / "tests").glob("test_*.py")):
        print(f"\nTesting {path.name}", flush=True)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", str(path)],
                cwd=root, env=environment, timeout=180,
            )
            if result.returncode:
                failed.append(path.name)
        except subprocess.TimeoutExpired:
            failed.append(path.name + " (timeout)")
    if failed:
        print("Failed modules: " + ", ".join(failed), flush=True)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
