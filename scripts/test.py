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
        targets = [str(path)]
        if path.name.startswith("test_online"):
            # Async QObject trees can outlive a backend fixture. A separate
            # process for each online scenario matches the app's Qt lifetime.
            collection = subprocess.run(
                [sys.executable, "-m", "pytest", "--collect-only", "--color=no", "-q", str(path)],
                cwd=root, env=environment, timeout=60, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
            )
            targets = [line.strip() for line in collection.stdout.splitlines()
                       if line.startswith("tests/") and "::" in line]
            if collection.returncode or not targets:
                print(collection.stdout + collection.stderr, flush=True)
                failed.append(path.name + " (collection)")
                continue
        for target in targets:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", target],
                    cwd=root, env=environment, timeout=180,
                )
                if result.returncode:
                    failed.append(target)
            except subprocess.TimeoutExpired:
                failed.append(target + " (timeout)")
    if failed:
        print("Failed modules: " + ", ".join(failed), flush=True)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
