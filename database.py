# database.py
# All the SQLite code lives in this one file.
# app.py calls these functions and never talks to the database directly.

import sqlite3
# datetime is part of Python's standard library (nothing to pip install).
# We use it to read the computer's clock when a timer starts or stops.
from datetime import datetime

# The database is a single file that sits next to the code.
DATABASE_FILE = "reports.db"


def get_connection():
    """Open a connection to the database file and return it."""
    connection = sqlite3.connect(DATABASE_FILE)
    # row_factory lets us read columns by name (row["title"])
    # instead of by position (row[1]).
    connection.row_factory = sqlite3.Row
    return connection


def now_text():
    """
    Return the current local time as text, e.g. "2026-10-03 14:05:09".
    SQLite has no real date type, so we store times as text in this
    fixed format. SQLite's date functions understand it.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    """Create the tables if they don't exist yet. Runs on startup."""
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
    # One row per timer session. A task can have many sessions
    # (start, stop, start again later...).
    # - task_id "REFERENCES tasks(id)" documents that each session belongs
    #   to a task (this link is called a "foreign key").
    # - end_time stays NULL (empty) while the timer is still running.
    # Because of "IF NOT EXISTS", an existing reports.db just gets the
    # new table added and keeps all its tasks.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS time_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     INTEGER NOT NULL REFERENCES tasks(id),
            start_time  TEXT NOT NULL,
            end_time    TEXT
        )
        """
    )
    # A "partial unique index": among rows WHERE end_time IS NULL (running
    # sessions), each task_id may appear only once. So even if two Start
    # clicks arrive at the same moment, the database refuses the second one.
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS one_running_session_per_task
        ON time_sessions (task_id) WHERE end_time IS NULL
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
    """Remove a task by id, together with all of its time sessions."""
    connection = get_connection()
    # Delete the sessions first, then the task. Both deletes are saved by
    # the same commit(), so we never end up with only half of the work done.
    connection.execute("DELETE FROM time_sessions WHERE task_id = ?", (task_id,))
    connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    connection.commit()
    connection.close()


# ---------------------------------------------------------------------------
# Time tracker
# ---------------------------------------------------------------------------


def start_timer(task_id):
    """
    Start a new session for a task.
    Returns True if it started, False if a session was already running.
    """
    connection = get_connection()
    running = connection.execute(
        "SELECT id FROM time_sessions WHERE task_id = ? AND end_time IS NULL",
        (task_id,),
    ).fetchone()
    if running is not None:
        connection.close()
        return False

    # try/except: if the INSERT breaks the "one running session" index
    # (a double click that slipped past the check above), sqlite3 raises
    # IntegrityError. We catch it and treat it as "already running".
    try:
        connection.execute(
            "INSERT INTO time_sessions (task_id, start_time) VALUES (?, ?)",
            (task_id, now_text()),
        )
        connection.commit()
        started = True
    except sqlite3.IntegrityError:
        started = False
    connection.close()
    return started


def stop_timer(task_id):
    """
    Stop the running session of a task by filling in its end_time.
    Returns True if a session was stopped, False if none was running.
    """
    connection = get_connection()
    # cursor.rowcount tells us how many rows the UPDATE changed (0 or 1 here).
    cursor = connection.execute(
        "UPDATE time_sessions SET end_time = ? WHERE task_id = ? AND end_time IS NULL",
        (now_text(), task_id),
    )
    connection.commit()
    stopped = cursor.rowcount > 0
    connection.close()
    return stopped


def get_tracked_seconds():
    """
    Return a dictionary {task_id: total_seconds} with the time of all
    FINISHED sessions of each task. Tasks with no finished sessions are
    simply missing from the dictionary.
    """
    connection = get_connection()
    # strftime('%s', some_time) turns a time into "seconds since 1970".
    # end - start = length of one session in seconds.
    # SUM(...) adds them up, and GROUP BY gives one total per task.
    rows = connection.execute(
        """
        SELECT task_id,
               SUM(CAST(strftime('%s', end_time) AS INTEGER)
                 - CAST(strftime('%s', start_time) AS INTEGER)) AS seconds
        FROM time_sessions
        WHERE end_time IS NOT NULL
        GROUP BY task_id
        """
    ).fetchall()
    connection.close()
    # A "dictionary comprehension": builds a dict from the rows in one line.
    return {row["task_id"]: row["seconds"] for row in rows}


def get_running_timers():
    """Return a dictionary {task_id: start_time} for every running session."""
    connection = get_connection()
    rows = connection.execute(
        "SELECT task_id, start_time FROM time_sessions WHERE end_time IS NULL"
    ).fetchall()
    connection.close()
    return {row["task_id"]: row["start_time"] for row in rows}
