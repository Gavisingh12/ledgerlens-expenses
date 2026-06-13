from __future__ import annotations

import hashlib
import hmac
import html
import os
import urllib.parse
from http import cookies
from wsgiref.simple_server import make_server

from .db import (
    balance_summary,
    connect,
    expense_trace,
    export_import_report,
    init_db,
    load_anomalies,
    load_expense_splits,
    load_expenses,
    load_import_run,
    load_memberships,
    load_payments,
    save_import,
    update_expense_status,
)
from .import_engine import import_csv_text


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def sign(value: str) -> str:
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def make_session(user_id: int, name: str) -> str:
    value = f"{user_id}:{name}"
    return f"{value}:{sign(value)}"


def read_session(environ) -> tuple[int, str] | None:
    raw = environ.get("HTTP_COOKIE", "")
    jar = cookies.SimpleCookie(raw)
    morsel = jar.get("session")
    if not morsel:
        return None
    parts = morsel.value.split(":")
    if len(parts) != 3:
        return None
    user_id, name, supplied = parts
    value = f"{user_id}:{name}"
    if not hmac.compare_digest(sign(value), supplied):
        return None
    return int(user_id), name


def parse_body(environ) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(length)
    content_type = environ.get("CONTENT_TYPE", "")
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    if content_type.startswith("application/x-www-form-urlencoded"):
        parsed = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
        fields = {key: values[0] for key, values in parsed.items()}
    elif content_type.startswith("multipart/form-data"):
        boundary = content_type.split("boundary=", 1)[1].encode()
        for part in body.split(b"--" + boundary):
            part = part.strip(b"\r\n")
            if not part or part == b"--":
                continue
            header_blob, _, data = part.partition(b"\r\n\r\n")
            headers = header_blob.decode("utf-8", errors="replace")
            disposition = next((line for line in headers.split("\r\n") if line.lower().startswith("content-disposition")), "")
            name = _header_param(disposition, "name")
            filename = _header_param(disposition, "filename")
            data = data.removesuffix(b"\r\n")
            if filename:
                files[name] = (filename, data)
            elif name:
                fields[name] = data.decode("utf-8", errors="replace")
    return fields, files


def _header_param(header: str, key: str) -> str:
    needle = f'{key}="'
    if needle not in header:
        return ""
    return header.split(needle, 1)[1].split('"', 1)[0]


def layout(title: str, content: str, user: tuple[int, str] | None = None) -> bytes:
    nav = ""
    if user:
        nav = f"""
        <nav>
          <a href="/">Dashboard</a>
          <a href="/expenses">Expenses</a>
          <a href="/import">Import</a>
          <a href="/groups">Groups</a>
          <a href="/logout">Logout {esc(user[1])}</a>
        </nav>
        """
    page = f"""<!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{esc(title)} | LedgerLens Expenses</title>
      <style>
        :root {{
          --ink:#17202a; --muted:#5b6673; --line:#d9dee5; --brand:#0f766e;
          --soft:#f6f8fb; --warn:#8a4b00; --bad:#9f1239; --good:#0f766e;
        }}
        * {{ box-sizing:border-box; }}
        body {{ margin:0; font-family:Arial, Helvetica, sans-serif; color:var(--ink); background:#fff; }}
        header {{ border-bottom:1px solid var(--line); padding:14px 22px; display:flex; justify-content:space-between; gap:16px; align-items:center; }}
        header h1 {{ font-size:20px; margin:0; }}
        nav {{ display:flex; gap:12px; flex-wrap:wrap; font-size:14px; }}
        nav a, a {{ color:var(--brand); text-decoration:none; font-weight:600; }}
        main {{ max-width:1180px; margin:0 auto; padding:24px; }}
        .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:16px; }}
        .card {{ border:1px solid var(--line); border-radius:8px; padding:16px; background:#fff; }}
        .band {{ background:var(--soft); border-block:1px solid var(--line); padding:16px; margin:0 -24px 20px; }}
        table {{ width:100%; border-collapse:collapse; font-size:14px; }}
        th, td {{ border-bottom:1px solid var(--line); padding:9px 8px; text-align:left; vertical-align:top; }}
        th {{ background:var(--soft); font-size:13px; }}
        .muted {{ color:var(--muted); }}
        .status-included {{ color:var(--good); font-weight:700; }}
        .status-needs_review, .warn {{ color:var(--warn); font-weight:700; }}
        .status-excluded_duplicate, .bad {{ color:var(--bad); font-weight:700; }}
        input, textarea, select {{ width:100%; border:1px solid var(--line); border-radius:6px; padding:10px; font:inherit; }}
        button, .button {{ display:inline-block; border:0; border-radius:6px; padding:10px 13px; background:var(--brand); color:white; font-weight:700; cursor:pointer; }}
        form.inline {{ display:inline; }}
        .right {{ text-align:right; }}
        .pill {{ display:inline-block; padding:3px 8px; border:1px solid var(--line); border-radius:999px; font-size:12px; }}
      </style>
    </head>
    <body>
      <header><h1>LedgerLens Expenses</h1>{nav}</header>
      <main>{content}</main>
    </body>
    </html>"""
    return page.encode("utf-8")


