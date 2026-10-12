"""Exclusive profile/database ownership; stale locks require explicit recovery."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def process_lock(data_dir: Path) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = data_dir / "app.lock"
    content = str(os.getpid())
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError(
            f"Another tracker or setup process may be running. After a crash, "
            f"confirm all such processes are stopped, then remove {path} and retry."
        ) from None
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
        yield
    finally:
        try:
            if path.read_text() == content:
                path.unlink()
        except FileNotFoundError:
            pass
