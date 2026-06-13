from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from .import_engine import MEMBERSHIPS, ImportResult, balances_for, money, settlement_plan


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "expenses.db"))


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS group_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    member_id INTEGER NOT NULL REFERENCES members(id),
    joined_on TEXT NOT NULL,
    left_on TEXT,
    UNIQUE(group_id, member_id, joined_on)
);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    imported_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    import_run_id INTEGER REFERENCES import_runs(id),
    source_row INTEGER,
    expense_date TEXT NOT NULL,
    description TEXT NOT NULL,
    paid_by TEXT NOT NULL,
    amount_original TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount_inr TEXT NOT NULL,
    split_type TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'included'
);

CREATE TABLE IF NOT EXISTS expense_splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    member_name TEXT NOT NULL,
    amount_inr TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    import_run_id INTEGER REFERENCES import_runs(id),
    source_row INTEGER,
    payment_date TEXT NOT NULL,
    payer TEXT NOT NULL,
    recipient TEXT NOT NULL,
    amount_inr TEXT NOT NULL,
    description TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS import_anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_run_id INTEGER NOT NULL REFERENCES import_runs(id) ON DELETE CASCADE,
    source_row INTEGER NOT NULL,
    code TEXT NOT NULL,
    field TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    action TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO users(name, password) VALUES(?, ?)",
            [(name, "demo123") for name in ("Aisha", "Rohan", "Priya", "Meera", "Sam", "Dev")],
        )
        conn.execute("INSERT OR IGNORE INTO groups(name) VALUES(?)", ("Household Expense Ledger",))
        group_id = conn.execute("SELECT id FROM groups WHERE name=?", ("Household Expense Ledger",)).fetchone()["id"]
        for name, (joined, left) in MEMBERSHIPS.items():
            conn.execute("INSERT OR IGNORE INTO members(name) VALUES(?)", (name,))
            member_id = conn.execute("SELECT id FROM members WHERE name=?", (name,)).fetchone()["id"]
            conn.execute(
                """
                INSERT OR IGNORE INTO group_memberships(group_id, member_id, joined_on, left_on)
                VALUES (?, ?, ?, ?)
                """,
                (group_id, member_id, joined.isoformat(), left.isoformat() if left else None),
            )
        conn.execute("INSERT OR IGNORE INTO members(name) VALUES('Kabir')")


def default_group_id(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT id FROM groups ORDER BY id LIMIT 1").fetchone()["id"]


def save_import(filename: str, user_id: int | None, result: ImportResult) -> int:
    with connect() as conn:
        group_id = default_group_id(conn)
        cur = conn.execute("INSERT INTO import_runs(filename, imported_by) VALUES(?, ?)", (filename, user_id))
        import_run_id = cur.lastrowid
        for expense in result.expenses:
            cur = conn.execute(
                """
                INSERT INTO expenses(
                    group_id, import_run_id, source_row, expense_date, description, paid_by,
                    amount_original, currency, amount_inr, split_type, notes, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    import_run_id,
                    expense.row_number,
                    expense.date.isoformat(),
                    expense.description,
                    expense.paid_by,
                    str(expense.amount_original),
                    expense.currency,
                    str(expense.amount_inr),
                    expense.split_type,
                    expense.notes,
                    expense.status,
                ),
            )
            expense_id = cur.lastrowid
            for member, amount in expense.splits.items():
                conn.execute(
                    "INSERT INTO expense_splits(expense_id, member_name, amount_inr) VALUES (?, ?, ?)",
                    (expense_id, member, str(amount)),
                )
        for payment in result.payments:
            conn.execute(
                """
                INSERT INTO payments(
                    group_id, import_run_id, source_row, payment_date, payer, recipient,
                    amount_inr, description, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    import_run_id,
                    payment.row_number,
                    payment.date.isoformat(),
                    payment.payer,
                    payment.recipient,
                    str(payment.amount_inr),
                    payment.description,
                    payment.notes,
                ),
            )
        for anomaly in result.anomalies:
            conn.execute(
                """
                INSERT INTO import_anomalies(import_run_id, source_row, code, field, severity, message, action)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_run_id,
                    anomaly.row_number,
                    anomaly.code,
                    anomaly.field,
                    anomaly.severity,
                    anomaly.message,
                    anomaly.action,
                ),
            )
        return int(import_run_id)


def load_import_run(import_run_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM import_runs WHERE id=?", (import_run_id,)).fetchone()


def load_anomalies(import_run_id: int | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM import_anomalies"
    params: tuple = ()
    if import_run_id:
        sql += " WHERE import_run_id=?"
        params = (import_run_id,)
    sql += " ORDER BY source_row, id"
    with connect() as conn:
        return list(conn.execute(sql, params).fetchall())


def load_expenses() -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute("SELECT * FROM expenses ORDER BY expense_date, source_row").fetchall())


def load_expense_splits(expense_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute("SELECT * FROM expense_splits WHERE expense_id=? ORDER BY member_name", (expense_id,)).fetchall())


def load_payments() -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute("SELECT * FROM payments ORDER BY payment_date, source_row").fetchall())


def load_memberships() -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT g.name AS group_name, m.name AS member_name, gm.joined_on, gm.left_on
                FROM group_memberships gm
                JOIN groups g ON g.id = gm.group_id
                JOIN members m ON m.id = gm.member_id
                ORDER BY gm.joined_on, m.name
                """
            ).fetchall()
        )


