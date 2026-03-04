"""
Personal Finance Dashboard
--------------------------
A local web app to track end-of-day balances across HDFC, Kotak, and ICICI accounts.
Run with: python app.py
"""

import sqlite3
import json
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

app = Flask(__name__)
app.secret_key = "finance-dashboard-secret-key"

# ─── Database Configuration ───────────────────────────────────────────────────

DB_PATH = "database.db"

# Account → bucket mapping
ACCOUNTS = {
    "HDFC":  {"bucket": "Spending", "color": "#3B82F6"},   # blue
    "Kotak": {"bucket": "Bills",    "color": "#F59E0B"},   # amber
    "ICICI": {"bucket": "Wealth",   "color": "#10B981"},   # emerald
}

BUCKET_COLORS = {
    "Spending": "#3B82F6",
    "Bills":    "#F59E0B",
    "Wealth":   "#10B981",
}


def get_db():
    """Open a database connection with row_factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the balances table if it doesn't exist, then seed sample data."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT    NOT NULL,
                account_name TEXT   NOT NULL,
                balance     REAL    NOT NULL,
                notes       TEXT,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_date_account
            ON balances (date, account_name)
        """)

        # Seed sample data only when the table is empty
        count = conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0]
        if count == 0:
            seed_sample_data(conn)


def seed_sample_data(conn):
    """Insert 30 days of realistic sample data for all three accounts."""
    today = date.today()
    samples = []

    # Starting balances
    balances = {"HDFC": 85000, "Kotak": 42000, "ICICI": 150000}

    for i in range(29, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        for account, info in ACCOUNTS.items():
            # Simulate small daily fluctuations
            import random
            random.seed(i + hash(account))
            delta = random.randint(-3000, 5000)
            balances[account] = max(1000, balances[account] + delta)
            note = "Sample data" if i > 0 else "Today's opening balance"
            samples.append((d, account, round(balances[account], 2), note))

    conn.executemany(
        "INSERT INTO balances (date, account_name, balance, notes) VALUES (?, ?, ?, ?)",
        samples,
    )


# ─── Helper Queries ───────────────────────────────────────────────────────────

def get_latest_balances():
    """Return the most recent balance for each account."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT account_name, balance, date, notes
            FROM balances
            WHERE (account_name, date) IN (
                SELECT account_name, MAX(date)
                FROM balances
                GROUP BY account_name
            )
            ORDER BY account_name
        """).fetchall()
    return [dict(r) for r in rows]


def get_balance_change(account_name):
    """Return today's and yesterday's balance for an account to detect big swings."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, balance
            FROM balances
            WHERE account_name = ?
            ORDER BY date DESC
            LIMIT 2
        """, (account_name,)).fetchall()
    return [dict(r) for r in rows]


def get_history(sort="date", order="desc", limit=200):
    """Return balance history with optional sorting."""
    allowed_cols = {"date", "account_name", "balance"}
    col = sort if sort in allowed_cols else "date"
    direction = "DESC" if order.lower() == "desc" else "ASC"

    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT id, date, account_name, balance, notes, created_at
            FROM balances
            ORDER BY {col} {direction}, account_name ASC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_trend_data(days=60):
    """Return balance trend data per account for the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, account_name, balance
            FROM balances
            WHERE date >= ?
            ORDER BY date ASC, account_name ASC
        """, (cutoff,)).fetchall()

    # Pivot into {account: [{date, balance}]}
    trend: dict = {acc: [] for acc in ACCOUNTS}
    for r in rows:
        acc = r["account_name"]
        if acc in trend:
            trend[acc].append({"date": r["date"], "balance": r["balance"]})
    return trend


