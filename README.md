# CCP Clearing House

A central counterparty clearing house built as an event-driven microservice system in Python.

## Architecture

14 containerized services communicating via Kafka events and HTTP APIs, deployed with Docker Compose across three isolated networks:

- **dmz** -- external-facing (API gateway, netting engine, Postgres)
- **internal** -- all business logic services, Kafka, Zookeeper
- **signing** -- isolated MPC threshold signing cluster (3 nodes)

### Services

| Service | Port | Description |
|---|---|---|
| api-gateway | 8000 | REST API for trade submission, queries, reconciliation |
| trade-ingestion | 8001 | Kafka consumer for trade novation |
| outbox-publisher | 8002 | Polls outbox table, publishes events to Kafka |
| netting-engine | 8003 | Multilateral netting cycle execution |
| margin-engine | 8004 | Initial and variation margin calculation |
| collateral-manager | 8005 | Deposit/withdrawal and collateral tracking |
| settlement-engine | 8006 | Cash and DVP settlement state machine |
| liquidation-engine | 8007 | Default waterfall execution |
| price-oracle | 8008 | Price feed ingestion |
| compliance-monitor | 8009 | Regulatory compliance checks |
| signing-gateway | 8010 | MPC signing coordinator (2-of-3 threshold) |
| mpc-node-1/2/3 | 8020 | Individual MPC key share holders |
| reconciliation-engine | -- | Ledger replay and balance verification |

### Key Properties

- **Append-only double-entry ledger** -- immutable journals enforced by database triggers; balances derived from entries, never stored independently
- **Transactional outbox pattern** -- events persisted atomically with business writes, then published to Kafka asynchronously
- **Idempotency** -- consumer-side deduplication via `processed_events` table; API-side via `Idempotency-Key` header
- **Dead letter queue** -- failed messages routed to `dead_letter_events` table with error context
- **RBAC** -- five application roles (Admin, Operator, System, Signer, Viewer) with separated permissions
- **Deterministic settlement state machine** -- PENDING -> APPROVED -> SIGNED -> BROADCASTED -> CONFIRMED
- **MPC threshold signing** -- 2-of-3 quorum with simulated key shares (demo-appropriate)
- **Reconciliation** -- replays ledger, recomputes balances, compares against derived views, alerts on mismatch

## Running

```bash
docker compose up -d
python run_demo.py
```

The demo script waits for all services to become healthy, then drives the full clearing lifecycle through the API gateway.

## Changes from Initial Deployment

### Environment configuration

- Removed `.env.example` and all `env_file: .env` references from docker-compose.yml
- Hardcoded credentials directly in docker-compose.yml `x-common-env` anchor for zero-setup startup
- Removed `.env` file loading from `CCPSettings` pydantic model (`shared/src/ccp_shared/config.py`)
- Updated default role names (`admin_user`, `ledger_user`, `readonly_user`) and passwords to match docker-compose values

### Docker Compose

- Added `seed-data` init service that runs `scripts/seed-members.py` automatically after database initialization
- Fixed per-service health checks -- each service now specifies its own port instead of sharing a generic check
- Added `postgres` to the `dmz` network; changed external port from 5432 to 5433
- Added `netting-engine` to the `dmz` network with external port 8081
- Added `SIGNING_GATEWAY_HOST: signing-gateway` to common environment

### Domain model alignment

- **Instruments** (`migrations/versions/003_create_instruments.py`): changed asset classes from traditional (`equity`, `fixed_income`, `commodity`, `fx`, `crypto`, `derivative`) to blockchain-native (`crypto_future`, `crypto_option`, `crypto_perpetual`, `tokenized_equity`, `tokenized_bond`, `tokenized_rwa`); changed settlement type `hybrid` to `dvp`
- **Accounts** (`migrations/versions/004_create_accounts_and_ledger.py`): changed account types from `MARGIN`, `FEE`, `CCP_SKIN_IN_GAME` to `MARGIN_IM`, `MARGIN_VM`, `CCP_EQUITY`; added `DEFAULT_FUND_CONTRIBUTION` journal type
- **Netting** (`migrations/versions/007_create_netting_tables.py`): changed cycle type `ad_hoc` to `manual` and `intraday`

### Bug fixes

- **seed-members.py**: fixed `conn.fetchone()` to `cur.fetchone()` (psycopg3 returns cursors from `execute()`, not connections)
- **settlement consumer** (`services/settlement-engine/src/settlement_engine/consumer.py`): fixed `SigningClient` initialization to accept settings object; added missing `conn.commit()` after settlement execution
- **settlement settler** (`services/settlement-engine/src/settlement_engine/settler.py`): added zero-amount guard for cash settlement journal entries; fixed MPC signing response handling (base64 decode); updated DVP instruction field names to match shared types
- **trade novation** (`services/trade-ingestion/src/trade_ingestion/novation.py`): changed margin account lookup from `MARGIN` to `MARGIN_IM` to match updated schema

### Service improvements

- **Netting engine** (`services/netting-engine/src/netting_engine/netting.py`): CCP member ID now looked up dynamically from the `members` table by LEI instead of a hardcoded UUID; trade status after netting changed from `closed` to `netted`
- **Settlement engine main** (`services/settlement-engine/src/settlement_engine/main.py`): migrated from deprecated `@app.on_event("startup")` to FastAPI `lifespan` context manager; added logging initialization
- **MPC config** (`shared/src/ccp_shared/config.py`): changed defaults from 3-of-5 to 2-of-3 threshold to match the three MPC nodes defined in docker-compose

### Demo script

- Rewrote `run_demo.py` from an in-memory simulation to an API-driven demo that exercises the real microservice pipeline via HTTP requests to the running services
