#!/usr/bin/env python3
"""CCP Clearing House API-driven demo.

Drives the real microservice pipeline: submits trades via the API gateway,
lets Kafka propagate events through trade ingestion, margin, netting, and
settlement engines, then verifies results through API queries and DB reads.

Prerequisites:
    docker compose up -d
    python scripts/seed-members.py

Usage:
    python run_demo.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from decimal import Decimal

# ── Configuration ─────────────────────────────────────────────

API_GATEWAY = "http://localhost:8000"
NETTING_ENGINE = "http://localhost:8081"
DB_DSN = (
    "postgresql://readonly_user:readonly_secret_change_me"
    "@localhost:5433/ccp_clearing"
)
AUTH_HEADER = "Bearer demo"

POLL_INTERVAL = 2
NOVATION_TIMEOUT = 30
SETTLEMENT_TIMEOUT = 60

TRADE_SCENARIOS = [
    {
        "buyer": "Alpha Capital Markets",
        "seller": "Beta Securities LLC",
        "instrument": "BTC-PERP",
        "quantity": "10",
        "price": "67500.00",
    },
    {
        "buyer": "Gamma Digital Assets",
        "seller": "Delta Institutional Trading",
        "instrument": "ETH-FUTURE-Q2",
        "quantity": "100",
        "price": "3800.00",
    },
    {
        "buyer": "Beta Securities LLC",
        "seller": "Epsilon Fund Services",
        "instrument": "BTC-OPTION-30K",
        "quantity": "5",
        "price": "5200.00",
    },
    {
        "buyer": "Delta Institutional Trading",
        "seller": "Alpha Capital Markets",
        "instrument": "AAPL-TOKEN",
        "quantity": "500",
        "price": "185.50",
    },
    {
        "buyer": "Epsilon Fund Services",
        "seller": "Gamma Digital Assets",
        "instrument": "TBOND-10Y",
        "quantity": "1000",
        "price": "98.75",
    },
    {
        "buyer": "Alpha Capital Markets",
        "seller": "Gamma Digital Assets",
        "instrument": "REALESTATE-RWA-1",
        "quantity": "25",
        "price": "150000.00",
    },
]


# ── Output Formatting ─────────────────────────────────────────


def header(title: str) -> None:
    width = 72
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def subheader(title: str) -> None:
    print(f"\n  --- {title} ---")


def bullet(text: str) -> None:
    print(f"    - {text}")


def money(amount: str | Decimal) -> str:
    d = Decimal(str(amount))
    return f"${d:,.2f}"


# ── HTTP Helpers ──────────────────────────────────────────────


def api_get(path: str, base: str = API_GATEWAY) -> dict | list | None:
    """GET request to an API endpoint. Returns parsed JSON or None."""
    url = f"{base}{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", AUTH_HEADER)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"    [ERROR] GET {path}: {exc}")
        return None


def api_post(
    path: str,
    body: dict | None = None,
    base: str = API_GATEWAY,
) -> dict | list | None:
    """POST request to an API endpoint. Returns parsed JSON or None."""
    url = f"{base}{path}"
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", AUTH_HEADER)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode() if exc.fp else ""
        print(f"    [ERROR] POST {path}: {exc.code} {body_text}")
        return None
    except urllib.error.URLError as exc:
        print(f"    [ERROR] POST {path}: {exc}")
        return None


# ── Database Helper ───────────────────────────────────────────


def db_query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a read-only query and return rows as dicts."""
    import psycopg

    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


# ── Polling Helper ────────────────────────────────────────────


def poll_until(check_fn, interval: int, timeout: int, desc: str):
    """Poll check_fn every interval seconds until truthy or timeout."""
    elapsed = 0
    while elapsed < timeout:
        result = check_fn()
        if result:
            return result
        time.sleep(interval)
        elapsed += interval
    print(f"    [TIMEOUT] {desc} after {timeout}s")
    return None


# ── Phase 1: Infrastructure Check ─────────────────────────────