def redirect(start_response, location: str, headers: list[tuple[str, str]] | None = None):
    response_headers = [("Location", location)]
    if headers:
        response_headers.extend(headers)
    start_response("303 See Other", response_headers)
    return [b""]


def require_login(environ, start_response):
    user = read_session(environ)
    if not user:
        return None, redirect(start_response, "/login")
    return user, None


def app(environ, start_response):
    init_db()
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET")
    user = read_session(environ)

    if path == "/login":
        return login(environ, start_response, method)
    if path == "/logout":
        return redirect(start_response, "/login", [("Set-Cookie", "session=; Max-Age=0; Path=/")])

    user, login_response = require_login(environ, start_response)
    if login_response:
        return login_response

    if path == "/":
        return dashboard(start_response, user)
    if path == "/groups":
        return groups(start_response, user)
    if path == "/expenses":
        return expenses_page(start_response, user)
    if path.startswith("/expenses/") and path.endswith("/trace"):
        expense_id = int(path.split("/")[2])
        return trace_page(start_response, user, expense_id)
    if path == "/import":
        if method == "POST":
            return run_import(environ, start_response, user)
        return import_page(start_response, user)
    if path.startswith("/imports/") and path.endswith("/report.json"):
        import_run_id = int(path.split("/")[2])
        payload = export_import_report(import_run_id).encode("utf-8")
        start_response("200 OK", [("Content-Type", "application/json"), ("Content-Disposition", f"attachment; filename=import-{import_run_id}-report.json")])
        return [payload]
    if path.startswith("/imports/"):
        import_run_id = int(path.split("/")[2])
        return import_report(start_response, user, import_run_id)
    if path.startswith("/review/") and method == "POST":
        expense_id = int(path.split("/")[2])
        fields, _ = parse_body(environ)
        update_expense_status(expense_id, fields.get("status", "needs_review"))
        return redirect(start_response, "/expenses")

    start_response("404 Not Found", [("Content-Type", "text/html; charset=utf-8")])
    return [layout("Not found", "<h2>Not found</h2>", user)]


def login(environ, start_response, method: str):
    error = ""
    if method == "POST":
        fields, _ = parse_body(environ)
        with connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE name=? AND password=?", (fields.get("name"), fields.get("password"))).fetchone()
        if row:
            cookie = f"session={make_session(row['id'], row['name'])}; Path=/; HttpOnly; SameSite=Lax"
            return redirect(start_response, "/", [("Set-Cookie", cookie)])
        error = "<p class='bad'>Invalid login. Try any seeded member with password demo123.</p>"
    content = f"""
    <section class="band"><h2>Login</h2><p class="muted">Seed users: Aisha, Rohan, Priya, Meera, Sam, Dev. Password: demo123.</p></section>
    {error}
    <form method="post" class="card" style="max-width:420px">
      <label>Name<input name="name" value="Aisha" required></label><br><br>
      <label>Password<input name="password" type="password" value="demo123" required></label><br><br>
      <button type="submit">Login</button>
    </form>
    """
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
    return [layout("Login", content)]


