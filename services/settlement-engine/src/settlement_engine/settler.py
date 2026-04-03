"""Settlement execution with full state machine for cash and DVP."""

import base64
import logging
import time
import uuid
from decimal import Decimal

import psycopg

from ccp_shared.chain.base import DVPInstruction, TransactionStatus
from ccp_shared.chain.registry import ChainRegistry
from ccp_shared.errors import StateTransitionError
from ccp_shared.enums import StateEntityType
from ccp_shared.kafka.outbox import insert_outbox_event
from ccp_shared.signing.client import SigningClient
from ccp_shared.trace import TraceContext

logger = logging.getLogger(__name__)

MAX_CONFIRMATION_POLLS = 30
POLL_INTERVAL_SECONDS = 2

VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"approved", "failed", "cancelled"},
    "approved": {"signed", "failed"},
    "signed": {"broadcasted", "failed"},
    "broadcasted": {"confirmed", "failed"},
    "confirmed": set(),
    "failed": set(),
    "cancelled": set(),
}


def _validate_transition(
    inst_id: str, from_status: str, to_status: str,
) -> None:
    """Validate a settlement status transition.

    Args:
        inst_id: Settlement instruction UUID for error context.
        from_status: Current status.
        to_status: Desired next status.

    Raises:
        StateTransitionError: If the transition is not allowed.
    """
    allowed = VALID_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise StateTransitionError(
            f"Invalid settlement transition: {from_status} -> {to_status}",
            entity_type=StateEntityType.SETTLEMENT_INSTRUCTION,
            entity_id=uuid.UUID(inst_id),
            from_status=from_status,
            to_status=to_status,
        )


def _advance_status(
    conn: psycopg.Connection,
    inst_id: str,
    from_status: str,
    to_status: str,
    reason: str,
    trace: TraceContext,
) -> None:
    """Transition settlement instruction status with validation."""
    _validate_transition(inst_id, from_status, to_status)
    conn.execute(
        """
        UPDATE settlement_instructions
        SET status = %s, updated_at = now()
        WHERE id = %s
        """,
        (to_status, inst_id),
    )
    _record_transition(conn, inst_id, from_status, to_status, reason, trace)


def settle_instruction(
    conn: psycopg.Connection,
    instruction_id: str,
    chain_registry: ChainRegistry,
    signing_client: SigningClient,
    trace: TraceContext | None = None,
) -> dict:
    """Execute a settlement instruction (cash or DVP).

    Args:
        conn: Database connection with ledger permissions.
        instruction_id: UUID of the settlement instruction.
        chain_registry: Registry of chain adapters.
        signing_client: Client for threshold signing.
        trace: Optional trace context for audit correlation.

    Returns:
        Dict with settlement result details.
    """
    if trace is None:
        trace = TraceContext.new_system("settlement-engine")

    row = conn.execute(
        """
        SELECT si.id, si.settlement_type, si.from_member_id, si.to_member_id,
               si.instrument_id, si.quantity, si.amount, si.chain_id,
               i.contract_address
        FROM settlement_instructions si
        JOIN instruments i ON i.id = si.instrument_id
        WHERE si.id = %s AND si.status = 'pending'
        """,
        (instruction_id,),
    ).fetchone()

    if not row:
        logger.warning("Instruction %s not found or not pending", instruction_id)
        return {"status": "skipped", "reason": "not_found_or_not_pending"}

    settlement_type = row[1]
    if settlement_type == "cash":
        return _settle_cash(conn, row, trace)
    elif settlement_type in ("dvp", "physical"):
        return _settle_dvp(conn, row, chain_registry, signing_client, trace)
    else:
        logger.error("Unknown settlement type: %s", settlement_type)
        return {"status": "error", "reason": f"unknown_type_{settlement_type}"}


