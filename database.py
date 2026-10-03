# database.py
# All the SQLite code lives in this one file.
# app.py calls these functions and never talks to the database directly.

import sqlite3
# datetime is part of Python's standard library (nothing to pip install).
# We use it to read the computer's clock when a timer starts or stops,
# and to know today's date for the daily report.
from datetime import date, datetime

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


def today_text():
    """Return today's date as text, e.g. "2026-10-03" (YYYY-MM-DD)."""
    # isoformat() gives exactly the YYYY-MM-DD format. Dates in this format
    # also sort correctly as plain text: "2026-09-30" < "2026-10-03".
    return date.today().isoformat()


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

    # The profile table. The app only ever uses one row (your profile).
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS profile (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL,
            role  TEXT
        )
        """
    )

    # One row per day's report.
    # - UNIQUE on report_date: the database refuses a second report for the
    #   same day.
    # - CHECK (...) is a rule the database tests on every insert/update, so
    #   status can only ever be 'draft' or 'synced'.
    # - DEFAULT 'draft': a new report starts as a draft automatically.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_reports (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date    TEXT NOT NULL UNIQUE,
            subject        TEXT NOT NULL DEFAULT '',
            tomorrow_plan  TEXT NOT NULL DEFAULT '',
            status         TEXT NOT NULL DEFAULT 'draft'
                           CHECK (status IN ('draft', 'synced'))
        )
        """
    )

    # Give every task a report_date so we know which day it belongs to.
    #
    # ALTER TABLE changes a table that already exists. "ADD COLUMN" adds a
    # new column to it; all existing rows get NULL (empty) in that column.
    # CREATE TABLE IF NOT EXISTS can't do this: if the tasks table is
    # already there, it does nothing at all, even if the columns differ.
    #
    # SQLite has no "ADD COLUMN IF NOT EXISTS", and adding a column twice
    # is an error. So we first ask SQLite which columns tasks has:
    # "PRAGMA table_info(tasks)" returns one row per column, and
    # row["name"] is the column's name.
    columns = connection.execute("PRAGMA table_info(tasks)").fetchall()
    column_names = [column["name"] for column in columns]
    if "report_date" not in column_names:
        connection.execute("ALTER TABLE tasks ADD COLUMN report_date TEXT")
        # The new column is empty for old tasks: put them on today's report.
        connection.execute(
            "UPDATE tasks SET report_date = ? WHERE report_date IS NULL",
            (today_text(),),
        )

    connection.commit()
    connection.close()


def get_tasks_for_date(report_date):
    """Return the tasks of one day (YYYY-MM-DD), newest first."""
    connection = get_connection()
    # id is the tie-breaker: tasks created in the same second
    # still come out newest first.
    tasks = connection.execute(
        "SELECT * FROM tasks WHERE report_date = ? ORDER BY created_at DESC, id DESC",
        (report_date,),
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
    """Insert a new task on today's report. The ? marks are filled in safely by sqlite3."""
    connection = get_connection()
    connection.execute(
        "INSERT INTO tasks (title, link, hours, report_date) VALUES (?, ?, ?, ?)",
        (title, link, hours, today_text()),
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


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def get_profile():
    """Return the profile row, or None if it hasn't been saved yet."""
    connection = get_connection()
    # LIMIT 1: we only ever use one row, so take the first one.
    profile = connection.execute(
        "SELECT * FROM profile ORDER BY id LIMIT 1"
    ).fetchone()
    connection.close()
    return profile


def save_profile(name, role):
    """Create the profile the first time (INSERT), change it after that (UPDATE)."""
    connection = get_connection()
    existing = connection.execute(
        "SELECT id FROM profile ORDER BY id LIMIT 1"
    ).fetchone()
    if existing is None:
        connection.execute(
            "INSERT INTO profile (name, role) VALUES (?, ?)", (name, role)
        )
    else:
        connection.execute(
            "UPDATE profile SET name = ?, role = ? WHERE id = ?",
            (name, role, existing["id"]),
        )
    connection.commit()
    connection.close()


# ---------------------------------------------------------------------------
# Daily reports
# ---------------------------------------------------------------------------


def get_report(report_date):
    """Return the report for one day (YYYY-MM-DD), or None if there is none yet."""
    connection = get_connection()
    report = connection.execute(
        "SELECT * FROM daily_reports WHERE report_date = ?", (report_date,)
    ).fetchone()
    connection.close()
    return report


def get_all_reports():
    """Return every saved report, newest day first (for the History page)."""
    connection = get_connection()
    reports = connection.execute(
        "SELECT * FROM daily_reports ORDER BY report_date DESC"
    ).fetchall()
    connection.close()
    return reports


def save_report(report_date, subject, tomorrow_plan, status):
    """
    Save the subject and tomorrow's plan of a day's report, and set its status.
    Only works while the report is a draft: a synced report is locked.
    Returns True if it was saved, False if the report was locked.
    """
    connection = get_connection()
    # INSERT OR IGNORE: create the day's report row if it doesn't exist yet.
    # If it already exists, the UNIQUE rule on report_date would fail, and
    # "OR IGNORE" tells SQLite to quietly skip the insert instead.
    # After this line the row is guaranteed to exist.
    connection.execute(
        "INSERT OR IGNORE INTO daily_reports (report_date) VALUES (?)",
        (report_date,),
    )
    # "AND status = 'draft'" means a synced report is never changed here.
    cursor = connection.execute(
        """
        UPDATE daily_reports
        SET subject = ?, tomorrow_plan = ?, status = ?
        WHERE report_date = ? AND status = 'draft'
        """,
        (subject, tomorrow_plan, status, report_date),
    )
    connection.commit()
    saved = cursor.rowcount > 0
    connection.close()
    return saved


def unlock_report(report_date):
    """Set a synced report back to draft so it can be edited again."""
    connection = get_connection()
    connection.execute(
        "UPDATE daily_reports SET status = 'draft' WHERE report_date = ?",
        (report_date,),
    )
    connection.commit()
    connection.close()