def phase_1_infrastructure() -> bool:
    header("PHASE 1: INFRASTRUCTURE CHECK")

    gw = api_get("/health")
    if gw and gw.get("status") == "ok":
        bullet(f"API Gateway: OK ({gw.get('service', '')})")
    else:
        bullet("API Gateway: UNREACHABLE")
        bullet("Run: docker compose up -d")
        return False

    ne = api_get("/health", base=NETTING_ENGINE)
    if ne and ne.get("status") == "ok":
        bullet(f"Netting Engine: OK ({ne.get('service', '')})")
    else:
        bullet("Netting Engine: UNREACHABLE")
        bullet("Ensure netting-engine port 8081 is mapped")
        return False

    try:
        rows = db_query("SELECT 1 AS ok")
        if rows and rows[0]["ok"] == 1:
            bullet("PostgreSQL: OK")
        else:
            bullet("PostgreSQL: query failed")
            return False
    except Exception as exc:
        bullet(f"PostgreSQL: {exc}")
        return False

    return True


# ── Phase 2: Verify Seed Data ─────────────────────────────────


def phase_2_seed_data() -> tuple[dict, dict] | None:
    header("PHASE 2: VERIFY SEED DATA")

    members_list = api_get("/members")
    if not members_list:
        bullet("No members found")
        bullet("Run: python scripts/seed-members.py")
        return None

    members = {m["name"]: m["id"] for m in members_list}
    bullet(f"Members: {len(members)}")
    for name in sorted(members):
        bullet(f"  {name}")

    instruments = db_query(
        "SELECT id, symbol, asset_class, settlement_type "
        "FROM instruments WHERE is_active = true"
    )
    if not instruments:
        bullet("No active instruments found")
        bullet("Run: python scripts/seed-members.py")
        return None

    inst_map = {i["symbol"]: str(i["id"]) for i in instruments}
    bullet(f"Instruments: {len(instruments)}")
    for i in instruments:
        bullet(
            f"  {i['symbol']} ({i['asset_class']}, "
            f"{i['settlement_type']})"
        )

    needed_members = set()
    needed_instruments = set()
    for s in TRADE_SCENARIOS:
        needed_members.add(s["buyer"])
        needed_members.add(s["seller"])
        needed_instruments.add(s["instrument"])

    missing_m = needed_members - set(members)
    missing_i = needed_instruments - set(inst_map)
    if missing_m:
        bullet(f"Missing members: {missing_m}")
        return None
    if missing_i:
        bullet(f"Missing instruments: {missing_i}")
        return None

    return members, inst_map


# ── Phase 3: Submit Trades ────────────────────────────────────


def phase_3_submit_trades(
    members: dict, instruments: dict,
) -> list[str]:
    header("PHASE 3: SUBMIT TRADES")

    trade_ids = []
    for i, s in enumerate(TRADE_SCENARIOS, 1):
        body = {
            "external_trade_id": f"DEMO-{uuid.uuid4().hex[:8]}",
            "instrument_id": instruments[s["instrument"]],
            "buyer_member_id": members[s["buyer"]],
            "seller_member_id": members[s["seller"]],
            "quantity": s["quantity"],
            "price": s["price"],
        }
        result = api_post("/trades", body)
        if result and "id" in result:
            trade_ids.append(result["id"])
            notional = Decimal(s["quantity"]) * Decimal(s["price"])
            bullet(
                f"Trade #{i}: {s['buyer']} buys "
                f"{s['quantity']} {s['instrument']} "
                f"from {s['seller']} "
                f"@ {money(s['price'])} "
                f"(notional: {money(notional)}) "
                f"[{result['id'][:8]}...]"
            )
        else:
            bullet(f"Trade #{i}: FAILED to submit")

    print(f"\n  {len(trade_ids)}/{len(TRADE_SCENARIOS)} trades submitted")
    return trade_ids


# ── Phase 4: Await Novation ───────────────────────────────────