def dashboard(start_response, user):
    balances, plan = balance_summary()
    balance_rows = "".join(
        f"<tr><td>{esc(name)}</td><td class='right'>{amount}</td><td>{'gets back' if amount > 0 else 'owes' if amount < 0 else 'settled'}</td></tr>"
        for name, amount in balances.items()
    )
    plan_rows = "".join(
        f"<tr><td>{esc(payer)}</td><td>{esc(receiver)}</td><td class='right'>₹{amount}</td></tr>"
        for payer, receiver, amount in plan
    ) or "<tr><td colspan='3'>No settlement needed yet.</td></tr>"
    content = f"""
    <section class="band">
      <h2>Balance Summary</h2>
      <p class="muted">Positive means that person should receive money. Negative means that person owes money.</p>
    </section>
    <div class="grid">
      <div class="card"><h3>Per-person net</h3><table><tr><th>Member</th><th class="right">Net INR</th><th>Meaning</th></tr>{balance_rows}</table></div>
      <div class="card"><h3>Who pays whom</h3><table><tr><th>Payer</th><th>Receiver</th><th class="right">Amount</th></tr>{plan_rows}</table></div>
    </div>
    """
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
    return [layout("Dashboard", content, user)]


def groups(start_response, user):
    rows = "".join(
        f"<tr><td>{esc(row['group_name'])}</td><td>{esc(row['member_name'])}</td><td>{esc(row['joined_on'])}</td><td>{esc(row['left_on'] or 'active')}</td></tr>"
        for row in load_memberships()
    )
    content = f"""
    <section class="band"><h2>Group Membership Timeline</h2><p class="muted">Membership windows drive whether a row can charge a person.</p></section>
    <table><tr><th>Group</th><th>Member</th><th>Joined</th><th>Left</th></tr>{rows}</table>
    """
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
    return [layout("Groups", content, user)]


def import_page(start_response, user):
    content = """
    <section class="band"><h2>Import CSV</h2><p class="muted">Upload the original expenses_export.csv without editing it first.</p></section>
    <form method="post" enctype="multipart/form-data" class="card">
      <label>CSV file<input type="file" name="csv_file" accept=".csv,text/csv" required></label><br><br>
      <button type="submit">Import and generate report</button>
    </form>
    """
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
    return [layout("Import", content, user)]


def run_import(environ, start_response, user):
    _, files = parse_body(environ)
    filename, data = files.get("csv_file", ("upload.csv", b""))
    result = import_csv_text(data.decode("utf-8-sig"))
    import_run_id = save_import(filename, user[0], result)
    return redirect(start_response, f"/imports/{import_run_id}")


def import_report(start_response, user, import_run_id: int):
    run = load_import_run(import_run_id)
    anomalies = load_anomalies(import_run_id)
    by_code: dict[str, int] = {}
    for anomaly in anomalies:
        by_code[anomaly["code"]] = by_code.get(anomaly["code"], 0) + 1
    summary = "".join(f"<tr><td>{esc(code)}</td><td>{count}</td></tr>" for code, count in sorted(by_code.items()))
    rows = "".join(
        f"<tr><td>{a['source_row']}</td><td><span class='pill'>{esc(a['code'])}</span></td><td>{esc(a['field'])}</td><td>{esc(a['message'])}</td><td>{esc(a['action'])}</td></tr>"
        for a in anomalies
    )
    content = f"""
    <section class="band">
      <h2>Import Report #{import_run_id}</h2>
      <p class="muted">File: {esc(run['filename'] if run else '')}. This is the required import report produced by the app.</p>
      <p><a class="button" href="/imports/{import_run_id}/report.json">Download JSON report</a></p>
    </section>
    <div class="grid">
      <div class="card"><h3>Anomalies by type</h3><table><tr><th>Code</th><th>Count</th></tr>{summary}</table></div>
      <div class="card"><h3>Import totals</h3><p>{len(anomalies)} anomalies detected and handled.</p></div>
    </div>
    <h3>Every anomaly</h3>
    <table><tr><th>CSV row</th><th>Code</th><th>Field</th><th>Detected problem</th><th>Action taken</th></tr>{rows}</table>
    """
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
    return [layout("Import report", content, user)]


