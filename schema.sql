CREATE TABLE orders (
    id bigint PRIMARY KEY,
    amount bigint NOT NULL DEFAULT 0,
    label text,
    backfill_count integer NOT NULL DEFAULT 0
);
INSERT INTO orders (id) SELECT generate_series(1, 1000);
CREATE TABLE checkpoint (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    last_id bigint NOT NULL,
    target_hi bigint NOT NULL
);
INSERT INTO checkpoint VALUES (true, 0, 1000);
CREATE TABLE batches (
    start_id bigint PRIMARY KEY,
    end_id bigint NOT NULL,
    affected integer NOT NULL
);
