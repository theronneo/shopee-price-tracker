"""Run the project's checks with the current virtual environment."""

import subprocess
import sys

commands = [
    [sys.executable, "-m", "ruff", "check", "."],
    [sys.executable, "-m", "ruff", "format", "--check", "."],
    [sys.executable, "-m", "mypy"],
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
]
for command in commands:
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)
