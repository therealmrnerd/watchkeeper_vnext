# DB Benchmarks

`tools/bench_db.py` provides repeatable DB read/write benchmarks for the Brainstem SQLite store.

## Run

```powershell
python tools/bench_db.py --pretty
```

Quick smoke run:

```powershell
python tools/bench_db.py --n-keys 50 --n-events 50 --ops-per-sec 100 --duration 0.5 --pretty
```

## What It Measures

- `bench_state_set(n_keys, change_rate)`: state upsert throughput.
- `bench_event_append(n_events)`: append-only event log throughput.
- `bench_mixed(read_ratio, ops_per_sec, duration)`: mixed read/write workload at target cadence.

## Expected Baselines

These are guidance targets for local development on SSD-backed Windows hosts:

- `state_set`: 1,000+ ops/sec
- `event_append`: 1,500+ ops/sec
- `mixed`: sustain requested target within about 20%

If results are below targets, check disk pressure, antivirus exclusions for `data/`, and WAL mode.
