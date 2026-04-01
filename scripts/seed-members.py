"""Seed test clearing members, accounts, instruments, and default fund."""

import os
import sys
import uuid
from decimal import Decimal

import psycopg


DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://admin_user:admin_secret_change_me@localhost:5432/ccp_clearing",
)

MEMBERS = [
    {
        "lei": "529900HNOAA1KXQJUQ27",
        "name": "Alpha Capital Markets",
        "credit_limit": Decimal("50000000.00"),
    },
    {
        "lei": "213800WSGIIZCXF1P572",
        "name": "Beta Securities LLC",
        "credit_limit": Decimal("75000000.00"),
    },
    {
        "lei": "549300MLUDYVRQOOXS22",
        "name": "Gamma Digital Assets",
        "credit_limit": Decimal("30000000.00"),
    },
    {
        "lei": "353800KFBP72XHSW7E44",
        "name": "Delta Institutional Trading",
        "credit_limit": Decimal("100000000.00"),
    },
    {
        "lei": "815600OPPT9MZBGEE678",
        "name": "Epsilon Fund Services",
        "credit_limit": Decimal("60000000.00"),
    },
]

ACCOUNT_TYPES = [
    "MARGIN_IM",
    "MARGIN_VM",
    "DEFAULT_FUND",
    "COLLATERAL",
    "SETTLEMENT",
]

POOLS = ["AVAILABLE", "LOCKED"]

INSTRUMENTS = [
    {
        "symbol": "BTC-PERP",
        "asset_class": "crypto_perpetual",
        "settlement_type": "cash",
        "margin_rate_im": Decimal("0.100000"),
        "margin_rate_vm": Decimal("0.050000"),
    },
    {
        "symbol": "ETH-FUTURE-Q2",
        "asset_class": "crypto_future",
        "settlement_type": "cash",
        "margin_rate_im": Decimal("0.120000"),
        "margin_rate_vm": Decimal("0.060000"),
    },
    {
        "symbol": "BTC-OPTION-30K",
        "asset_class": "crypto_option",
        "settlement_type": "cash",
        "margin_rate_im": Decimal("0.150000"),
        "margin_rate_vm": Decimal("0.070000"),
    },
    {
        "symbol": "AAPL-TOKEN",
        "asset_class": "tokenized_equity",
        "settlement_type": "dvp",
        "margin_rate_im": Decimal("0.050000"),
        "margin_rate_vm": Decimal("0.025000"),
        "chain_id": "ethereum-mainnet",
        "contract_address": "0x1234567890abcdef1234567890abcdef12345678",
    },
    {
        "symbol": "TBOND-10Y",
        "asset_class": "tokenized_bond",
        "settlement_type": "dvp",
        "margin_rate_im": Decimal("0.030000"),
        "margin_rate_vm": Decimal("0.015000"),
        "chain_id": "ethereum-mainnet",
        "contract_address": "0xabcdef1234567890abcdef1234567890abcdef12",
    },
    {
        "symbol": "REALESTATE-RWA-1",
        "asset_class": "tokenized_rwa",
        "settlement_type": "dvp",
        "margin_rate_im": Decimal("0.200000"),
        "margin_rate_vm": Decimal("0.100000"),
        "chain_id": "polygon-mainnet",
        "contract_address": "0x9876543210fedcba9876543210fedcba98765432",
    },
]

DEFAULT_FUND_AMOUNTS = {
    "Alpha Capital Markets": Decimal("5000000.00"),
    "Beta Securities LLC": Decimal("7500000.00"),
    "Gamma Digital Assets": Decimal("3000000.00"),
    "Delta Institutional Trading": Decimal("10000000.00"),
    "Epsilon Fund Services": Decimal("6000000.00"),
}


