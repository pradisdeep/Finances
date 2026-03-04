"""
Personal Finance Dashboard
--------------------------
A local web app to track end-of-day balances, salary planning, loans,
savings goals, and more.  Run with: python app.py
"""

import sqlite3
import json
import math
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

app = Flask(__name__)
app.secret_key = "finance-dashboard-secret-key"

# ─── Database Configuration ───────────────────────────────────────────────────

DB_PATH = "database.db"

ACCOUNTS = {
    "HDFC":  {"bucket": "Spending", "color": "#3B82F6"},
    "Kotak": {"bucket": "Bills",    "color": "#F59E0B"},
    "ICICI": {"bucket": "Wealth",   "color": "#10B981"},
}

BUCKET_COLORS = {
    "Spending": "#3B82F6",
    "Bills":    "#F59E0B",
    "Wealth":   "#10B981",
}

MONTHLY_SALARY = 228000

SALARY_TRANSFER_DEFAULTS = [
    {"name": "HDFC → Kotak",                "amount": 89000},
    {"name": "HDFC → ICICI",               "amount": 37500},
    {"name": "HDFC → ICICI Loan Repayment", "amount": 40000},
]

LOAN_DEFAULTS = [
    {"name": "Friend Loan", "original_amount": 229340, "outstanding": 229340, "emi": 40000},
    {"name": "Bike Loan",   "original_amount": 60000,  "outstanding": 60000,  "emi": 3900},
    {"name": "Home Loan",   "original_amount": 317968, "outstanding": 317968, "emi": 3542},
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables and seed defaults if needed."""
    with get_db() as conn:
        # ── Existing ────────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT    NOT NULL,
                account_name TEXT    NOT NULL,
                balance      REAL    NOT NULL,
                notes        TEXT,
                created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_date_account
            ON balances (date, account_name)
        """)

        # ── Feature 1 – Salary day transfers ────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS salary_transfers (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                date          TEXT    NOT NULL,
                transfer_name TEXT    NOT NULL,
                amount        REAL    NOT NULL,
                completed     INTEGER NOT NULL DEFAULT 0
            )
        """)

        # ── Feature 2 – Loans ───────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS loans (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT    NOT NULL UNIQUE,
                original_amount REAL    NOT NULL,
                outstanding     REAL    NOT NULL,
                emi             REAL    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS loan_payments (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                loan_id INTEGER NOT NULL,
                date    TEXT    NOT NULL,
                amount  REAL    NOT NULL,
                FOREIGN KEY (loan_id) REFERENCES loans(id)
            )
        """)

        # ── Features 3 & 4 – Savings goals ──────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS savings_goals (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                name                 TEXT    NOT NULL UNIQUE,
                target_amount        REAL    NOT NULL,
                current_saved        REAL    NOT NULL DEFAULT 0,
                monthly_contribution REAL    NOT NULL DEFAULT 0,
                return_rate          REAL    NOT NULL DEFAULT 7.0,
                notes                TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goal_contributions (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER NOT NULL,
                date    TEXT    NOT NULL,
                amount  REAL    NOT NULL,
                FOREIGN KEY (goal_id) REFERENCES savings_goals(id)
            )
        """)

        # ── Feature 5 – PPF / Sukanya yearly goals ──────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS yearly_goals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL UNIQUE,
                yearly_target REAL    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goal_transactions (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER NOT NULL,
                date    TEXT    NOT NULL,
                amount  REAL    NOT NULL,
                FOREIGN KEY (goal_id) REFERENCES yearly_goals(id)
            )
        """)

        # ── Feature 6 – Emergency fund config ───────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS emergency_fund_config (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                monthly_expenses REAL    NOT NULL DEFAULT 35000,
                target_months    INTEGER NOT NULL DEFAULT 6
            )
        """)

        # ── Seed loans ───────────────────────────────────────────────────────
        if conn.execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 0:
            for ln in LOAN_DEFAULTS:
                conn.execute(
                    "INSERT INTO loans (name, original_amount, outstanding, emi) VALUES (?, ?, ?, ?)",
                    (ln["name"], ln["original_amount"], ln["outstanding"], ln["emi"]),
                )

        # ── Seed savings goals ───────────────────────────────────────────────
        if conn.execute("SELECT COUNT(*) FROM savings_goals").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO savings_goals (name, target_amount, monthly_contribution, return_rate) VALUES (?, ?, ?, ?)",
                ("House Fund", 4000000, 30000, 8.0),
            )
            conn.execute(
                "INSERT INTO savings_goals (name, target_amount, monthly_contribution, return_rate) VALUES (?, ?, ?, ?)",
                ("Car Goal", 1500000, 15000, 6.0),
            )

        # ── Seed yearly goals ────────────────────────────────────────────────
        if conn.execute("SELECT COUNT(*) FROM yearly_goals").fetchone()[0] == 0:
            conn.execute("INSERT INTO yearly_goals (name, yearly_target) VALUES (?, ?)", ("PPF", 150000))
            conn.execute("INSERT INTO yearly_goals (name, yearly_target) VALUES (?, ?)", ("Sukanya", 150000))

        # ── Seed emergency fund config ────────────────────────────────────────
        if conn.execute("SELECT COUNT(*) FROM emergency_fund_config").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO emergency_fund_config (monthly_expenses, target_months) VALUES (?, ?)",
                (35000, 6),
            )



# ─── Helper: current Indian financial year ────────────────────────────────────

def current_fy():
    """Return (fy_start, fy_end) as ISO date strings for the current FY (Apr–Mar)."""
    today = date.today()
    if today.month >= 4:
        fy_start = date(today.year, 4, 1)
        fy_end   = date(today.year + 1, 3, 31)
    else:
        fy_start = date(today.year - 1, 4, 1)
        fy_end   = date(today.year, 3, 31)
    return fy_start.isoformat(), fy_end.isoformat()


# ─── Existing Helper Queries ──────────────────────────────────────────────────

def get_latest_balances():
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
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, account_name, balance
            FROM balances
            WHERE date >= ?
            ORDER BY date ASC, account_name ASC
        """, (cutoff,)).fetchall()
    trend: dict = {acc: [] for acc in ACCOUNTS}
    for r in rows:
        acc = r["account_name"]
        if acc in trend:
            trend[acc].append({"date": r["date"], "balance": r["balance"]})
    return trend


