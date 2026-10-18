from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

DATABASE_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = DATABASE_DIRECTORY / "crestfall.db"
SCHEMA_PATH = DATABASE_DIRECTORY / "schema.sql"
PathLike = Union[str, Path]


def initialize_database(database_path: PathLike = DEFAULT_DATABASE_PATH) -> Path:
    """Create the database file and all required tables if they do not exist."""
    path = Path(database_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    return path


def connect_database(database_path: PathLike = DEFAULT_DATABASE_PATH) -> sqlite3.Connection:
    """Initialize and return a configured database connection."""
    path = initialize_database(database_path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON").close()
    connection.execute("PRAGMA busy_timeout = 5000").close()
    return connection


if __name__ == "__main__":
    print(f"Initialized database at {initialize_database()}")