def expenses_page(start_response, user):
    rows = ""
    for expense in load_expenses():
        splits = ", ".join(f"{s['member_name']}: ₹{s['amount_inr']}" for s in load_expense_splits(expense["id"]))
        actions = ""
        if expense["status"] == "needs_review":
            actions = f"""
            <form class="inline" method="post" action="/review/{expense['id']}"><input type="hidden" name="status" value="included"><button>Include</button></form>
            <form class="inline" method="post" action="/review/{expense['id']}"><input type="hidden" name="status" value="excluded_duplicate"><button>Exclude</button></form>
            """
        rows += f"""
        <tr>
          <td>{expense['source_row']}</td><td>{esc(expense['expense_date'])}</td><td>{esc(expense['description'])}</td>
          <td>{esc(expense['paid_by'])}</td><td class="right">₹{esc(expense['amount_inr'])}</td>
          <td>{esc(splits)}</td><td class="status-{esc(expense['status'])}">{esc(expense['status'])}</td>
          <td><a href="/expenses/{expense['id']}/trace">Trace</a> {actions}</td>
        </tr>
        """
    payment_rows = "".join(
        f"<tr><td>{p['source_row']}</td><td>{esc(p['payment_date'])}</td><td>{esc(p['payer'])}</td><td>{esc(p['recipient'])}</td><td class='right'>₹{esc(p['amount_inr'])}</td><td>{esc(p['description'])}</td></tr>"
        for p in load_payments()
    )
    content = f"""
    <section class="band"><h2>Expenses and Payments</h2><p class="muted">Trace links show the exact splits and anomalies behind a row.</p></section>
    <h3>Expenses</h3>
    <table><tr><th>CSV row</th><th>Date</th><th>Description</th><th>Paid by</th><th class="right">INR</th><th>Splits</th><th>Status</th><th>Review</th></tr>{rows}</table>
    <h3>Payments / settlements</h3>
    <table><tr><th>CSV row</th><th>Date</th><th>Payer</th><th>Recipient</th><th class="right">INR</th><th>Description</th></tr>{payment_rows}</table>
    """
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
    return [layout("Expenses", content, user)]


def trace_page(start_response, user, expense_id: int):
    trace = expense_trace(expense_id)
    expense = trace["expense"]
    split_rows = "".join(f"<tr><td>{esc(s['member_name'])}</td><td class='right'>₹{esc(s['amount_inr'])}</td></tr>" for s in trace["splits"])
    anomaly_rows = "".join(
        f"<tr><td>{esc(a['code'])}</td><td>{esc(a['message'])}</td><td>{esc(a['action'])}</td></tr>" for a in trace["anomalies"]
    ) or "<tr><td colspan='3'>No anomalies on this row.</td></tr>"
    content = f"""
    <section class="band"><h2>Trace CSV row {expense['source_row']}</h2><p class="muted">{esc(expense['description'])}</p></section>
    <div class="grid">
      <div class="card"><h3>Expense</h3><p>Paid by {esc(expense['paid_by'])}: ₹{esc(expense['amount_inr'])}</p><p>Status: {esc(expense['status'])}</p></div>
      <div class="card"><h3>Split math</h3><table><tr><th>Member</th><th class="right">Charged</th></tr>{split_rows}</table></div>
    </div>
    <h3>Importer decisions</h3><table><tr><th>Code</th><th>Detected problem</th><th>Action</th></tr>{anomaly_rows}</table>
    """
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
    return [layout("Trace", content, user)]


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    print(f"Serving on http://127.0.0.1:{port}")
    make_server("0.0.0.0", port, app).serve_forever()
