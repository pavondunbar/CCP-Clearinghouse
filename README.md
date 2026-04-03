# Central Counterparty (CCP) Clearing House (Python)

> **SANDBOX / EDUCATIONAL USE ONLY — NOT FOR PRODUCTION**
> This codebase is a reference implementation designed for learning, prototyping, and architectural exploration. It is **not audited, not legally reviewed, and must not be used to clear real trades, manage real margin, or handle real collateral or settlement.** See the [Production Warning](#production-warning) section for full details.

---

## Table of Contents

- [Overview](#overview)
- [What is a CCP?](#what-is-a-ccp)
- [Architecture](#architecture)
- [Core Services](#core-services)
- [Key Features & Design Patterns](#key-features--design-patterns)
- [Database Schema](#database-schema)
- [State Machines](#state-machines)
- [Real-World Example: Full Clearing Lifecycle](#real-world-example-full-clearing-lifecycle)
- [Running in a Sandbox Environment](#running-in-a-sandbox-environment)
- [Project Structure](#project-structure)
- [Production Warning](#production-warning)
- [License](#license)

---

## Overview

The **CCP Clearing House** is a Python-based reference implementation that models the full lifecycle of a **central counterparty clearing house** — from trade submission and novation through margin calculation, multilateral netting, collateral management, settlement (cash, physical, and on-chain DvP), default waterfall execution, and post-trade reconciliation. Every operation is protected by **role-based access control (RBAC)** and recorded in an **append-only double-entry ledger** with distributed tracing.

The system is modeled closely on how institutional clearing infrastructure operates at **LCH (London Clearing House)**, **CME Clearing**, **DTCC**, **Eurex Clearing**, and **ICE Clear**. It demonstrates how traditional post-trade infrastructure (novation, netting, margin, default fund) integrates with blockchain technology (on-chain DvP settlement, MPC threshold signing, tokenized instruments) to achieve T+0 finality while eliminating bilateral counterparty risk.

| Component | Count | Responsibility |
|-----------|-------|----------------|
| Microservices | 14 | Gateway, ingestion, netting, margin, collateral, settlement, liquidation, pricing, compliance, signing, outbox, reconciliation |
| MPC Nodes | 3 | 2-of-3 threshold cryptography for on-chain settlement signing |
| Kafka Topics | 20+ | Event-driven communication across all services |
| Database Tables | 20+ | Append-only immutable ledger with double-entry accounting |
| API Endpoints | 15+ | Full REST API behind RBAC-authenticated gateway |
| Docker Networks | 3 | Trust boundary isolation (DMZ, internal, signing) |
| Migration Files | 22 | Sequential schema versions with immutability triggers |

---

## What is a CCP?

A **Central Counterparty Clearing House (CCP)** is the single most critical piece of infrastructure in modern financial markets. When two parties agree on a trade, the CCP steps in between them — becoming the buyer to every seller and the seller to every buyer. This process, called **novation**, eliminates bilateral counterparty risk: if one party defaults, the other party's position is protected by the CCP's layered loss-absorption mechanism (the **default waterfall**).

CCPs are the backbone of:
- **Futures and options exchanges** (CME, ICE, Eurex) — every listed derivative is centrally cleared
- **Interest rate swap clearing** (LCH SwapClear clears >90% of global IRS notional)
- **Equity and fixed income clearing** (DTCC's NSCC clears virtually all US equity trades)
- **Crypto derivatives clearing** — the emerging frontier where this system operates
- **Tokenized securities settlement** — DvP with on-chain atomic finality

The core risk management mechanism is the **default waterfall**:

```
Default Waterfall — Loss Absorption Priority
─────────────────────────────────────────────

1. Defaulter's Initial Margin         ← First loss absorbed by the defaulter
2. Defaulter's Default Fund            ← Defaulter's mutualized contribution
3. CCP Equity (Skin-in-the-Game)       ← CCP's own capital at risk
4. Non-Defaulting Members' Fund        ← Mutualized loss sharing
5. CCP Additional Equity               ← Second tranche of CCP capital
6. Assessment Powers                   ← Emergency calls on surviving members
```

This system implements the full institutional workflow: trade ingestion, novation, margin calculation (IM and VM), multilateral netting, collateral management, cash/physical/on-chain settlement, default detection and waterfall execution, and post-trade reconciliation — with MPC-signed blockchain transactions and an immutable double-entry ledger.

---

## Architecture

```
                    ┌──────────────────────────────────────────────────────────┐
                    │              CCP CLEARING LIFECYCLE                      │
                    └──────────────────────────────────────────────────────────┘

  DMZ Network (Internet-Facing)            Internal Network (Kafka-Driven)
  ─────────────────────────────────────────────────────────────────────────────

  Clients ──► API Gateway (8000)
              │  RBAC (5 roles via X-API-Key)
              │  Idempotency-Key deduplication
              │  Audit trail → Kafka (trace_id + actor_id)
              │
              ├──► Trade Ingestion (8001)       PostgreSQL 16
              │    Kafka consumer                │  Append-only ledger
              │    Trade validation               │  Double-entry journals
              │    Novation (split into           │  Immutability triggers
              │     CCP-facing legs)              │  Transactional outbox
              │                                   │
              ├──► Netting Engine (8003/8081)     │
              │    Multilateral netting            │
              │    Net obligation computation      │
              │    Cycle management ◄─────────────┤
              │                                   │
              ├──► Margin Engine (8004)           │
              │    Initial margin (IM)             │
              │    Variation margin (VM)           │
              │    Margin call issuance            │
              │                                   │
              ├──► Collateral Manager (8005)      │
              │    Deposit / withdraw              │
              │    Lock / release                  │
              │    Balance tracking ◄─────────────┤
              │                                   │
              ├──► Settlement Engine (8006)       │        Signing Network
              │    Cash / physical / DvP           │        │
              │    On-chain settlement ────────────┼────────├── Signing Gateway (8010)
              │    State machine tracking          │        │     Fan-out + combine
              │                                   │        │
              ├──► Liquidation Engine (8007)      │        ├── MPC Node 1
              │    Default detection               │        ├── MPC Node 2
              │    6-step waterfall execution       │        └── MPC Node 3
              │    Loss allocation                 │             2-of-3 threshold
              │                                   │
              ├──► Price Oracle (8008)            │
              │    Instrument price feeds          │
              │    Materialized latest_prices      │
              │                                   │
              ├──► Compliance Monitor (8009)      │
              │    Market abuse detection          │
              │    Kafka event consumption         │
              │                                   │
              └──► Reconciliation Engine          │
                   Ledger replay verification      │
                   Balance cross-check             │
                                                  │
              Outbox Publisher (8002) ─────────────┤──► Apache Kafka
              Polls outbox table                        20+ event topics
              Advisory locking (SKIP LOCKED)             7-day retention
              At-least-once delivery + DLQ
                                                  │
              Prometheus (9090) ◄──────────────────┤    Metrics scraping
              Grafana (3000)                            Dashboard visualization
```

### Trust Boundary Network Isolation

| Network | Type | Services | Purpose |
|---------|------|----------|---------|
| `dmz` | bridge | API Gateway, Netting Engine, PostgreSQL | Internet-facing — only exposed ports |
| `internal` | bridge | All microservices, PostgreSQL, Kafka, Zookeeper | Business logic — no outbound internet access |
| `signing` | bridge | Signing Gateway, MPC Nodes 1-3, Settlement Engine | Isolated cryptographic operations |

The API gateway bridges the DMZ and internal networks. The settlement engine bridges internal and signing. MPC nodes communicate only with the signing gateway. PostgreSQL is accessible from DMZ (for direct queries) and internal (for service access), but not from the signing network.

---

## Core Services

### `API Gateway` — Authentication & Routing (port 8000)

The sole internet-facing service. Authenticates all requests via `X-API-Key` with role-based access control, enforces idempotency via `Idempotency-Key` headers, propagates distributed trace context to internal services, and provides REST endpoints for trade submission, member/position queries, netting triggers, and reconciliation. Aggregated health check across all upstream services.

**Key endpoints:**
- `POST /trades` — Submit a new trade for clearing
- `GET /members` — List clearing members
- `GET /positions/{member_id}` — Member positions and exposures
- `POST /netting/trigger` — Trigger a manual netting cycle
- `GET /reconcile` — Run ledger reconciliation
- `GET /health` — Aggregated health of all services

### `Trade Ingestion` — Novation Engine (port 8001)

Consumes `trades.submitted` events from Kafka, validates trade parameters (instrument existence, member status, quantity/price constraints), and executes novation — splitting each bilateral trade into two CCP-facing legs. The original trade between Party A and Party B becomes: (1) Party A ↔ CCP and (2) CCP ↔ Party B. Creates initial margin journal entries atomically with the novated trade records.

**Responsibilities:**
- Trade validation against member and instrument registries
- Novation: bilateral trade → two CCP-facing novated trades
- Initial margin journal entries (double-entry)
- Transactional outbox events for downstream consumption

### `Netting Engine` — Multilateral Netting (port 8003/8081)

Computes multilateral net obligations across all open positions. Instead of settling every individual trade, the netting engine aggregates all of a member's obligations per instrument into a single net amount — reducing the number and value of settlement instructions by 80-95% (consistent with real-world CCP netting ratios).

**Responsibilities:**
- Scheduled, manual, and intraday netting cycle types
- Net obligation computation per member per instrument
- Settlement instruction generation from net obligations
- Cut-off time enforcement for cycle windows

### `Margin Engine` — Risk Management (port 8004)

Calculates initial margin (IM) and variation margin (VM) requirements for every member's portfolio. IM covers potential future exposure using instrument-specific margin rates. VM covers the daily mark-to-market profit/loss. Issues margin calls when posted collateral falls below required levels.

**Responsibilities:**
- Initial margin calculation (instrument margin rate × notional)
- Variation margin computation (mark-to-market against latest prices)
- Margin call issuance with configurable deadlines
- Margin call status tracking (issued → acknowledged → met / breached)
- Breach detection triggers default waterfall

### `Collateral Manager` — Deposit & Lock Operations (port 8005)

Manages collateral deposits, withdrawals, and lock/release operations across member accounts. Tracks balances across six account types (MARGIN_IM, MARGIN_VM, SETTLEMENT, DEFAULT_FUND, COLLATERAL, CCP_EQUITY) with three pool states (AVAILABLE, RESERVED, LOCKED).

**Responsibilities:**
- Collateral deposit and withdrawal with journal entries
- Lock collateral for pending settlement or margin calls
- Release collateral after settlement confirmation
- Balance queries across account types and pools

### `Settlement Engine` — Cash, Physical & On-Chain DvP (port 8006)

Processes settlement instructions generated by the netting engine. Supports three settlement types: cash (fiat currency movement), physical (asset delivery), and on-chain DvP (blockchain atomic swap). On-chain settlements are signed by the MPC threshold signing cluster before broadcast.

**Responsibilities:**
- Settlement instruction lifecycle management
- Cash settlement via journal entries
- Physical delivery tracking
- On-chain DvP via signing gateway and blockchain adapter
- Settlement confirmation with tx_hash and block_number recording

### `Liquidation Engine` — Default Waterfall (port 8007)

Executes the 6-step default waterfall when a clearing member fails to meet margin obligations. Each step is recorded as an immutable waterfall step with the applied amount, ensuring a complete audit trail of loss allocation.

**Waterfall Steps:**
1. **DEFAULTER_MARGIN** — Seize defaulter's initial and variation margin
2. **DEFAULTER_DEFAULT_FUND** — Apply defaulter's default fund contribution
3. **CCP_SKIN_IN_GAME** — CCP puts its own equity at risk
4. **NON_DEFAULTER_DEFAULT_FUND** — Mutualized loss sharing across surviving members
5. **CCP_ADDITIONAL_EQUITY** — Second tranche of CCP capital
6. **ASSESSMENT_POWERS** — Emergency cash calls on surviving members

### `Price Oracle` — Instrument Price Feeds (port 8008)

Fetches and publishes current instrument prices for all registered instruments. Maintains a materialized view (`latest_prices`) for fast lookups. Prices feed into margin calculations, mark-to-market valuations, and netting cycle computations.

### `Compliance Monitor` — Regulatory Surveillance (port 8009)

Consumes all lifecycle events from Kafka and applies rule-based screening for market abuse patterns, position limit violations, and suspicious activity. Operates as fire-and-forget — it never blocks the originating transaction.

### `Signing Gateway` — MPC Signature Aggregation (port 8010)

Coordinates MPC signing requests across three independent MPC nodes in the isolated signing network. Fans out the signing payload to all nodes, collects partial signatures, and combines them when the 2-of-3 threshold is met. Returns the combined signature for on-chain transaction broadcast.

### `MPC Nodes` (3 instances) — Threshold Cryptography

Three independent signing nodes that each produce a partial signature using their shard of the signing key. No single node holds the complete key — a minimum of 2 nodes must cooperate to produce a valid signature.

> **Note:** The MPC implementation uses deterministic SHA256 hashing for demonstration purposes. A production system would use Shamir's Secret Sharing, GG20/FROST threshold ECDSA, or equivalent cryptographic protocols.

### `Outbox Publisher` — Reliable Event Delivery (port 8002)

Standalone service that polls the `outbox_events` table and publishes pending events to Kafka. Uses PostgreSQL advisory locking (`FOR UPDATE SKIP LOCKED`) for safe horizontal scaling across multiple replicas.

**Pattern:** Solves the dual-write problem — business operations and their events are committed atomically to PostgreSQL, then delivered to Kafka asynchronously with at-least-once guarantees.

### `Reconciliation Engine` — Ledger Integrity Verification

Replays journal entries, recomputes account balances from scratch, and compares against the derived `account_balances` view. Any discrepancy is flagged immediately. Also verifies dead letter queue status for failed event delivery.

---

## Key Features & Design Patterns

### Double-Entry Accounting Ledger

Every financial operation — margin posting, collateral deposit, settlement transfer, waterfall loss allocation — records balanced debit/credit journal entry pairs. All balances are derived from journal entries via the `account_balances` view (no mutable balance columns). The ledger is append-only: corrections are made via offsetting entries, never updates or deletes.

### Transactional Outbox Pattern (All Services)

Every service writes its outbox event in the **same database transaction** as the business record. This eliminates the dual-write problem across all services. The outbox publisher delivers events to Kafka only after they are safely committed to PostgreSQL — downstream systems never miss an event, even across crashes.

### Trade Novation — CCP Interpositioning

When Party A sells to Party B, the CCP novates the trade: Party A now faces the CCP (not Party B), and Party B faces the CCP (not Party A). This is the fundamental mechanism that eliminates bilateral counterparty risk — if Party A defaults, Party B's position is protected by the CCP's margin and default fund, not by Party A's creditworthiness.

### Multilateral Netting — 80-95% Settlement Reduction

Instead of settling every individual trade, the netting engine computes each member's net obligation per instrument across all their trades. A member who bought 100 BTC-PERP in one trade and sold 70 BTC-PERP in another settles only the net 30 BTC-PERP — reducing settlement volume and counterparty exposure.

### 6-Step Default Waterfall — Mutualized Loss Absorption

The default waterfall ensures that losses from a member default are absorbed in a strict priority order: the defaulter's own resources first, then the CCP's equity (skin-in-the-game), then mutualized across surviving members. Each step is recorded as an immutable `waterfall_steps` row with the applied amount.

### Append-Only Immutability Enforcement

Database triggers on `trades`, `novated_trades`, `journal_entries`, and `state_transitions` reject all UPDATE and DELETE operations. Once written, ledger data cannot be modified — corrections require offsetting entries. This mirrors the regulatory requirement for immutable audit trails in clearing systems.

### MPC Threshold Signing — No Single Point of Compromise

On-chain settlement transactions require cryptographic authorization from at least 2 of 3 MPC nodes. A single compromised node cannot produce a valid signature. The signing gateway fans out requests and combines partials once the threshold is met — mirroring Fireblocks and Copper.co institutional custody architecture.

### Idempotency at Every Layer

All POST endpoints are protected by `Idempotency-Key` headers. The gateway passes the header to upstream services, which check the `idempotency_keys` table before processing. Duplicate requests return the cached response. Kafka consumers deduplicate via the `processed_events` table, checking `event_id` before invoking handlers.

### Role-Based Access Control (RBAC)

Five roles enforce separation of duties at the API gateway:

| Role | Permissions |
|------|-------------|
| `admin` | Full access to all endpoints |
| `operator` | POST on trades, margin, collateral, netting; all GET |
| `signer` | POST on signing endpoints; all GET |
| `viewer` | Read-only GET access |
| `system` | POST on prices and margin (automated services); all GET |

### Deterministic Settlement State Machine

Settlement instructions follow a strict state machine:

```
  PENDING ──► APPROVED ──► SIGNED ──► BROADCASTED ──► CONFIRMED
     |            |            |            |
     └────────────┴────────────┴────────────┘
                       FAILED (recoverable → PENDING)
```

Each transition is validated against `VALID_TRANSITIONS`, and invalid transitions raise an error. All transitions are recorded in `state_transitions` with `trace_id` and `actor` context.

### Dead Letter Queue (DLQ)

Failed Kafka messages are retried up to 3 times. After exhausting retries, the message is recorded in the `dead_letter_events` table with the original payload, error message, service name, and retry count. The reconciliation engine monitors DLQ status.

### Decimal Precision for Financial Arithmetic

All monetary values and quantities use Python's `Decimal` type with `DECIMAL(38,18)` database precision rather than floats, preventing IEEE 754 rounding errors from corrupting financial calculations — mandatory in any system handling institutional-scale clearing.

### Network Trust Boundaries

Three isolated Docker networks enforce the principle of least privilege: the DMZ exposes only the API gateway and netting engine, the internal network sandboxes all microservices and databases, and the signing network isolates MPC nodes from everything except the signing gateway and settlement engine.

### Distributed Tracing

Every operation carries a `trace_id` that propagates through Kafka events, database writes, and service-to-service calls. Combined with `actor_id` and `request_id`, this enables full reconstruction of any clearing lifecycle from API entry point to ledger mutation.

---

## Database Schema

### `members`

LEI-identified clearing house participants.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Member identifier |
| `lei` | VARCHAR(20) UNIQUE | ISO 17442 Legal Entity Identifier |
| `name` | VARCHAR | Institution name |
| `status` | ENUM | `pending`, `active`, `suspended`, `defaulted` |
| `credit_limit` | DECIMAL(38,18) | Maximum exposure allowed |

### `instruments`

Tradeable products with blockchain settlement support.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Instrument identifier |
| `symbol` | VARCHAR UNIQUE | Ticker symbol (e.g., `BTC-PERP`, `ETH-FUT-2025Q1`) |
| `asset_class` | ENUM | `crypto_future`, `crypto_option`, `crypto_perpetual`, `tokenized_equity`, `tokenized_bond`, `tokenized_rwa` |
| `settlement_type` | ENUM | `cash`, `physical`, `dvp` |
| `margin_rate_im` | DECIMAL | Initial margin rate (e.g., 0.10 = 10%) |
| `margin_rate_vm` | DECIMAL | Variation margin rate |
| `chain_id` | VARCHAR | Blockchain network identifier |
| `contract_address` | VARCHAR | On-chain smart contract address |

### `accounts`

Six account types per member, each with three pool states.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Account identifier |
| `member_id` | FK → members | Owning clearing member |
| `account_type` | ENUM | `MARGIN_IM`, `MARGIN_VM`, `SETTLEMENT`, `DEFAULT_FUND`, `COLLATERAL`, `CCP_EQUITY` |
| `currency` | VARCHAR | Account currency |
| `pool` | ENUM | `AVAILABLE`, `RESERVED`, `LOCKED` |

### `trades`

Bilateral trades submitted for clearing — **immutable (no UPDATE or DELETE)**.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Trade identifier |
| `external_trade_id` | VARCHAR UNIQUE | External reference |
| `instrument_id` | FK → instruments | Traded instrument |
| `buyer_member_id` | FK → members | Buying party |
| `seller_member_id` | FK → members | Selling party |
| `quantity` | DECIMAL(38,18) | Trade quantity |
| `price` | DECIMAL(38,18) | Trade price |
| `status` | ENUM | `submitted` → `validated` → `novated` / `rejected` |

### `novated_trades`

CCP-facing legs after novation — **immutable (no UPDATE or DELETE)**.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Novated trade identifier |
| `original_trade_id` | FK → trades | Source bilateral trade |
| `member_id` | FK → members | Member facing the CCP |
| `instrument_id` | FK → instruments | Traded instrument |
| `side` | ENUM | `BUY` or `SELL` |
| `quantity` | DECIMAL(38,18) | Trade quantity |
| `price` | DECIMAL(38,18) | Trade price |
| `status` | ENUM | `open`, `netted`, `closed`, `defaulted` |

### `journals`

Journal headers grouping related double-entry pairs.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Journal identifier |
| `journal_type` | ENUM | `TRADE_SETTLEMENT`, `MARGIN_CALL`, `MARGIN_POST`, `MARGIN_RETURN`, `COLLATERAL_DEPOSIT`, `COLLATERAL_WITHDRAWAL`, `DEFAULT_FUND_CONTRIBUTION`, `FEE_COLLECTION`, `NETTING_SETTLEMENT`, `DEFAULT_LOSS` |
| `reference_type` | VARCHAR | Type of referenced entity |
| `reference_id` | UUID | Referenced entity ID |
| `status` | ENUM | `pending`, `confirmed`, `rejected` |

### `journal_entries`

Immutable double-entry ledger — **no UPDATE or DELETE permitted**.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Entry identifier |
| `journal_id` | FK → journals | Parent journal |
| `account_id` | FK → accounts | Affected account |
| `debit` | DECIMAL(38,18) | Debit amount (zero if credit) |
| `credit` | DECIMAL(38,18) | Credit amount (zero if debit) |
| `narrative` | TEXT | Human-readable description |

> CHECK constraint: each row must have exactly one of debit or credit > 0.

### `margin_requirements`

Margin calculations per member per instrument.

| Column | Type | Description |
|--------|------|-------------|
| `member_id` | FK → members | Clearing member |
| `instrument_id` | FK → instruments | Instrument |
| `margin_type` | ENUM | `INITIAL` or `VARIATION` |
| `required_amount` | DECIMAL(38,18) | Calculated margin requirement |
| `posted_amount` | DECIMAL(38,18) | Collateral posted against requirement |
| `shortfall` | DECIMAL(38,18) | required - posted (if positive) |

### `margin_calls`

Margin call lifecycle tracking.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Margin call identifier |
| `member_id` | FK → members | Called member |
| `call_amount` | DECIMAL(38,18) | Amount of margin required |
| `deadline` | TIMESTAMP | Response deadline |
| `status` | ENUM | `issued` → `acknowledged` → `met` / `breached` |

### `netting_cycles`

Netting execution records.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Cycle identifier |
| `cycle_type` | ENUM | `scheduled`, `manual`, `intraday` |
| `status` | ENUM | Cycle state |
| `cut_off_time` | TIMESTAMP | Trade inclusion cutoff |

### `net_obligations`

Computed net positions per netting cycle.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Obligation identifier |
| `netting_cycle_id` | FK → netting_cycles | Parent cycle |
| `member_id` | FK → members | Obligated member |
| `instrument_id` | FK → instruments | Instrument |
| `net_quantity` | DECIMAL(38,18) | Net quantity (positive = deliver, negative = receive) |
| `net_amount` | DECIMAL(38,18) | Net cash amount |

### `settlement_instructions`

Settlement task lifecycle with on-chain support.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Instruction identifier |
| `settlement_type` | ENUM | `cash`, `physical`, `hybrid`, `on_chain` |
| `chain_id` | VARCHAR | Blockchain network (for on-chain) |
| `tx_hash` | VARCHAR | On-chain transaction hash |
| `block_number` | BIGINT | Confirmation block number |
| `status` | ENUM | `pending` → `approved` → `signed` → `broadcasted` → `confirmed` / `failed` |

### `default_events`

Default detection and waterfall execution records.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Default event identifier |
| `member_id` | FK → members | Defaulting member |
| `trigger_reason` | TEXT | What caused the default |
| `total_loss` | DECIMAL(38,18) | Total loss amount |
| `status` | ENUM | `detected` → `margin_seized` → `default_fund_applied` → `ccp_equity_applied` → `mutualized` → `resolved` |

### `waterfall_steps`

Individual loss allocation steps — append-only.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Step identifier |
| `default_event_id` | FK → default_events | Parent default |
| `step_order` | INTEGER | Execution order (1-6) |
| `step_type` | ENUM | `DEFAULTER_MARGIN`, `DEFAULTER_DEFAULT_FUND`, `CCP_SKIN_IN_GAME`, `NON_DEFAULTER_DEFAULT_FUND`, `CCP_ADDITIONAL_EQUITY`, `ASSESSMENT_POWERS` |
| `applied_amount` | DECIMAL(38,18) | Amount applied at this step |

### `price_feeds`

Time-series instrument price data.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Feed identifier |
| `instrument_id` | FK → instruments | Priced instrument |
| `price` | DECIMAL(38,18) | Price in settlement currency |
| `source` | VARCHAR | Price source identifier |
| `received_at` | TIMESTAMP | When the price was received |

### `outbox_events`

Reliable Kafka delivery buffer.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Event identifier |
| `aggregate_type` | VARCHAR | Entity type (trade, settlement, etc.) |
| `event_type` | VARCHAR | Event name (e.g., `trades.novated`) |
| `topic` | VARCHAR | Kafka destination topic |
| `payload` | JSONB | Serialized event data |
| `published_at` | TIMESTAMP | NULL = pending Kafka delivery |

### `dead_letter_events`

Failed message tracking.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | DLQ entry identifier |
| `service_name` | VARCHAR | Service that failed processing |
| `topic` | VARCHAR | Source Kafka topic |
| `payload` | JSONB | Original event payload |
| `error_message` | TEXT | Last error encountered |
| `retry_count` | INTEGER | Number of attempts |

### `state_transitions`

Append-only audit log of every state change.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Transition identifier |
| `entity_type` | VARCHAR | Type of entity (trade, settlement, margin_call, etc.) |
| `entity_id` | UUID | ID of the entity that changed |
| `from_state` | VARCHAR | Previous state |
| `to_state` | VARCHAR | New state |
| `trace_id` | UUID | Distributed trace correlation |
| `actor` | VARCHAR | Who initiated the transition |

### Views

| View | Purpose |
|------|---------|
| `member_positions` | Aggregates novated_trades into long_qty, short_qty, net_qty, avg_price per member per instrument |
| `account_balances` | SUM(debit) - SUM(credit) from confirmed journal entries per account |
| `latest_prices` | Materialized view of the most recent price per instrument |

---

## State Machines

### Trade Status

```
                      ┌──────────────────┐
  POST /trades ──────►│    SUBMITTED     │
                      └────────┬─────────┘
                               │  validation
                               ▼
                      ┌──────────────────┐
                      │    VALIDATED     │
                      └────────┬─────────┘
                               │  novation (split into 2 CCP-facing legs)
                               ▼
                      ┌──────────────────┐        ┌──────────────────┐
                      │    NOVATED       │        │    REJECTED      │
                      └──────────────────┘        └──────────────────┘
                                                     (validation failure)
```

### Novated Trade Status

```
  novation ──► OPEN ──► NETTED ──► CLOSED    (normal lifecycle)
                  │
                  └──► DEFAULTED              (member default)
```

### Margin Call Status

```
  evaluate() ──► ISSUED ──► ACKNOWLEDGED ──► MET       (member posts margin)
                    │
                    └──► BREACHED              (deadline passed → default waterfall)
```

### Settlement Instruction Status

```
  netting ──► PENDING
                 │
                 ├──► APPROVED     (authorization check)
                 │       │
                 │       └──► SIGNED        (MPC 2-of-3 threshold signature)
                 │               │
                 │               └──► BROADCASTED  (submitted to blockchain)
                 │                       │
                 │                       └──► CONFIRMED  (block confirmations met)
                 │
                 └──► FAILED      (any stage — recoverable back to PENDING)
```

### Default Waterfall Status

```
  margin breached ──► DETECTED
                         │
                         ├──► MARGIN_SEIZED          (step 1-2)
                         │       │
                         │       └──► DEFAULT_FUND_APPLIED    (step 2)
                         │               │
                         │               └──► CCP_EQUITY_APPLIED  (step 3)
                         │                       │
                         │                       └──► MUTUALIZED   (step 4-5)
                         │                               │
                         │                               └──► RESOLVED  (step 6)
                         │
                         └──► RESOLVED  (loss fully absorbed at any step)
```

---

## Real-World Example: Full Clearing Lifecycle

The demo script (`run_demo.py`) drives the entire clearing pipeline through the running microservices via HTTP requests.

### Participants (Seeded Members)

| Entity | LEI | Role |
|--------|-----|------|
| Citadel Securities | 549300KX51PROJ3YM742 | Market maker |
| Jane Street Group | 549300APJP3NDSF99R62 | Quantitative trading firm |
| Jump Trading | 549300GXKJ94ASXLM512 | High-frequency trading firm |
| Wintermute Trading | 549300WINT3RMUT30001 | Crypto market maker |
| Galaxy Digital | 549300GALXYDIG1T0001 | Digital asset manager |

### Instruments

| Symbol | Asset Class | Settlement |
|--------|-------------|------------|
| BTC-PERP | Crypto Perpetual | Cash |
| ETH-FUT-2025Q1 | Crypto Future | Physical |
| BTC-OPT-60K-CALL | Crypto Option | Cash |
| AAPL-TOKEN | Tokenized Equity | DvP (on-chain) |
| TBOND-2030-TOKEN | Tokenized Bond | DvP (on-chain) |
| RWA-REALESTATE-001 | Tokenized RWA | DvP (on-chain) |

### Lifecycle Walkthrough

1. **Submit Trades** — 6 trades posted via API gateway spanning all asset classes (BTC perpetuals, ETH futures, BTC options, tokenized equities, tokenized bonds, tokenized RWA)
2. **Novation** — Each bilateral trade split into two CCP-facing legs; initial margin journal entries created
3. **Price Updates** — Price oracle publishes latest prices for all instruments
4. **Margin Calculation** — IM and VM computed for each member's portfolio
5. **Netting Cycle** — Manual netting triggered; net obligations computed per member per instrument (reducing gross obligations by 80-95%)
6. **Settlement** — Net obligations settled via cash journal entries, physical delivery, or MPC-signed on-chain DvP transactions
7. **Reconciliation** — Ledger replayed, balances cross-checked against derived views, dead letter queue inspected

---

## Running in a Sandbox Environment

### Option A: Docker Compose (Recommended)

The fastest way to run the entire system. Docker Compose orchestrates all 17 containers with trust domain network isolation.

**Prerequisites:** Docker and Docker Compose.

```bash
# Clone and start
git clone <repo-url>
cd CCP-PYTHON

# Build and start all services
docker compose up -d
```

This starts:

| Service | Port | Network(s) |
|---------|------|------------|
| `api-gateway` | 8000 (exposed) | dmz, internal |
| `trade-ingestion` | 8001 | internal |
| `outbox-publisher` | 8002 | internal |
| `netting-engine` | 8003/8081 | dmz, internal |
| `margin-engine` | 8004 | internal |
| `collateral-manager` | 8005 | internal |
| `settlement-engine` | 8006 | internal, signing |
| `liquidation-engine` | 8007 | internal |
| `price-oracle` | 8008 | internal |
| `compliance-monitor` | 8009 | internal |
| `signing-gateway` | 8010 | internal, signing |
| `mpc-node-1/2/3` | — | signing |
| `postgres` | 5433 | dmz, internal |
| `kafka` | 9092 | internal |
| `zookeeper` | — | internal |
| `prometheus` | 9090 | dmz |
| `grafana` | 3000 | dmz |

**Run the full demo:**

```bash
python run_demo.py
```

The demo script waits for all services to become healthy, then drives the full clearing lifecycle through the API gateway — trade submission, novation, netting, settlement, and reconciliation.

**Verify health:**

```bash
curl http://localhost:8000/health
```

**View logs:**

```bash
docker compose logs -f                          # All services
docker compose logs -f trade-ingestion          # Single service
docker compose logs -f settlement-engine        # Settlement events
docker compose logs -f liquidation-engine       # Default waterfall
```

**Inspect database:**

```bash
# Connect to PostgreSQL
docker compose exec postgres psql -U readonly_user -d ccp_clearing

# View member positions
SELECT * FROM member_positions;

# View journal entries
SELECT j.journal_type, je.debit, je.credit, je.narrative
FROM journal_entries je JOIN journals j ON j.id = je.journal_id
ORDER BY je.created_at;

# View account balances (derived from ledger)
SELECT * FROM account_balances;

# View latest prices
SELECT * FROM latest_prices;
```

**Tear down:**

```bash
docker compose down        # Stop containers (keep data)
docker compose down -v     # Stop containers AND delete volumes
```

### Option B: Local Development

For running tests directly on your machine without Docker.

#### Prerequisites

- Python 3.13+
- PostgreSQL 16+ (running locally)
- Apache Kafka (optional — stubbed in tests)

#### 1. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e shared/
pip install -e services/api-gateway/
# ... install additional services as needed
```

#### 2. Run Tests

```bash
pytest tests/ -v --tb=short
```

---

## Project Structure

```
CCP-PYTHON/
│
├── docker-compose.yml                # 17-container orchestration with 3 trust domain networks
├── docker-compose.monitoring.yml     # Prometheus + Grafana observability stack
├── Dockerfile.base                   # Base image with ccp-shared library pre-installed
├── Makefile                          # Development & operations commands
├── pyproject.toml                    # Root workspace configuration (ruff, pytest)
├── run_demo.py                       # API-driven demo: trades → novation → netting → settlement
│
├── shared/                           # Common library used by all services
│   ├── pyproject.toml                # ccp-shared package (psycopg, confluent-kafka, pydantic)
│   └── src/ccp_shared/
│       ├── config.py                 # Pydantic-based CCPSettings (DB, Kafka, MPC config)
│       ├── auth.py                   # API key authentication
│       ├── trace.py                  # Distributed tracing (trace_id propagation)
│       ├── enums.py                  # 20+ domain enums (statuses, types, account types)
│       ├── errors.py                 # Domain exceptions (CCPError, NettingError, etc.)
│       ├── idempotency.py            # Idempotency key management
│       ├── db/
│       │   ├── connection.py         # Connection pooling (admin, ledger, readonly users)
│       │   ├── transactions.py       # Transactional helpers
│       │   └── readonly.py           # Read-only query builders
│       ├── kafka/
│       │   ├── producer.py           # KafkaProducer (JSON, routing)
│       │   ├── consumer.py           # KafkaConsumer with DLQ routing
│       │   └── outbox.py             # Transactional outbox insertion
│       ├── models/
│       │   ├── member.py             # Member, MemberStatus
│       │   ├── instrument.py         # Instrument, AssetClass, SettlementType
│       │   ├── trade.py              # Trade, NovatedTrade, MemberPosition
│       │   ├── margin.py             # MarginRequirement, MarginCall
│       │   └── journal.py            # Journal, JournalEntry, AccountBalance
│       ├── chain/
│       │   ├── base.py               # Abstract ChainAdapter
│       │   ├── ethereum.py           # Ethereum implementation
│       │   ├── stubs.py              # Mock for testing
│       │   └── registry.py           # Chain adapter factory
│       └── signing/
│           ├── client.py             # MPC signing request/response
│           └── types.py              # SigningRequest, SigningResponse
│
├── services/                         # Microservices (one directory per service)
│   ├── api-gateway/                  # Internet-facing REST API
│   │   └── src/api_gateway/main.py   # RBAC, routing, health aggregation
│   │
│   ├── trade-ingestion/              # Trade validation & novation
│   │   └── src/trade_ingestion/
│   │       ├── main.py               # FastAPI + Kafka consumer lifespan
│   │       ├── consumer.py           # trades.submitted handler
│   │       └── novation.py           # Novation logic with journal entries
│   │
│   ├── netting-engine/               # Multilateral netting
│   │   └── src/netting_engine/
│   │       ├── main.py               # Trigger endpoint + consumer
│   │       └── netting.py            # Net obligation computation
│   │
│   ├── margin-engine/                # IM/VM calculation & margin calls
│   │   └── src/margin_engine/
│   │       ├── main.py               # Consumer for margin events
│   │       └── calculator.py         # Margin computation logic
│   │
│   ├── collateral-manager/           # Deposit/withdraw/lock/release
│   │   └── src/collateral_manager/
│   │       ├── main.py               # Consumer + endpoints
│   │       └── consumer.py           # Collateral event handler
│   │
│   ├── settlement-engine/            # Cash, physical, on-chain DvP
│   │   └── src/settlement_engine/
│   │       ├── main.py               # FastAPI lifespan + consumer
│   │       ├── consumer.py           # Settlement instruction handler
│   │       └── settler.py            # Settlement execution with signing
│   │
│   ├── liquidation-engine/           # Default waterfall
│   │   └── src/liquidation_engine/
│   │       ├── main.py               # Consumer for default events
│   │       └── waterfall.py          # 6-step waterfall execution
│   │
│   ├── price-oracle/                 # Price feeds
│   │   └── src/price_oracle/main.py  # Price publishing + materialized view refresh
│   │
│   ├── compliance-monitor/           # Regulatory surveillance
│   │   └── src/compliance_monitor/
│   │       ├── main.py               # Kafka consumer
│   │       └── consumer.py           # Rule-based screening
│   │
│   ├── signing-gateway/              # MPC coordinator
│   │   └── src/signing_gateway/main.py  # Fan-out + combine (2-of-3)
│   │
│   ├── mpc-node/                     # Threshold signing node (x3 instances)
│   │   └── src/mpc_node/main.py      # Partial signature generation
│   │
│   ├── outbox-publisher/             # Transactional outbox → Kafka
│   │   └── src/outbox_publisher/main.py  # Advisory locking, at-least-once delivery
│   │
│   └── reconciliation-engine/        # Ledger integrity verification
│       └── src/reconciliation_engine/main.py  # Balance replay + cross-check
│
├── migrations/                       # Alembic database migrations (22 versions)
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       ├── 001_create_roles.py                          # DB roles & permissions
│       ├── 002_create_members.py                        # Clearing members
│       ├── 003_create_instruments.py                    # Tradeable instruments
│       ├── 004_create_accounts_and_ledger.py            # Accounts, journals, entries
│       ├── 005_create_trades_and_positions.py           # Trades, novated trades, positions view
│       ├── 006_create_margin_tables.py                  # Margin requirements & calls
│       ├── 007_create_netting_tables.py                 # Netting cycles & obligations
│       ├── 008_create_settlement_tables.py              # Settlement instructions
│       ├── 009_create_outbox.py                         # Transactional outbox
│       ├── 010_create_state_transitions.py              # Audit trail
│       ├── 011_create_price_feeds.py                    # Price feeds + materialized view
│       ├── 012_create_default_waterfall.py              # Default events & waterfall steps
│       ├── 013_immutability_triggers.py                 # Append-only enforcement
│       ├── 014_balance_validation_triggers.py           # Balance invariant checks
│       ├── 015_derived_balance_views.py                 # account_balances view
│       ├── 016_create_indexes.py                        # Performance indexes
│       ├── 017_create_processed_events.py               # Consumer idempotency
│       ├── 018_add_trace_columns.py                     # Distributed tracing columns
│       ├── 019_create_dead_letter_queue.py              # DLQ table
│       ├── 020_fix_settlement_status_constraint.py      # Constraint fix
│       ├── 021_idempotency_ref_and_state_immutability.py # Idempotency + state guards
│       └── 022_fix_settlement_type_constraint.py        # Constraint fix
│
├── scripts/                          # Operational utilities
│   ├── init-db.sh                    # Run Alembic migrations
│   ├── seed-members.py               # Seed 5 members, 6 instruments, default fund accounts
│   ├── health-check.py               # Verify all services, PostgreSQL, Kafka
│   └── query-topics.py               # Inspect Kafka topic messages
│
├── proto/                            # Event schema definitions
│   └── events/                       # JSON schemas for Kafka event payloads
│
├── monitoring/                       # Observability stack
│   ├── prometheus/
│   │   ├── prometheus.yml            # Metrics scrape targets
│   │   └── alerts.yml                # Alerting rules
│   └── grafana/
│       ├── dashboards/               # Pre-built dashboards (4 JSON files)
│       └── provisioning/             # Auto-provisioned datasources & dashboards
│
├── tests/                            # Test suite
│   ├── unit/
│   │   ├── test_chain_adapter.py     # Blockchain adapter mocking
│   │   ├── test_margin_calculator.py # IM/VM calculation logic
│   │   ├── test_netting.py           # Netting algorithm correctness
│   │   ├── test_novation.py          # Trade novation splitting
│   │   └── test_waterfall.py         # Default waterfall step logic
│   └── integration/
│       ├── test_double_entry.py      # Journal double-entry invariants
│       ├── test_full_lifecycle.py    # Trade → settlement full flow
│       └── test_trade_lifecycle.py   # Individual trade state transitions
│
└── .github/
    └── workflows/
        └── ci.yml                    # CI pipeline (lint, type-check, test)
```

---

## Production Warning

**This project is explicitly NOT suitable for production use.** Central counterparty clearing is among the most regulated, operationally complex, and systemically important activities in global financial markets. CCPs are classified as **Systemically Important Financial Market Infrastructure (SIFMI)** by the FSB. The following critical components are absent or stubbed:

| Missing Component | Risk if Absent |
|-------------------|----------------|
| Real MPC cryptography (GG20 / FROST) | Private keys exposed — single compromise drains settlement accounts |
| CCP license and regulatory approval (CFTC, ESMA, MAS) | Operating an unlicensed CCP is illegal in every major jurisdiction |
| Qualified custodian integration (Fireblocks, Copper.co) | Cannot verify actual asset custody positions |
| Real price oracle integration (Chainlink, Pyth, Bloomberg) | Price manipulation enables margin evasion and collateral theft |
| HSM key management (Thales, AWS CloudHSM) | Signing keys stored in software, not tamper-proof hardware |
| Production-grade auth (OAuth2 / mTLS / JWT) | API keys are not sufficient for production clearing |
| Real AML/KYC provider integration (Chainalysis, Elliptic) | No actual sanctions or member screening |
| Default fund waterfall legal framework | Loss mutualization requires legal agreements with all members |
| SWIFT / FedWire / CLS connectivity | Cannot execute real payment rail settlement |
| Smart contract audit (ERC-1400 / escrow) | Exploitable vulnerabilities in settlement contracts |
| Position and concentration limits | No controls on member exposure size |
| TLS/mTLS encryption between services | Internal traffic unencrypted |
| Comprehensive test suite with mutation testing | Untested edge cases in fund handling |
| Disaster recovery & business continuity | No tested failover for settlement outages |
| Regulatory reporting (EMIR, Dodd-Frank, MiFID II) | Post-trade reporting violations |
| Insurance coverage (crime, E&O, cyber) | No protection against operational losses |
| Kafka cluster (replication factor > 1) | Single broker — no fault tolerance |
| Database replication and failover | Single PostgreSQL instance — no HA |

> Central counterparty clearing at institutional scale requires: a CCP license from relevant regulators (CFTC, ESMA, MAS, FCA), qualified custodian relationships, default fund legal agreements with all clearing members, real-time price oracle infrastructure, HSM-based key management, regulatory reporting pipelines, and legal agreements with all counterparties. **Do not use this code to clear, settle, or manage any real trades, margin, collateral, or settlement obligations.**

---

## License

This project is provided as-is for educational and reference purposes under the MIT License.

---

*Built with ♥️ by [Pavon Dunbar](https://linktr.ee/pavondunbar) — Modeled on LCH, CME Clearing, DTCC, Eurex Clearing, and ICE Clear institutional clearing infrastructure*