def phase_4_novation(
    trade_ids: list[str], members: dict,
) -> bool:
    header("PHASE 4: AWAIT NOVATION")

    member_ids = set(members.values())
    all_novated = True

    for tid in trade_ids:
        def check(trade_id=tid):
            t = api_get(f"/trades/{trade_id}")
            if t and t.get("status") != "submitted":
                return t
            return None

        result = poll_until(
            check, POLL_INTERVAL, NOVATION_TIMEOUT,
            f"trade {tid[:8]} novation",
        )
        if result:
            status = result.get("status", "unknown")
            bullet(f"Trade {tid[:8]}...: {status}")
            if status != "novated":
                all_novated = False
        else:
            bullet(f"Trade {tid[:8]}...: still pending (timeout)")
            all_novated = False

    subheader("Member Positions")
    for name, mid in sorted(members.items()):
        positions = api_get(f"/members/{mid}/positions")
        if positions:
            for p in positions:
                bullet(
                    f"{name}: instrument={p['instrument_id'][:8]}... "
                    f"net={p['net_quantity']}"
                )

    return all_novated


# ── Phase 5: Prices & Margin ─────────────────────────────────


def phase_5_prices_margin(members: dict) -> None:
    header("PHASE 5: PRICES & MARGIN")

    subheader("Latest Prices")
    try:
        prices = db_query(
            "SELECT lp.instrument_id, i.symbol, lp.price "
            "FROM latest_prices lp "
            "JOIN instruments i ON i.id = lp.instrument_id "
            "ORDER BY i.symbol"
        )
        if prices:
            for p in prices:
                bullet(f"{p['symbol']}: {money(p['price'])}")
        else:
            bullet("No prices available yet (oracle may not have run)")
    except Exception as exc:
        bullet(f"Price query failed: {exc}")

    subheader("Member Margin Accounts")
    for name, mid in sorted(members.items()):
        accounts = api_get(f"/members/{mid}/accounts")
        if accounts:
            margin_accts = [
                a for a in accounts
                if "MARGIN" in a.get("account_type", "")
            ]
            if margin_accts:
                for a in margin_accts:
                    bullet(
                        f"{name}: {a['account_type']} "
                        f"({a['pool']}): {money(a['balance'])}"
                    )
            else:
                bullet(f"{name}: no margin accounts")


# ── Phase 6: Trigger Netting ──────────────────────────────────


def phase_6_netting() -> str | None:
    header("PHASE 6: TRIGGER NETTING")

    result = api_post(
        "/netting/trigger?cycle_type=manual",
        body={},
        base=NETTING_ENGINE,
    )
    if not result or "cycle_id" not in result:
        bullet("Failed to trigger netting cycle")
        if result:
            bullet(f"Response: {result}")
        return None

    cycle_id = result["cycle_id"]
    bullet(f"Cycle ID: {cycle_id}")
    bullet(f"Obligations: {result.get('obligation_count', '?')}")
    bullet(f"Instructions: {result.get('instruction_count', '?')}")
    bullet(f"Trades netted: {result.get('trades_netted', '?')}")

    subheader("Netting Obligations")
    obligations = api_get(
        f"/netting/cycles/{cycle_id}/obligations",
        base=NETTING_ENGINE,
    )
    if obligations:
        for o in obligations:
            bullet(
                f"Member {o['member_id'][:8]}...: "
                f"instrument={o['instrument_id'][:8]}... "
                f"net_qty={o['net_quantity']} "
                f"net_amt={money(o['net_amount'])}"
            )
    else:
        bullet("No obligations returned")

    return cycle_id


# ── Phase 7: Await Settlement ─────────────────────────────────


