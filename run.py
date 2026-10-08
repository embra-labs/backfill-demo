"""Run healthy/crash scenarios and demonstrate that broken variants are rejected."""
from collections import Counter
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
import uuid

from psycopg import sql

from app import App
from db import connect


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def execute(schema, crash=None, mutation=None):
    args = [sys.executable, "-u", "backfill.py", schema]
    if crash:
        args += ["--crash", crash]
    if mutation:
        args += ["--mutation", mutation]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, bufsize=0)
    events = []
    killed = False
    # Read a line with an overall bound. Each worker event is short and flushed.
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 40
            pending = b""
            while True:
                require(time.monotonic() < deadline, "Executor timed out")
                if not selector.select(timeout=1):
                    continue
                chunk = os.read(p.stdout.fileno(), 4096)
                if not chunk:
                    require(not pending, "Incomplete executor event")
                    break
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        raise RuntimeError("Executor error: " + line.decode(errors="replace"))
                    events.append(e)
                    if e["event"] == "boundary":
                        p.kill()  # SIGKILL, not a graceful rollback/exception.
                        killed = True
            code = p.wait(timeout=5)
        expected_kill = bool(crash or mutation == "early-checkpoint")
        require(killed == expected_kill, "Requested boundary was not reached")
        require(code == (-signal.SIGKILL if killed else 0), f"Unexpected worker exit {code}")
        if killed:
            require(not any(e["event"] == "batch_ack" and e["batch"] == 3 for e in events),
                    "Batch 3 unexpectedly acknowledged")
        return events
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)
        p.stdin.close()
        p.stdout.close()


def inspect_boundary(schema, expected_last):
    with connect(schema) as conn, conn.transaction():
        # Wait for killed backend's transaction to release the checkpoint lock.
        last = conn.execute("SELECT last_id FROM checkpoint FOR UPDATE").fetchone()[0]
        count = conn.execute("SELECT count(*) FROM orders WHERE id <= 1000 AND backfill_count = 1").fetchone()[0]
        require(last == expected_last, f"Checkpoint: {last}, expected {expected_last}")
        return dict(last_id=last, transformed_seed_rows=count)


def verify(schema, acks):
    expected_updates = Counter(x[0] for x in acks)
    inserted = {x[1] for x in acks}
    with connect(schema) as conn:
        rows = conn.execute("SELECT id, amount, label, backfill_count FROM orders ORDER BY id").fetchall()
        last, target = conn.execute("SELECT last_id, target_hi FROM checkpoint").fetchone()
        batches = conn.execute("SELECT start_id, end_id, affected FROM batches ORDER BY start_id").fetchall()
    seeded = {r[0] for r in rows if r[0] <= 1000}
    new_ids = {r[0] for r in rows if r[0] > 1000}
    bad_labels = sum(label != str(i) for i, _, label, _ in rows)
    bad_counts = sum(count != (1 if i <= 1000 else 0) for i, _, _, count in rows)
    bad_updates = sum(amount != expected_updates[i] for i, amount, _, _ in rows)
    valid_batches = batches == [(i, i + 100, 100) for i in range(0, 1000, 100)]
    result = dict(rows=len(rows), acknowledged_app_transactions=len(acks),
                  missing_seed_rows=len(set(range(1, 1001)) - seeded),
                  missing_app_inserts=len(inserted - new_ids), unexpected_app_inserts=len(new_ids - inserted),
                  bad_labels=bad_labels, bad_backfill_counts=bad_counts, bad_app_updates=bad_updates,
                  batch_audit_passed=valid_batches, checkpoint=last)
    result["passed"] = (bool(acks) and seeded == set(range(1, 1001)) and new_ids == inserted
                        and not (bad_labels or bad_counts or bad_updates)
                        and valid_batches and last == target == 1000)
    return result


def scenario(name, crash=None, mutation=None):
    schema = "demo_" + uuid.uuid4().hex
    with connect(schema) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(Path("schema.sql").read_text())
    app = App(schema)
    app.start()
    try:
        require(app.ready.wait(10) and not app.error, "Application did not start")
        before = len(app.acks)
        boundary = None
        if mutation == "replay":
            execute(schema, crash="after-commit")
            boundary = inspect_boundary(schema, 300)
            require(boundary["transformed_seed_rows"] == 300, "Committed batch not present")
            execute(schema, mutation="replay")
        else:
            execute(schema, crash=crash, mutation=mutation)
            if crash or mutation:
                expected = 200 if crash == "before-commit" else 300
                boundary = inspect_boundary(schema, expected)
                wanted_rows = 200 if crash == "before-commit" or mutation == "early-checkpoint" else 300
                require(boundary["transformed_seed_rows"] == wanted_rows, "Unexpected commit boundary")
                execute(schema)
        app.stop()
        require(len(app.acks) > before, "No application commits during executor interval")
        result = verify(schema, app.acks)
        if mutation == "early-checkpoint":
            require(not result["passed"] and result["bad_labels"] == 100
                    and result["bad_backfill_counts"] == 100 and not result["batch_audit_passed"],
                    "Verifier failed to detect skipped batch")
        elif mutation == "replay":
            require(not result["passed"] and result["bad_backfill_counts"] == 300
                    and not result["batch_audit_passed"], "Verifier failed to detect replay")
        else:
            require(result["passed"], f"Integrity failure: {result}")
        # Even intentionally broken backfills must preserve acknowledged app writes.
        require(result["missing_app_inserts"] == result["unexpected_app_inserts"] == result["bad_app_updates"] == 0,
                "App writes did not reconcile")
        print(json.dumps(dict(scenario=name, expected_outcome="rejected" if mutation else "passed",
                              boundary=boundary, verification=result)), flush=True)
    finally:
        if app.is_alive():
            app.stop()
        with connect(schema) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


if __name__ == "__main__":
    with connect("demo_version") as conn:
        print(json.dumps(dict(postgres=conn.execute("SELECT version()").fetchone()[0],
                              fsync=conn.execute("SHOW fsync").fetchone()[0],
                              synchronous_commit=conn.execute("SHOW synchronous_commit").fetchone()[0])), flush=True)
    scenario("uninterrupted")
    scenario("kill_before_commit", crash="before-commit")
    scenario("kill_after_commit_before_ack", crash="after-commit")
    scenario("negative_early_checkpoint", mutation="early-checkpoint")
    scenario("negative_replay_committed_batch", mutation="replay")
    print("PASS: 3 valid scenarios; 2 deliberately broken variants detected.", flush=True)
