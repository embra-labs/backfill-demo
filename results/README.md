# Recorded run

Run on 2026-10-08 using `./demo.sh`, Linux x86_64, Docker Compose v5.5.1, PostgreSQL 16.15, Python 3.12 container and psycopg 3.2.10. Exit code: 0.

`local.jsonl` contains only the six JSON records emitted by the runner (database settings + five scenario results), extracted from Compose output. Build and container logs are omitted. All data is synthetic.

Application transaction counts depend on scheduling. Do not use these counts as a throughput benchmark. Negative-control `passed: false` values are expected and asserted by the runner. CI runs the same command and retains the full execution log for 14 days.