def _settle_cash(
    conn: psycopg.Connection,
    instruction_row: tuple,
    trace: TraceContext,
) -> dict:
    """Execute cash settlement via the full state machine.

    Transitions: pending -> approved -> signed -> broadcasted -> confirmed.
    For cash, signed and broadcasted are auto-advanced (no external action).
    """
    inst_id = str(instruction_row[0])
    from_member = str(instruction_row[2])
    to_member = str(instruction_row[3])
    amount = instruction_row[6]

    from_acct = _get_account(conn, from_member, "SETTLEMENT", "AVAILABLE")
    to_acct = _get_account(conn, to_member, "SETTLEMENT", "AVAILABLE")
    if not from_acct or not to_acct:
        _fail_instruction(conn, inst_id, "pending", "Settlement accounts not found", trace)
        return {"status": "failed", "reason": "accounts_not_found"}

    _advance_status(conn, inst_id, "pending", "approved", "Validation passed", trace)
    _advance_status(conn, inst_id, "approved", "signed", "Cash: no signing needed", trace)
    _advance_status(conn, inst_id, "signed", "broadcasted", "Cash: no broadcast needed", trace)

    journal_id = str(uuid.uuid4())
    if amount and Decimal(str(amount)) > 0:
        conn.execute(
            """
            INSERT INTO journals
                (id, journal_type, reference_type, reference_id, status)
            VALUES (%s, 'SETTLEMENT', 'settlement_instruction',
                    %s, 'confirmed')
            """,
            (journal_id, inst_id),
        )
        conn.execute(
            """
            INSERT INTO journal_entries
                (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, from_acct, amount),
        )
        conn.execute(
            """
            INSERT INTO journal_entries
                (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, to_acct, amount),
        )

    _advance_status(
        conn, inst_id, "broadcasted", "confirmed",
        "Cash settlement completed", trace,
    )
    _emit_settlement_event(conn, inst_id, "settlement.completed", from_member, trace)

    logger.info("Cash settlement completed: instruction=%s amount=%s", inst_id, amount)
    return {"status": "confirmed", "instruction_id": inst_id, "journal_id": journal_id}


def _settle_dvp(
    conn: psycopg.Connection,
    instruction_row: tuple,
    chain_registry: ChainRegistry,
    signing_client: SigningClient,
    trace: TraceContext,
) -> dict:
    """Execute DVP settlement via on-chain transaction.

    Transitions: pending -> approved -> signed -> broadcasted -> confirmed.
    """
    inst_id = str(instruction_row[0])
    from_member = str(instruction_row[2])
    to_member = str(instruction_row[3])
    instrument_id = str(instruction_row[4])
    quantity = instruction_row[5]
    amount = instruction_row[6]
    chain_id = instruction_row[7]
    contract_address = instruction_row[8]

    if not chain_id:
        _fail_instruction(conn, inst_id, "pending", "No chain_id for DVP settlement", trace)
        return {"status": "failed", "reason": "no_chain_id"}

    adapter = chain_registry.get(chain_id)
    if not adapter:
        _fail_instruction(
            conn, inst_id, "pending",
            f"No adapter for chain {chain_id}", trace,
        )
        return {"status": "failed", "reason": "no_chain_adapter"}

    _advance_status(conn, inst_id, "pending", "approved", "DVP validation passed", trace)
    conn.commit()

    try:
        dvp_instruction = DVPInstruction(
            chain_id=chain_id,
            seller_address=from_member,
            buyer_address=to_member,
            asset_token_address=contract_address or "",
            asset_amount=quantity,
            payment_token_address="",
            payment_amount=amount,
            instruction_id=uuid.UUID(inst_id),
        )
        unsigned_tx = adapter.build_dvp_tx(dvp_instruction)
        sign_response = signing_client.sign(unsigned_tx, chain_id)
        signed_tx = base64.b64decode(sign_response.signed_tx_bytes)

        conn.autocommit = False
        _advance_status(conn, inst_id, "approved", "signed", "MPC signing complete", trace)
        conn.commit()

        result = adapter.submit_signed_tx(signed_tx)

        conn.autocommit = False
        conn.execute(
            """
            UPDATE settlement_instructions
            SET tx_hash = %s, updated_at = now()
            WHERE id = %s
            """,
            (result.tx_hash, inst_id),
        )
        _advance_status(conn, inst_id, "signed", "broadcasted", "Tx submitted", trace)
        conn.commit()

        required_confirmations = adapter.get_required_confirmations()
        tx_result = _poll_confirmations(
            adapter, result.tx_hash, required_confirmations,
        )

        conn.autocommit = False
        if tx_result.status == TransactionStatus.CONFIRMED:
            return _finalize_dvp(
                conn, inst_id, from_member, to_member, amount,
                result.tx_hash, None,
                tx_result.confirmations, trace,
            )
        else:
            _fail_instruction(
                conn, inst_id, "broadcasted",
                f"Tx failed: {tx_result.tx_hash}", trace,
            )
            conn.commit()
            return {"status": "failed", "instruction_id": inst_id}

    except Exception as exc:
        logger.exception("DVP settlement failed: %s", inst_id)
        conn.autocommit = False
        _fail_instruction(conn, inst_id, "approved", str(exc), trace)
        conn.commit()
        return {"status": "failed", "instruction_id": inst_id, "error": str(exc)}