def phase_7_settlement(cycle_id: str) -> None:
    header("PHASE 7: AWAIT SETTLEMENT")

    terminal = {"confirmed", "failed", "cancelled"}

    def check():
        rows = db_query(
            "SELECT id, settlement_type, status, tx_hash "
            "FROM settlement_instructions "
            "WHERE netting_cycle_id = %s",
            (cycle_id,),
        )
        if not rows:
            return None
        all_done = all(r["status"] in terminal for r in rows)
        return rows if all_done else None

    result = poll_until(
        check, 3, SETTLEMENT_TIMEOUT,
        "settlement completion",
    )

    if result:
        subheader("Settlement Results")
        for r in result:
            line = (
                f"{r['settlement_type']}: {r['status']}"
            )
            if r.get("tx_hash"):
                line += f" (tx: {r['tx_hash'][:16]}...)"
            bullet(line)

        confirmed = sum(1 for r in result if r["status"] == "confirmed")
        failed = sum(1 for r in result if r["status"] == "failed")
        bullet(f"Total: {len(result)} instructions")
        bullet(f"Confirmed: {confirmed}, Failed: {failed}")
    else:
        subheader("Settlement Status (incomplete)")
        rows = db_query(
            "SELECT id, settlement_type, status "
            "FROM settlement_instructions "
            "WHERE netting_cycle_id = %s",
            (cycle_id,),
        )
        if rows:
            for r in rows:
                bullet(f"{r['settlement_type']}: {r['status']}")
        else:
            bullet("No settlement instructions found for this cycle")


# ── Phase 8: Reconciliation & Final State ─────────────────────


def phase_8_reconciliation(members: dict) -> None:
    header("PHASE 8: RECONCILIATION & FINAL STATE")

    subheader("Ledger Reconciliation")
    report = api_post("/reconcile")
    if report:
        bullet(f"Status: {report.get('status', '?')}")
        bullet(
            f"Global balance: "
            f"{'OK' if report.get('global_balance_ok') else 'MISMATCH'}"
        )
        bullet(
            f"Journal integrity: "
            f"{'OK' if report.get('journal_integrity_ok') else 'ISSUE'}"
        )
        bullet(f"Accounts checked: {report.get('accounts_checked', '?')}")
        bullet(f"Mismatches: {report.get('mismatches', 0)}")
        if report.get("details"):
            for d in report["details"]:
                bullet(
                    f"  Account {d['account_id']}: "
                    f"expected={d['expected_balance']} "
                    f"actual={d['actual_balance']} "
                    f"diff={d['difference']}"
                )
    else:
        bullet("Reconciliation request failed")

    subheader("Final Account Balances")
    for name, mid in sorted(members.items()):
        accounts = api_get(f"/members/{mid}/accounts")
        if accounts:
            for a in accounts:
                bal = a.get("balance", "0")
                if Decimal(str(bal)) != 0:
                    bullet(
                        f"{name}: {a['account_type']} "
                        f"({a['pool']}): {money(bal)}"
                    )

    subheader("Dead Letter Queue")
    dlq = api_get("/admin/dlq")
    if dlq:
        bullet(f"DLQ entries: {len(dlq)}")
        for entry in dlq[:5]:
            bullet(
                f"  {entry['service_name']}: {entry['topic']} "
                f"- {entry['error_message'][:60]}"
            )
    elif dlq is not None:
        bullet("DLQ: empty (no failed events)")
    else:
        bullet("DLQ: could not query")

    subheader("Note")
    bullet(
        "Default waterfall is event-driven "
        "(margin.call.breached / settlement.failed via Kafka) "
        "and cannot be triggered via HTTP"
    )


# ── Main ──────────────────────────────────────────────────────


def main() -> None:
    print()
    print("  CCP CLEARING HOUSE - API-Driven Demo")
    print()

    if not phase_1_infrastructure():
        print("\n  Infrastructure check failed. Aborting.")
        sys.exit(1)

    seed = phase_2_seed_data()
    if seed is None:
        print("\n  Seed data missing. Aborting.")
        sys.exit(1)
    members, instruments = seed

    trade_ids = phase_3_submit_trades(members, instruments)
    if not trade_ids:
        print("\n  No trades submitted. Aborting.")
        sys.exit(1)

    phase_4_novation(trade_ids, members)
    phase_5_prices_margin(members)

    cycle_id = phase_6_netting()
    if cycle_id:
        phase_7_settlement(cycle_id)
    else:
        print("\n  Netting cycle not created; skipping settlement.")

    phase_8_reconciliation(members)

    print()
    print("=" * 72)
    print("  DEMO COMPLETE")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
