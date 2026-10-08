"""Small application workload: read, increment an order, insert a new order."""
import threading

from db import connect


class App(threading.Thread):
    def __init__(self, schema):
        super().__init__(daemon=True)
        self.schema = schema
        self.stop_requested = threading.Event()
        self.ready = threading.Event()
        self.acks = []  # Independent client-side ledger, appended only AFTER commit.
        self.error = None

    def run(self):
        try:
            with connect(self.schema) as conn:
                n = 0
                while not self.stop_requested.is_set():
                    n += 1
                    updated_id = (n * 37) % 1000 + 1
                    inserted_id = 1000 + n
                    with conn.transaction():
                        assert conn.execute("SELECT id FROM orders WHERE id = %s", (updated_id,)).fetchone()
                        conn.execute("UPDATE orders SET amount = amount + 1 WHERE id = %s", (updated_id,))
                        # New writer populates the new field; inserted rows are outside watermark.
                        conn.execute("INSERT INTO orders (id, label) VALUES (%s, %s)",
                                     (inserted_id, str(inserted_id)))
                    self.acks.append((updated_id, inserted_id))
                    self.ready.set()
                    self.stop_requested.wait(.002)
        except BaseException as error:
            self.error = error
            self.ready.set()

    def stop(self):
        self.stop_requested.set()
        self.join(15)
        if self.is_alive():
            raise RuntimeError("Application did not stop")
        if self.error:
            raise self.error