def _finalize_dvp(
    conn: psycopg.Connection,
    inst_id: str,
    from_member: str,
    to_member: str,
    amount: Decimal,
    tx_hash: str,
    block_number: int | None,
    confirmations: int,
    trace: TraceContext,
) -> dict:
    """Create final journal entries after DVP confirmation."""
    from_acct = _get_account(conn, from_member, "SETTLEMENT", "AVAILABLE")
    to_acct = _get_account(conn, to_member, "SETTLEMENT", "AVAILABLE")

    if from_acct and to_acct:
        journal_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, reference_id, status)
            VALUES (%s, 'SETTLEMENT', 'settlement_instruction', %s, 'confirmed')
            """,
            (journal_id, inst_id),
        )
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, from_acct, amount),
        )
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, to_acct, amount),
        )

    conn.execute(
        """
        UPDATE settlement_instructions
        SET block_number = %s, confirmations = %s, updated_at = now()
        WHERE id = %s
        """,
        (block_number, confirmations, inst_id),
    )
    _advance_status(
        conn, inst_id, "broadcasted", "confirmed",
        "DVP confirmed on-chain", trace,
    )
    _emit_settlement_event(conn, inst_id, "settlement.completed", from_member, trace)
    conn.commit()

    logger.info("DVP settlement confirmed: %s tx=%s", inst_id, tx_hash)
    return {"status": "confirmed", "instruction_id": inst_id, "tx_hash": tx_hash}


def _poll_confirmations(adapter, tx_hash: str, required: int):
    """Poll chain adapter for transaction confirmations."""
    for _ in range(MAX_CONFIRMATION_POLLS):
        result = adapter.get_tx_status(tx_hash)
        if result.status == TransactionStatus.CONFIRMED:
            if result.confirmations >= required:
                return result
        elif result.status == TransactionStatus.FAILED:
            return result
        time.sleep(POLL_INTERVAL_SECONDS)
    return adapter.get_tx_status(tx_hash)


def _get_account(
    conn: psycopg.Connection,
    member_id: str,
    account_type: str,
    pool: str,
) -> str | None:
    """Look up an account ID."""
    row = conn.execute(
        """
        SELECT id FROM accounts
        WHERE member_id = %s AND account_type = %s AND pool = %s
        """,
        (member_id, account_type, pool),
    ).fetchone()
    return str(row[0]) if row else None


def _fail_instruction(
    conn: psycopg.Connection,
    inst_id: str,
    from_status: str,
    reason: str,
    trace: TraceContext,
) -> None:
    """Mark a settlement instruction as failed."""
    conn.execute(
        """
        UPDATE settlement_instructions
        SET status = 'failed', updated_at = now()
        WHERE id = %s
        """,
        (inst_id,),
    )
    _record_transition(conn, inst_id, from_status, "failed", reason, trace)
    _emit_settlement_event(conn, inst_id, "settlement.failed", inst_id, trace)


def _record_transition(
    conn: psycopg.Connection,
    entity_id: str,
    from_status: str,
    to_status: str,
    reason: str,
    trace: TraceContext,
) -> None:
    """Record a state transition with trace context."""
    conn.execute(
        """
        INSERT INTO state_transitions
            (entity_type, entity_id, from_status, to_status,
             reason, transitioned_by, trace_id, actor)
        VALUES ('settlement_instruction', %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            entity_id,
            from_status,
            to_status,
            reason,
            f"settlement-engine:{trace.actor}",
            trace.trace_id,
            trace.actor,
        ),
    )


def _emit_settlement_event(
    conn: psycopg.Connection,
    inst_id: str,
    event_type: str,
    aggregate_id: str,
    trace: TraceContext,
) -> None:
    """Emit a settlement outbox event."""
    insert_outbox_event(
        conn,
        aggregate_type="settlement_instruction",
        aggregate_id=uuid.UUID(aggregate_id) if len(aggregate_id) == 36 else uuid.uuid4(),
        event_type=event_type,
        topic=event_type,
        payload={"instruction_id": inst_id},
        trace_id=trace.trace_id,
    )