def get_monthly_snapshot():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT strftime('%Y-%m', date) AS month,
                   account_name,
                   AVG(balance) AS avg_balance,
                   MAX(balance) AS max_balance,
                   MIN(balance) AS min_balance
            FROM balances
            GROUP BY month, account_name
            ORDER BY month DESC, account_name ASC
        """).fetchall()
    return [dict(r) for r in rows]


# ─── Routes – Existing ────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    latest = get_latest_balances()
    total_cash = sum(r["balance"] for r in latest)

    enriched = []
    for row in latest:
        acc = row["account_name"]
        changes = get_balance_change(acc)
        change_pct = None
        change_abs = None
        is_big_change = False
        if len(changes) == 2:
            prev = changes[1]["balance"]
            curr = changes[0]["balance"]
            if prev:
                change_pct = round(((curr - prev) / prev) * 100, 2)
                change_abs = abs(curr - prev)
                is_big_change = abs(change_pct) >= 10
        enriched.append({
            **row,
            "bucket":        ACCOUNTS.get(acc, {}).get("bucket", "Other"),
            "color":         ACCOUNTS.get(acc, {}).get("color", "#6B7280"),
            "change_pct":    change_pct,
            "change_abs":    change_abs,
            "is_big_change": is_big_change,
        })

    buckets: dict = {}
    for row in enriched:
        b = row["bucket"]
        buckets.setdefault(b, {"accounts": [], "total": 0, "color": BUCKET_COLORS.get(b, "#6B7280")})
        buckets[b]["accounts"].append(row)
        buckets[b]["total"] += row["balance"]

    # ── Summary data for dashboard cards ─────────────────────────────────────
    with get_db() as conn:
        ef_cfg = conn.execute("SELECT * FROM emergency_fund_config LIMIT 1").fetchone()
        ef_monthly = ef_cfg["monthly_expenses"] if ef_cfg else 35000
        ef_months  = ef_cfg["target_months"]    if ef_cfg else 6
        ef_target  = ef_monthly * ef_months

        # Use HDFC balance as proxy for cash emergency fund
        hdfc_balance = next((r["balance"] for r in latest if r["account_name"] == "HDFC"), 0)
        ef_pct = min(100, round((hdfc_balance / ef_target * 100) if ef_target > 0 else 0, 1))

        # House fund
        house = conn.execute(
            "SELECT * FROM savings_goals WHERE name = 'House Fund'"
        ).fetchone()
        house = dict(house) if house else {}
        if house:
            house_total = (house.get("current_saved") or 0) + sum(
                r["amount"] for r in conn.execute(
                    "SELECT amount FROM goal_contributions WHERE goal_id = ?",
                    (house["id"],)
                ).fetchall()
            )
            house_pct = min(100, round(house_total / house["target_amount"] * 100, 1)) if house["target_amount"] else 0
        else:
            house_total = 0
            house_pct = 0

        # Loans total outstanding
        loans = [dict(r) for r in conn.execute("SELECT * FROM loans").fetchall()]
        total_outstanding = sum(ln["outstanding"] for ln in loans)
        total_original    = sum(ln["original_amount"] for ln in loans)
        loans_paid_pct    = min(100, round(((total_original - total_outstanding) / total_original * 100) if total_original else 0, 1))

        # PPF & Sukanya this FY
        fy_start, fy_end = current_fy()
        ppf_goal = conn.execute("SELECT * FROM yearly_goals WHERE name = 'PPF'").fetchone()
        sukanya_goal = conn.execute("SELECT * FROM yearly_goals WHERE name = 'Sukanya'").fetchone()

        def fy_deposited(goal_id):
            row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM goal_transactions WHERE goal_id = ? AND date >= ? AND date <= ?",
                (goal_id, fy_start, fy_end)
            ).fetchone()
            return row["total"] if row else 0

        ppf_deposited     = fy_deposited(ppf_goal["id"])     if ppf_goal     else 0
        sukanya_deposited = fy_deposited(sukanya_goal["id"]) if sukanya_goal else 0
        ppf_target        = ppf_goal["yearly_target"]        if ppf_goal     else 150000
        sukanya_target    = sukanya_goal["yearly_target"]    if sukanya_goal else 150000

    today = date.today().isoformat()
    trend_json = json.dumps(get_trend_data(days=30))

    return render_template(
        "dashboard.html",
        accounts=enriched,
        total_cash=total_cash,
        buckets=buckets,
        today=today,
        ef_target=ef_target,
        ef_pct=ef_pct,
        hdfc_balance=hdfc_balance,
        house_total=house_total,
        house_target=house.get("target_amount", 4000000),
        house_pct=house_pct,
        total_outstanding=total_outstanding,
        loans_paid_pct=loans_paid_pct,
        ppf_deposited=ppf_deposited,
        ppf_target=ppf_target,
        sukanya_deposited=sukanya_deposited,
        sukanya_target=sukanya_target,
        trend_json=trend_json,
        accounts_config=ACCOUNTS,
    )


@app.route("/add", methods=["GET", "POST"])
def add_entry():
    if request.method == "POST":
        entry_date   = request.form.get("date", "").strip()
        account_name = request.form.get("account", "").strip()
        balance_raw  = request.form.get("balance", "").strip()
        notes        = request.form.get("notes", "").strip()

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
            last_balances = {r["account_name"]: r["balance"] for r in get_latest_balances()}
            return render_template("add_entry.html", accounts=list(ACCOUNTS.keys()),
                                   last_balances=last_balances,
                                   form=request.form, today=date.today().isoformat())

        # ── Detect big change (>₹25,000) ─────────────────────────────────────
        big_change_warning = None
        last_balances_map = {r["account_name"]: r["balance"] for r in get_latest_balances()}
        if account_name in last_balances_map:
            prev_bal = last_balances_map[account_name]
            diff = abs(balance - prev_bal)
            if diff > 25000:
                direction = "increase" if balance > prev_bal else "decrease"
                big_change_warning = f"Large balance {direction} of ₹{diff:,.0f} detected for {account_name}."

        with get_db() as conn:
            conn.execute(
                "INSERT INTO balances (date, account_name, balance, notes) VALUES (?, ?, ?, ?)",
                (entry_date, account_name, balance, notes or None),
            )

        msg = f"Balance for {account_name} on {entry_date} saved successfully!"
        flash(msg, "success")
        if big_change_warning:
            flash(big_change_warning, "warning")
        return redirect(url_for("dashboard"))

    last_balances = {r["account_name"]: r["balance"] for r in get_latest_balances()}
    return render_template(
        "add_entry.html",
        accounts=list(ACCOUNTS.keys()),
        last_balances=last_balances,
        today=date.today().isoformat(),
    )


@app.route("/history")
def history():
    sort  = request.args.get("sort", "date")
    order = request.args.get("order", "desc")
    rows  = get_history(sort=sort, order=order)
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
    days = int(request.args.get("days", 30))
    trend = get_trend_data(days=days)
    monthly = get_monthly_snapshot()
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
    days = int(request.args.get("days", 30))
    return jsonify(get_trend_data(days=days))


@app.route("/delete/<int:entry_id>", methods=["POST"])
def delete_entry(entry_id):
    with get_db() as conn:
        conn.execute("DELETE FROM balances WHERE id = ?", (entry_id,))
    flash("Entry deleted.", "info")
    return redirect(url_for("history"))


@app.route("/edit/<int:entry_id>", methods=["POST"])
def edit_entry(entry_id):
    entry_date   = request.form.get("date", "").strip()
    account_name = request.form.get("account", "").strip()
    balance_raw  = request.form.get("balance", "").strip()
    notes        = request.form.get("notes", "").strip()

    errors = []
    if not entry_date:
        errors.append("Date is required.")
    if account_name not in ACCOUNTS:
        errors.append("Invalid account.")
    try:
        balance = float(balance_raw.replace(",", ""))
        if balance < 0:
            raise ValueError
    except ValueError:
        errors.append("Balance must be a valid non-negative number.")

    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("history"))

    with get_db() as conn:
        conn.execute(
            "UPDATE balances SET date = ?, account_name = ?, balance = ?, notes = ? WHERE id = ?",
            (entry_date, account_name, balance, notes or None, entry_id),
        )
    flash("Entry updated.", "success")
    return redirect(url_for("history"))


# ─── Feature 1 – Salary Day Planner ──────────────────────────────────────────

@app.route("/salary", methods=["GET", "POST"])
def salary():
    today_str = date.today().isoformat()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "init_plan":
            # Create today's transfer rows if not already present
            with get_db() as conn:
                existing = conn.execute(
                    "SELECT COUNT(*) FROM salary_transfers WHERE date = ?", (today_str,)
                ).fetchone()[0]
                if existing == 0:
                    for t in SALARY_TRANSFER_DEFAULTS:
                        conn.execute(
                            "INSERT INTO salary_transfers (date, transfer_name, amount, completed) VALUES (?, ?, ?, 0)",
                            (today_str, t["name"], t["amount"]),
                        )
            flash("Salary day plan created for today!", "success")

        elif action == "toggle":
            transfer_id = int(request.form.get("transfer_id", 0))
            completed   = int(request.form.get("completed", 0))
            with get_db() as conn:
                conn.execute(
                    "UPDATE salary_transfers SET completed = ? WHERE id = ?",
                    (1 - completed, transfer_id),  # toggle
                )

        elif action == "reset":
            with get_db() as conn:
                conn.execute("DELETE FROM salary_transfers WHERE date = ?", (today_str,))
            flash("Today's plan reset.", "info")

        return redirect(url_for("salary"))

    # ── GET ───────────────────────────────────────────────────────────────────
    with get_db() as conn:
        transfers = [dict(r) for r in conn.execute(
            "SELECT * FROM salary_transfers WHERE date = ? ORDER BY id", (today_str,)
        ).fetchall()]

        history_rows = [dict(r) for r in conn.execute(
            "SELECT date, transfer_name, amount, completed FROM salary_transfers "
            "WHERE date < ? ORDER BY date DESC, id ASC LIMIT 60",
            (today_str,)
        ).fetchall()]

    total_planned   = sum(t["amount"] for t in SALARY_TRANSFER_DEFAULTS)
    total_completed = sum(t["amount"] for t in transfers if t["completed"])
    all_done        = len(transfers) > 0 and all(t["completed"] for t in transfers)
    leave_in_hdfc   = MONTHLY_SALARY - total_planned

    return render_template(
        "salary.html",
        today=today_str,
        transfers=transfers,
        history_rows=history_rows,
        total_planned=total_planned,
        total_completed=total_completed,
        all_done=all_done,
        leave_in_hdfc=leave_in_hdfc,
        salary=MONTHLY_SALARY,
        defaults=SALARY_TRANSFER_DEFAULTS,
    )


# ─── Feature 2 – Loans ───────────────────────────────────────────────────────

def months_to_payoff(outstanding, emi):
    """Simple ceiling division; returns None if EMI is zero."""
    if not emi or emi <= 0:
        return None
    return math.ceil(outstanding / emi)


def payoff_date(months):
    """Return the estimated payoff date given number of months from today."""
    if months is None:
        return None
    target = date.today() + timedelta(days=30 * months)
    return target.strftime("%b %Y")


@app.route("/loans", methods=["GET", "POST"])
def loans():
    if request.method == "POST":
        loan_id    = int(request.form.get("loan_id", 0))
        amount_raw = request.form.get("amount", "").replace(",", "").strip()
        pay_date   = request.form.get("date", date.today().isoformat()).strip()

        try:
            amount = float(amount_raw)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Enter a valid payment amount.", "error")
            return redirect(url_for("loans"))

        with get_db() as conn:
            conn.execute(
                "INSERT INTO loan_payments (loan_id, date, amount) VALUES (?, ?, ?)",
                (loan_id, pay_date, amount),
            )
            # Reduce outstanding
            conn.execute(
                "UPDATE loans SET outstanding = MAX(0, outstanding - ?) WHERE id = ?",
                (amount, loan_id),
            )
        flash("Payment recorded.", "success")
        return redirect(url_for("loans"))

    with get_db() as conn:
        loans_raw = [dict(r) for r in conn.execute("SELECT * FROM loans ORDER BY id").fetchall()]
        payments  = [dict(r) for r in conn.execute(
            "SELECT lp.*, l.name AS loan_name FROM loan_payments lp "
            "JOIN loans l ON l.id = lp.loan_id ORDER BY lp.date DESC LIMIT 30"
        ).fetchall()]

    enriched_loans = []
    for ln in loans_raw:
        paid   = ln["original_amount"] - ln["outstanding"]
        pct    = min(100, round((paid / ln["original_amount"] * 100) if ln["original_amount"] else 0, 1))
        months = months_to_payoff(ln["outstanding"], ln["emi"])
        enriched_loans.append({
            **ln,
            "paid":         paid,
            "pct":          pct,
            "months_left":  months,
            "payoff_date":  payoff_date(months),
        })

    total_outstanding = sum(ln["outstanding"] for ln in loans_raw)
    today = date.today().isoformat()

    return render_template(
        "loans.html",
        loans=enriched_loans,
        payments=payments,
        total_outstanding=total_outstanding,
        today=today,
    )


# ─── Feature 3 & 4 – Savings Goals (House Fund & Car Goal) ───────────────────

def project_savings(current, monthly, annual_rate, months):
    """
    Future Value of existing savings + regular contributions.
    FV = current*(1+r)^n  +  monthly*((1+r)^n - 1)/r
    where r = monthly rate.
    """
    if annual_rate <= 0:
        return current + monthly * months
    r = annual_rate / 100 / 12
    fv_lump  = current * ((1 + r) ** months)
    fv_pmt   = monthly * (((1 + r) ** months - 1) / r)
    return fv_lump + fv_pmt


def months_to_goal(current, monthly, annual_rate, target):
    """Estimate how many months to reach target (binary search / linear approx)."""
    if current >= target:
        return 0
    if monthly <= 0 and annual_rate <= 0:
        return None
    for m in range(1, 600):  # cap at 50 years
        if project_savings(current, monthly, annual_rate, m) >= target:
            return m
    return None


def build_projection_chart(current, monthly, annual_rate, target, months_horizon):
    """Return labels and values for the projection chart."""
    labels, values = [], []
    today = date.today()
    for m in range(0, months_horizon + 1, max(1, months_horizon // 24)):
        d = today + timedelta(days=30 * m)
        labels.append(d.strftime("%b %Y"))
        values.append(round(project_savings(current, monthly, annual_rate, m), 2))
    return labels, values


@app.route("/house-fund", methods=["GET", "POST"])
def house_fund():
    with get_db() as conn:
        goal = dict(conn.execute("SELECT * FROM savings_goals WHERE name = 'House Fund'").fetchone())

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_settings":
            mc   = float(request.form.get("monthly_contribution", goal["monthly_contribution"]).replace(",", ""))
            rate = float(request.form.get("return_rate", goal["return_rate"]).replace(",", ""))
            with get_db() as conn:
                conn.execute(
                    "UPDATE savings_goals SET monthly_contribution = ?, return_rate = ? WHERE name = 'House Fund'",
                    (mc, rate),
                )
            flash("Settings updated.", "success")

        elif action == "add_contribution":
            amount_raw = request.form.get("amount", "").replace(",", "").strip()
            cont_date  = request.form.get("date", date.today().isoformat()).strip()
            try:
                amount = float(amount_raw)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                flash("Enter a valid contribution amount.", "error")
                return redirect(url_for("house_fund"))
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO goal_contributions (goal_id, date, amount) VALUES (?, ?, ?)",
                    (goal["id"], cont_date, amount),
                )
                conn.execute(
                    "UPDATE savings_goals SET current_saved = current_saved + ? WHERE id = ?",
                    (amount, goal["id"]),
                )
            flash(f"Contribution of ₹{amount:,.0f} added.", "success")

        return redirect(url_for("house_fund"))

    # Reload after potential update
    with get_db() as conn:
        goal = dict(conn.execute("SELECT * FROM savings_goals WHERE name = 'House Fund'").fetchone())
        contributions = [dict(r) for r in conn.execute(
            "SELECT * FROM goal_contributions WHERE goal_id = ? ORDER BY date DESC LIMIT 24",
            (goal["id"],)
        ).fetchall()]

    current  = goal["current_saved"]
    monthly  = goal["monthly_contribution"]
    rate     = goal["return_rate"]
    target   = goal["target_amount"]
    horizon  = 48  # 4 years in months
    pct      = min(100, round(current / target * 100, 1)) if target else 0
    months_needed = months_to_goal(current, monthly, rate, target)
    projected_at_horizon = project_savings(current, monthly, rate, horizon)

    chart_labels, chart_values = build_projection_chart(current, monthly, rate, target, horizon)
    target_line = [target] * len(chart_labels)

    return render_template(
        "house_fund.html",
        goal=goal,
        contributions=contributions,
        current=current,
        pct=pct,
        months_needed=months_needed,
        projected_at_horizon=projected_at_horizon,
        chart_labels=json.dumps(chart_labels),
        chart_values=json.dumps(chart_values),
        target_line=json.dumps(target_line),
        today=date.today().isoformat(),
    )


@app.route("/car-goal", methods=["GET", "POST"])
def car_goal():
    with get_db() as conn:
        goal = dict(conn.execute("SELECT * FROM savings_goals WHERE name = 'Car Goal'").fetchone())

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_settings":
            mc   = float(request.form.get("monthly_contribution", goal["monthly_contribution"]).replace(",", ""))
            rate = float(request.form.get("return_rate", goal["return_rate"]).replace(",", ""))
            with get_db() as conn:
                conn.execute(
                    "UPDATE savings_goals SET monthly_contribution = ?, return_rate = ? WHERE name = 'Car Goal'",
                    (mc, rate),
                )
            flash("Settings updated.", "success")

        elif action == "add_contribution":
            amount_raw = request.form.get("amount", "").replace(",", "").strip()
            cont_date  = request.form.get("date", date.today().isoformat()).strip()
            try:
                amount = float(amount_raw)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                flash("Enter a valid contribution amount.", "error")
                return redirect(url_for("car_goal"))
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO goal_contributions (goal_id, date, amount) VALUES (?, ?, ?)",
                    (goal["id"], cont_date, amount),
                )
                conn.execute(
                    "UPDATE savings_goals SET current_saved = current_saved + ? WHERE id = ?",
                    (amount, goal["id"]),
                )
            flash(f"Contribution of ₹{amount:,.0f} added.", "success")

        elif action == "loan_sim":
            # Optional loan simulation: calculate EMI
            price   = float(request.form.get("car_price", "1500000").replace(",", ""))
            down    = float(request.form.get("down_payment", "0").replace(",", ""))
            int_rate = float(request.form.get("interest_rate", "9").replace(",", ""))
            tenure  = int(request.form.get("tenure_months", "60"))
            principal = price - down
            r = int_rate / 100 / 12
            if r > 0:
                emi = principal * r * ((1 + r) ** tenure) / (((1 + r) ** tenure) - 1)
            else:
                emi = principal / tenure if tenure else 0
            flash(f"Loan EMI estimate: ₹{emi:,.0f}/month on ₹{principal:,.0f} for {tenure} months @ {int_rate}% p.a.", "info")
            return redirect(url_for("car_goal"))

        return redirect(url_for("car_goal"))

    # Reload
    with get_db() as conn:
        goal = dict(conn.execute("SELECT * FROM savings_goals WHERE name = 'Car Goal'").fetchone())
        contributions = [dict(r) for r in conn.execute(
            "SELECT * FROM goal_contributions WHERE goal_id = ? ORDER BY date DESC LIMIT 24",
            (goal["id"],)
        ).fetchall()]

    current  = goal["current_saved"]
    monthly  = goal["monthly_contribution"]
    rate     = goal["return_rate"]
    target   = goal["target_amount"]
    pct      = min(100, round(current / target * 100, 1)) if target else 0
    months_needed = months_to_goal(current, monthly, rate, target)
    horizon  = months_needed or 36
    chart_labels, chart_values = build_projection_chart(current, monthly, rate, target, horizon)
    target_line = [target] * len(chart_labels)

    purchase_date = None
    if months_needed is not None:
        pd = date.today() + timedelta(days=30 * months_needed)
        purchase_date = pd.strftime("%B %Y")

    return render_template(
        "car_goal.html",
        goal=goal,
        contributions=contributions,
        current=current,
        pct=pct,
        months_needed=months_needed,
        purchase_date=purchase_date,
        chart_labels=json.dumps(chart_labels),
        chart_values=json.dumps(chart_values),
        target_line=json.dumps(target_line),
        today=date.today().isoformat(),
    )


# ─── Feature 5 – Yearly Deposits (PPF / Sukanya) ─────────────────────────────

@app.route("/yearly-deposits", methods=["GET", "POST"])
def yearly_deposits():
    fy_start, fy_end = current_fy()

    if request.method == "POST":
        goal_id    = int(request.form.get("goal_id", 0))
        amount_raw = request.form.get("amount", "").replace(",", "").strip()
        dep_date   = request.form.get("date", date.today().isoformat()).strip()

        try:
            amount = float(amount_raw)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Enter a valid deposit amount.", "error")
            return redirect(url_for("yearly_deposits"))

        with get_db() as conn:
            conn.execute(
                "INSERT INTO goal_transactions (goal_id, date, amount) VALUES (?, ?, ?)",
                (goal_id, dep_date, amount),
            )
        flash("Deposit logged successfully.", "success")
        return redirect(url_for("yearly_deposits"))

    with get_db() as conn:
        goals_raw = [dict(r) for r in conn.execute("SELECT * FROM yearly_goals ORDER BY id").fetchall()]
        transactions = [dict(r) for r in conn.execute(
            "SELECT gt.*, yg.name AS goal_name FROM goal_transactions gt "
            "JOIN yearly_goals yg ON yg.id = gt.goal_id "
            "WHERE gt.date >= ? AND gt.date <= ? ORDER BY gt.date DESC",
            (fy_start, fy_end)
        ).fetchall()]
        all_transactions = [dict(r) for r in conn.execute(
            "SELECT gt.*, yg.name AS goal_name FROM goal_transactions gt "
            "JOIN yearly_goals yg ON yg.id = gt.goal_id "
            "ORDER BY gt.date DESC LIMIT 50"
        ).fetchall()]

    enriched = []
    for g in goals_raw:
        deposited = sum(t["amount"] for t in transactions if t["goal_id"] == g["id"])
        remaining = max(0, g["yearly_target"] - deposited)
        pct       = min(100, round(deposited / g["yearly_target"] * 100, 1)) if g["yearly_target"] else 0
        complete  = deposited >= g["yearly_target"]
        enriched.append({
            **g,
            "deposited": deposited,
            "remaining": remaining,
            "pct":       pct,
            "complete":  complete,
        })

    today = date.today().isoformat()
    return render_template(
        "yearly_deposits.html",
        goals=enriched,
        transactions=all_transactions,
        fy_start=fy_start,
        fy_end=fy_end,
        today=today,
    )


# ─── Feature 6 – Emergency Fund ──────────────────────────────────────────────

@app.route("/emergency-fund", methods=["GET", "POST"])
def emergency_fund():
    if request.method == "POST":
        monthly_expenses = float(request.form.get("monthly_expenses", "35000").replace(",", ""))
        target_months    = int(request.form.get("target_months", "6"))
        with get_db() as conn:
            conn.execute(
                "UPDATE emergency_fund_config SET monthly_expenses = ?, target_months = ?",
                (monthly_expenses, target_months),
            )
        flash("Emergency fund settings updated.", "success")
        return redirect(url_for("emergency_fund"))

    with get_db() as conn:
        cfg = dict(conn.execute("SELECT * FROM emergency_fund_config LIMIT 1").fetchone())

    monthly_expenses = cfg["monthly_expenses"]
    target_months    = cfg["target_months"]
    fund_required    = monthly_expenses * target_months

    # Use total cash as current emergency fund
    latest = get_latest_balances()
    total_cash = sum(r["balance"] for r in latest)
    hdfc_cash  = next((r["balance"] for r in latest if r["account_name"] == "HDFC"), 0)

    runway_months_total = total_cash / monthly_expenses if monthly_expenses > 0 else 0
    runway_months_hdfc  = hdfc_cash  / monthly_expenses if monthly_expenses > 0 else 0
    pct_total = min(100, round(total_cash / fund_required * 100, 1)) if fund_required > 0 else 0
    pct_hdfc  = min(100, round(hdfc_cash  / fund_required * 100, 1)) if fund_required > 0 else 0
    shortfall = max(0, fund_required - hdfc_cash)

    return render_template(
        "emergency_fund.html",
        cfg=cfg,
        monthly_expenses=monthly_expenses,
        target_months=target_months,
        fund_required=fund_required,
        total_cash=total_cash,
        hdfc_cash=hdfc_cash,
        runway_months_total=round(runway_months_total, 1),
        runway_months_hdfc=round(runway_months_hdfc, 1),
        pct_total=pct_total,
        pct_hdfc=pct_hdfc,
        shortfall=shortfall,
        today=date.today().isoformat(),
    )


# ─── Bootstrap ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("=" * 55)
    print("  Personal Finance Dashboard")
    print("  Open http://127.0.0.1:5000 in your browser")
    print("=" * 55)
    app.run(debug=False, host="0.0.0.0", port=5000)
