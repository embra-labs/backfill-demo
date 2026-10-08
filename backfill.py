"""Readable batch executor. The negative-control flags deliberately break it."""
import argparse
import json
import sys

from db import connect

BATCH_SIZE = 100


def event(kind, **fields):
    print(json.dumps(dict(event=kind, **fields)), flush=True)


def boundary(point, batch):
    # Diagnostic synchronization is NOT a batch ACK. Parent SIGKILLs this process.
    event("boundary", point=point, batch=batch)
    if sys.stdin.readline() != "continue\n":
        raise RuntimeError("Boundary hook closed without parent action")


def run(schema, crash=None, mutation=None):
    with connect(schema) as conn:
        first = True
        while True:
            with conn.transaction():
                last, target = conn.execute(
                    "SELECT last_id, target_hi FROM checkpoint WHERE singleton FOR UPDATE"
                ).fetchone()
                if mutation == "replay" and first:
                    last = 0  # WRONG: lost client ACK does not mean DB failed to commit.
                first = False
                if last >= target:
                    break
                end = min(last + BATCH_SIZE, target)
                batch = end // BATCH_SIZE
                if mutation == "early-checkpoint" and batch == 3:
                    # WRONG: another transaction advances progress before data commits.
                    # The row lock above belongs to this transaction; release it first.
                    conn.execute("UPDATE checkpoint SET last_id = %s", (end,))
                else:
                    affected = conn.execute(
                        "UPDATE orders SET label = id::text, backfill_count = backfill_count + 1 "
                        "WHERE id > %s AND id <= %s", (last, end)
                    ).rowcount
                    conn.execute("INSERT INTO batches VALUES (%s, %s, %s) "
                                 "ON CONFLICT (start_id) DO UPDATE SET "
                                 "affected = batches.affected + EXCLUDED.affected", (last, end, affected))
                    conn.execute("UPDATE checkpoint SET last_id = %s", (end,))
                    if crash == "before-commit" and batch == 3:
                        boundary(crash, batch)
            # The transaction context has COMMITted here.
            if mutation == "early-checkpoint" and batch == 3:
                with conn.transaction():
                    conn.execute("UPDATE orders SET label = id::text, "
                                 "backfill_count = backfill_count + 1 WHERE id > %s AND id <= %s",
                                 (last, end))
                    boundary("early-checkpoint", batch)
            if crash == "after-commit" and batch == 3:
                boundary(crash, batch)
            event("batch_ack", batch=batch, last_id=end)
        event("done")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("schema")
    p.add_argument("--crash", choices=["before-commit", "after-commit"])
    p.add_argument("--mutation", choices=["early-checkpoint", "replay"])
    a = p.parse_args()
    run(a.schema, a.crash, a.mutation)
