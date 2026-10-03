# database.py
# All the SQLite code lives in this one file.
# app.py calls these functions and never talks to the database directly.

import sqlite3

# The database is a single file that sits next to the code.
DATABASE_FILE = "reports.db"


def get_connection():
    """Open a connection to the database file and return it."""
    connection = sqlite3.connect(DATABASE_FILE)
    # row_factory lets us read columns by name (row["title"])
    # instead of by position (row[1]).
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    """Create the tasks table if it doesn't exist yet. Runs on startup."""
    connection = get_connection()
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            link        TEXT,
            hours       REAL NOT NULL,
            created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()
    connection.close()


def get_all_tasks():
    """Return every task, newest first."""
    connection = get_connection()
    # id is the tie-breaker: tasks created in the same second
    # still come out newest first.
    tasks = connection.execute(
        "SELECT * FROM tasks ORDER BY created_at DESC, id DESC"
    ).fetchall()
    connection.close()
    return tasks


def get_task(task_id):
    """Return one task by id, or None if it doesn't exist."""
    connection = get_connection()
    task = connection.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    connection.close()
    return task


def add_task(title, link, hours):
    """Insert a new task. The ? marks are filled in safely by sqlite3."""
    connection = get_connection()
    connection.execute(
        "INSERT INTO tasks (title, link, hours) VALUES (?, ?, ?)",
        (title, link, hours),
    )
    connection.commit()
    connection.close()


def update_task(task_id, title, link, hours):
    """Change the title, link and hours of an existing task."""
    connection = get_connection()
    connection.execute(
        "UPDATE tasks SET title = ?, link = ?, hours = ? WHERE id = ?",
        (title, link, hours, task_id),
    )
    connection.commit()
    connection.close()


def delete_task(task_id):
    """Remove a task by id."""
    connection = get_connection()
    connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    connection.commit()
    connection.close()