def update_expense_status(expense_id: int, status: str) -> None:
    if status not in {"included", "excluded_duplicate", "needs_review"}:
        raise ValueError("Invalid status")
    with connect() as conn:
        conn.execute("UPDATE expenses SET status=? WHERE id=?", (status, expense_id))


def expense_trace(expense_id: int) -> dict:
    with connect() as conn:
        expense = conn.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
        splits = list(conn.execute("SELECT * FROM expense_splits WHERE expense_id=? ORDER BY member_name", (expense_id,)))
        anomalies = list(
            conn.execute(
                """
                SELECT a.* FROM import_anomalies a
                WHERE a.import_run_id=? AND a.source_row=?
                ORDER BY a.id
                """,
                (expense["import_run_id"], expense["source_row"]),
            )
        )
    return {"expense": expense, "splits": splits, "anomalies": anomalies}


def balance_summary() -> tuple[dict[str, Decimal], list[tuple[str, str, Decimal]]]:
    from .import_engine import ImportedExpense, ImportedPayment

    expenses = []
    with connect() as conn:
        for row in conn.execute("SELECT * FROM expenses ORDER BY source_row").fetchall():
            splits = {
                split["member_name"]: money(split["amount_inr"])
                for split in conn.execute("SELECT * FROM expense_splits WHERE expense_id=?", (row["id"],)).fetchall()
            }
            expenses.append(
                ImportedExpense(
                    row["source_row"],
                    date.fromisoformat(row["expense_date"]),
                    row["description"],
                    row["paid_by"],
                    money(row["amount_original"]),
                    row["currency"],
                    money(row["amount_inr"]),
                    row["split_type"],
                    splits,
                    row["notes"] or "",
                    row["status"],
                )
            )
        payments = [
            ImportedPayment(
                row["source_row"],
                date.fromisoformat(row["payment_date"]),
                row["payer"],
                row["recipient"],
                money(row["amount_inr"]),
                row["description"],
                row["notes"] or "",
            )
            for row in conn.execute("SELECT * FROM payments ORDER BY source_row").fetchall()
        ]
    balances = balances_for(expenses, payments)
    return balances, settlement_plan(balances)


def export_import_report(import_run_id: int) -> str:
    run = load_import_run(import_run_id)
    anomalies = load_anomalies(import_run_id)
    payload = {
        "import_run": dict(run) if run else None,
        "anomalies": [dict(row) for row in anomalies],
        "summary": {
            "total_anomalies": len(anomalies),
            "by_code": {},
        },
    }
    for row in anomalies:
        payload["summary"]["by_code"][row["code"]] = payload["summary"]["by_code"].get(row["code"], 0) + 1
    return json.dumps(payload, indent=2)