def get_monthly_snapshot():
    """Return per-month totals (sum of latest daily balance per account)."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT strftime('%Y-%m', date) AS month,
                   account_name,
                   AVG(balance)            AS avg_balance,
                   MAX(balance)            AS max_balance,
                   MIN(balance)            AS min_balance
            FROM balances
            GROUP BY month, account_name
            ORDER BY month DESC, account_name ASC
        """).fetchall()
    return [dict(r) for r in rows]


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    """Main dashboard: current balances, totals, and bucket summary."""
    latest = get_latest_balances()
    total_cash = sum(r["balance"] for r in latest)

    # Enrich with bucket info and change indicators
    enriched = []
    for row in latest:
        acc = row["account_name"]
        changes = get_balance_change(acc)
        change_pct = None
        is_big_change = False
        if len(changes) == 2:
            prev = changes[1]["balance"]
            curr = changes[0]["balance"]
            if prev:
                change_pct = round(((curr - prev) / prev) * 100, 2)
                is_big_change = abs(change_pct) >= 10   # flag ≥10% swing
        enriched.append({
            **row,
            "bucket":        ACCOUNTS.get(acc, {}).get("bucket", "Other"),
            "color":         ACCOUNTS.get(acc, {}).get("color", "#6B7280"),
            "change_pct":    change_pct,
            "is_big_change": is_big_change,
        })

    # Group by bucket
    buckets: dict = {}
    for row in enriched:
        b = row["bucket"]
        buckets.setdefault(b, {"accounts": [], "total": 0, "color": BUCKET_COLORS.get(b, "#6B7280")})
        buckets[b]["accounts"].append(row)
        buckets[b]["total"] += row["balance"]

    today = date.today().isoformat()
    return render_template(
        "dashboard.html",
        accounts=enriched,
        total_cash=total_cash,
        buckets=buckets,
        today=today,
    )


@app.route("/add", methods=["GET", "POST"])
def add_entry():
    """Form to add a new daily balance entry."""
    if request.method == "POST":
        entry_date   = request.form.get("date", "").strip()
        account_name = request.form.get("account", "").strip()
        balance_raw  = request.form.get("balance", "").strip()
        notes        = request.form.get("notes", "").strip()

        # Basic validation
        errors = []
        if not entry_date:
            errors.append("Date is required.")
        if account_name not in ACCOUNTS:
            errors.append("Invalid account selected.")
        try:
            balance = float(balance_raw.replace(",", ""))
            if balance < 0:
                errors.append("Balance cannot be negative.")
        except ValueError:
            errors.append("Balance must be a valid number.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("add_entry.html", accounts=list(ACCOUNTS.keys()),
                                   form=request.form, today=date.today().isoformat())

        with get_db() as conn:
            conn.execute(
                "INSERT INTO balances (date, account_name, balance, notes) VALUES (?, ?, ?, ?)",
                (entry_date, account_name, balance, notes or None),
            )

        flash(f"Balance for {account_name} on {entry_date} saved successfully!", "success")
        return redirect(url_for("dashboard"))

    # Pre-fill last known balances so the user can update quickly
    last_balances = {r["account_name"]: r["balance"] for r in get_latest_balances()}

    return render_template(
        "add_entry.html",
        accounts=list(ACCOUNTS.keys()),
        last_balances=last_balances,
        today=date.today().isoformat(),
    )


@app.route("/history")
def history():
    """Table of all balance entries, sortable by date/account/balance."""
    sort  = request.args.get("sort", "date")
    order = request.args.get("order", "desc")
    rows  = get_history(sort=sort, order=order)

    # Flip order for the next click on the same column
    next_order = "asc" if order == "desc" else "desc"

    return render_template(
        "history.html",
        rows=rows,
        sort=sort,
        order=order,
        next_order=next_order,
        accounts=list(ACCOUNTS.keys()),
    )


@app.route("/charts")
def charts():
    """Line charts showing balance trends per account."""
    days = int(request.args.get("days", 30))
    trend = get_trend_data(days=days)
    monthly = get_monthly_snapshot()

    # Serialize for Chart.js
    trend_json = json.dumps(trend)

    return render_template(
        "charts.html",
        trend_json=trend_json,
        monthly=monthly,
        days=days,
        accounts=ACCOUNTS,
    )


@app.route("/api/trend")
def api_trend():
    """JSON endpoint for live chart refresh without page reload."""
    days = int(request.args.get("days", 30))
    return jsonify(get_trend_data(days=days))


@app.route("/delete/<int:entry_id>", methods=["POST"])
def delete_entry(entry_id):
    """Delete a single balance record."""
    with get_db() as conn:
        conn.execute("DELETE FROM balances WHERE id = ?", (entry_id,))
    flash("Entry deleted.", "info")
    return redirect(url_for("history"))


# ─── Bootstrap ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("=" * 55)
    print("  Personal Finance Dashboard")
    print("  Open http://127.0.0.1:5000 in your browser")
    print("=" * 55)
    app.run(debug=True, host="127.0.0.1", port=5000)