def seed_ccp_house_account(conn: psycopg.Connection) -> uuid.UUID:
    """Create the CCP house member and its accounts."""
    ccp_id = uuid.uuid4()
    conn.execute(
        """
        INSERT INTO members (id, lei, name, status, credit_limit)
        VALUES (%s, %s, %s, 'active', 0)
        ON CONFLICT (lei) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (str(ccp_id), "CCP000000000000000", "CCP House Account"),
    )
    row = conn.fetchone()
    ccp_id = row[0] if row else ccp_id

    for acct_type in [*ACCOUNT_TYPES, "CCP_EQUITY"]:
        for pool in POOLS:
            conn.execute(
                """
                INSERT INTO accounts (member_id, account_type, currency, pool)
                VALUES (%s, %s, 'USD', %s)
                ON CONFLICT (member_id, account_type, currency, pool)
                DO NOTHING
                """,
                (str(ccp_id), acct_type, pool),
            )
    return ccp_id


def seed_members(conn: psycopg.Connection) -> dict[str, str]:
    """Insert clearing members and their accounts. Returns name->id map."""
    member_ids = {}
    for member in MEMBERS:
        member_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO members (id, lei, name, status, credit_limit)
            VALUES (%s, %s, %s, 'active', %s)
            ON CONFLICT (lei) DO UPDATE
                SET name = EXCLUDED.name, credit_limit = EXCLUDED.credit_limit
            RETURNING id
            """,
            (member_id, member["lei"], member["name"], member["credit_limit"]),
        )
        row = conn.fetchone()
        member_ids[member["name"]] = str(row[0]) if row else member_id

        for acct_type in ACCOUNT_TYPES:
            for pool in POOLS:
                conn.execute(
                    """
                    INSERT INTO accounts
                        (member_id, account_type, currency, pool)
                    VALUES (%s, %s, 'USD', %s)
                    ON CONFLICT (member_id, account_type, currency, pool)
                    DO NOTHING
                    """,
                    (member_ids[member["name"]], acct_type, pool),
                )
    return member_ids


def seed_instruments(conn: psycopg.Connection) -> None:
    """Insert sample instruments."""
    for inst in INSTRUMENTS:
        conn.execute(
            """
            INSERT INTO instruments (
                symbol, asset_class, settlement_type,
                margin_rate_im, margin_rate_vm,
                chain_id, contract_address
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol) DO NOTHING
            """,
            (
                inst["symbol"],
                inst["asset_class"],
                inst["settlement_type"],
                inst["margin_rate_im"],
                inst["margin_rate_vm"],
                inst.get("chain_id"),
                inst.get("contract_address"),
            ),
        )


def seed_default_fund(
    conn: psycopg.Connection,
    member_ids: dict[str, str],
    ccp_id: uuid.UUID,
) -> None:
    """Create initial default fund contributions via journal entries."""
    for name, amount in DEFAULT_FUND_AMOUNTS.items():
        mid = member_ids[name]

        conn.execute(
            "SELECT id FROM accounts WHERE member_id = %s "
            "AND account_type = 'DEFAULT_FUND' AND pool = 'AVAILABLE'",
            (mid,),
        )
        member_acct = conn.fetchone()

        conn.execute(
            "SELECT id FROM accounts WHERE member_id = %s "
            "AND account_type = 'CCP_EQUITY' AND pool = 'AVAILABLE'",
            (str(ccp_id),),
        )
        ccp_acct = conn.fetchone()

        if not member_acct or not ccp_acct:
            print(f"  Skipping default fund for {name}: accounts not found")
            continue

        journal_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'DEFAULT_FUND_CONTRIBUTION', 'seed', 'confirmed')
            """,
            (journal_id,),
        )
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, str(member_acct[0]), amount),
        )
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, str(ccp_acct[0]), amount),
        )
        print(f"  {name}: ${amount:,.2f} default fund contribution")


def main() -> None:
    """Run all seed operations."""
    print("Connecting to database...")
    with psycopg.connect(DB_URL) as conn:
        conn.autocommit = False
        try:
            print("Seeding CCP house account...")
            ccp_id = seed_ccp_house_account(conn)

            print("Seeding clearing members...")
            member_ids = seed_members(conn)
            print(f"  Created {len(member_ids)} members")

            print("Seeding instruments...")
            seed_instruments(conn)
            print(f"  Created {len(INSTRUMENTS)} instruments")

            print("Seeding default fund contributions...")
            seed_default_fund(conn, member_ids, ccp_id)

            conn.commit()
            print("Seed complete.")
        except Exception:
            conn.rollback()
            print("Seed failed, rolled back.", file=sys.stderr)
            raise


if __name__ == "__main__":
    main()
