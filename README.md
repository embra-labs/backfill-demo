# Backfill checkpoints across process crashes

[![Demo checks](https://github.com/embra-labs/backfill-demo/actions/workflows/demo.yml/badge.svg)](https://github.com/embra-labs/backfill-demo/actions/workflows/demo.yml)

A small, runnable PostgreSQL example: update a batch and its checkpoint in **one transaction**, kill the executor on either side of commit, then resume from database state.

The verifier checks every row. Two deliberately broken variants show it detecting skipped and repeated work.

Companion to Embra's engineering article: [Backfill 8 triệu dòng: dữ liệu đúng, nhưng latency không đạt](https://embra.cloud/engineering/backfill-8m/) (Vietnamese). **This is a new 1,000-row teaching fixture, not a reproduction of that eight-million-row benchmark or Embra's production executor.**

Built as part of [Embra](https://embra.cloud/), app and PostgreSQL hosting in development for developers and small teams in Vietnam. [Meet the builder and see the product direction](https://embra.cloud/#nguoi-lam). You can run this example independently of the unreleased product.

## Run it

Requirements: Docker with Compose v2 or newer, Bash, and a Linux/macOS host (Windows: WSL2). The first run downloads PostgreSQL, Python, and the pinned Python dependency.

```bash
git clone https://github.com/embra-labs/backfill-demo.git
cd backfill-demo
./demo.sh
```

The script builds a runner, starts a private PostgreSQL container, runs five scenarios, and returns nonzero on any unexpected result. It publishes no host ports and removes only its own uniquely named Compose project's containers and volume on exit. The fixed database password is for this isolated fixture only.

Expected final line:

```text
PASS: 3 valid scenarios; 2 deliberately broken variants detected.
```

Every scenario prints a JSON result. The application transaction count varies with scheduling; correctness checks and checkpoint boundaries do not. See [a recorded local run](results/local.jsonl) and the [CI runs](https://github.com/embra-labs/backfill-demo/actions).

## What happens

Seed 1,000 orders with an empty `label` and `backfill_count = 0`. The backfill sets `label = id::text`, increments the counter, and advances the checkpoint in batches of 100.

At the same time, [app.py](app.py) reads orders, increments their amounts, and inserts new rows. It keeps an independent in-memory ledger **after each transaction commits**. New inserts populate the new field themselves and have IDs above the backfill's fixed watermark. This is an application workload, not an HTTP server.

```text
BEGIN
  lock checkpoint row
  read last_id and target_hi
  update orders in (last_id, next_id]
  record affected rows in batch audit
  advance checkpoint to next_id
COMMIT
send batch ACK
```

The parent process sends **SIGKILL** after receiving a diagnostic boundary event from the worker. That event is not a batch ACK. The worker blocks at the hook until killed, so the test does not depend on guessing a sleep duration. PostgreSQL stays running.

| Scenario | Checkpoint after kill | Seed rows transformed after kill | Final expectation |
| :--- | ---: | ---: | :--- |
| Uninterrupted | — | — | Every seed row transformed once |
| Kill before committing batch 3 | 200 | 200 | Resume; every seed row transformed once |
| Kill after batch 3 commit, before its ACK | 300 | 300 | Resume from 300; no repeated batch |
| **Broken:** commit checkpoint before data | 300 | 200 | Verifier rejects 100 skipped rows |
| **Broken:** ignore checkpoint after lost ACK | 300 | 300 | Verifier rejects 300 repeated rows |

Both negative controls run on fresh disposable schemas. The last variant deliberately restarts at zero and records duplicate batch effects in the audit. A successful overall run means **the bad variants were rejected**, not that those migrations passed.

## What is verified

[run.py](run.py) checks:

- Exact seed IDs and application insert IDs, not just a row count.
- Every row's label and the number of times backfill touched each seed row.
- Application update totals against its client-side ACK ledger.
- All ten batch ranges, affected-row counts, and final checkpoint.
- The actual checkpoint/data state at each kill boundary.
- SIGKILL exit status and absence of batch 3's ACK in the interrupted attempt.
- Application commits while the executor interval is active.

The transformation depends only on immutable IDs, while the application changes a different column. There are no deletes or ID changes. This fixture does not solve migration of arbitrarily changing data.

## Read the code

| File | Responsibility |
| :--- | :--- |
| [schema.sql](schema.sql) | Fixture, fixed watermark, checkpoint and batch audit |
| [backfill.py](backfill.py) | Transaction boundary, crash hooks, intentionally broken variants |
| [app.py](app.py) | Concurrent application writes and client-side ACK ledger |
| [run.py](run.py) | Orchestration, kill/resume, independent verification |
| [demo.sh](demo.sh) | One-command execution and isolated cleanup |
| [.github/workflows/demo.yml](.github/workflows/demo.yml) | Same command in CI |

The code uses explicit transaction contexts on an autocommit connection. See [PostgreSQL transactions](https://www.postgresql.org/docs/16/tutorial-transactions.html) and [Psycopg transaction management](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

## Limits

This demonstrates one transactional mechanism under **executor process failure**. It does not test database/host power loss, replication/failover, nontransactional side effects, approval security, or multiple executors. The app process stays alive, so its ACK ledger is not a crash-durable external log.

There is no latency target, throttling policy, throughput claim, or SLA. `backfill_count` and the batch audit are teaching instrumentation, not a general exactly-once guarantee. Database settings and version are printed at startup. Python dependencies are pinned; container tags track Python 3.12 and PostgreSQL 16 updates, so this is not a bit-for-bit environment snapshot.

## Changes and questions

Run `./demo.sh` before submitting a change. A new failure case should include an assertion that would fail if the mechanism were broken. Report demo issues [here](https://github.com/embra-labs/backfill-demo/issues); keep private application data and credentials out of reports.

[Embra Engineering](https://embra.cloud/engineering/) · [Embra's current scope](https://embra.cloud/#trang-thai) · [MIT license](LICENSE)
