"""Benchmark harness — two experiments.

1. Classic comparison: one workload under FCFS / SJF / Priority / Round Robin.
2. Fairness comparison: a multi-user scenario (a FREE 'spammer' flooding the
   queue, a quiet FREE user, and a PREMIUM user) under FCFS vs FairShare vs WFQ,
   showing average waiting time per user and per tier.

Usage:  python benchmark.py
"""
from __future__ import annotations

import config
from wms.database import Database
from wms.engine import Engine
from wms.schedulers import build
from wms.users import Users, Tier

# Classic single-user workload — (request, priority, burst_ms).
CLASSIC = [
    ("a relaxing study playlist", 5, 500),
    ("high energy workout mix",   3, 800),
    ("sad indie acoustic songs",  5, 300),
    ("party dance hits",          1, 600),
    ("focus coding lo-fi beats",  4, 400),
    ("calm ambient sleep sounds", 2, 200),
]


def run_scenario(db, weight_fn, scheduler_name, submissions):
    scheduler = build(scheduler_name, config.RR_QUANTUM_MS, weight_fn)
    engine = Engine(db, scheduler, num_workers=1)
    for user, text, priority, burst in submissions:
        engine.submit(user["name"], text, priority=priority, burst_ms=burst,
                      user_id=user["user_id"], tier=user["tier"])
    engine.start()
    if not engine.wait_idle(timeout=180):
        print(f"  [warn] {scheduler_name} timed out")
    engine.stop()


def classic_comparison(db, users, weight_fn):
    print("\n### Experiment 1 - classic scheduling (single user)")
    db.clear_executions()
    bench = users.get_or_create("bench_user", Tier.FREE)
    subs = [(bench, t, p, b) for (t, p, b) in CLASSIC]
    for name in ["FCFS", "SJF", "Priority", "RoundRobin"]:
        print(f"  running {name} ...")
        run_scenario(db, weight_fn, name, subs)

    rows = {r["scheduler"]: r for r in db.analytics()}
    print(f"\n  {'Scheduler':<12}{'Avg Waiting':>14}{'Avg Turnaround':>16}{'Avg Response':>15}")
    print("  " + "-" * 55)
    for name in ["FCFS", "SJF", "Priority", "RoundRobin"]:
        r = rows.get(name)
        if r:
            print(f"  {name:<12}{r['avg_waiting']:>12.1f}ms{r['avg_turnaround']:>14.1f}ms"
                  f"{r['avg_response']:>13.1f}ms")


def fairness_comparison(db, users, weight_fn):
    print("\n### Experiment 2 - fairness (multi-user, shared API budget)")
    db.clear_executions()
    spammer = users.get_or_create("spammer_sam", Tier.FREE)
    quiet = users.get_or_create("quiet_qi", Tier.FREE)
    vip = users.get_or_create("premium_pat", Tier.PREMIUM)

    subs = []
    for i in range(10):
        subs.append((spammer, f"party dance hits {i}", 5, 400))
    for i in range(2):
        subs.append((quiet, "calm ambient sleep sounds", 5, 400))
        subs.append((vip, "high energy workout mix", 5, 400))

    for name in ["FCFS", "FairShare", "WFQ"]:
        print(f"  running {name} ...")
        run_scenario(db, weight_fn, name, subs)

    print("\n  Average waiting time per user (lower = served sooner):")
    print(f"  {'Scheduler':<12}{'User':<16}{'Tier':<9}{'Jobs':>5}{'Avg Waiting':>14}")
    print("  " + "-" * 56)
    for r in db.analytics_by_user():
        print(f"  {r['scheduler']:<12}{r['name']:<16}{r['tier']:<9}"
              f"{int(r['n']):>5}{r['avg_waiting']:>12.1f}ms")

    print("\n  Average waiting time per tier:")
    print(f"  {'Scheduler':<12}{'Tier':<9}{'Jobs':>5}{'Avg Waiting':>14}")
    print("  " + "-" * 41)
    for r in db.analytics_by_tier():
        print(f"  {r['scheduler']:<12}{r['tier']:<9}{int(r['n']):>5}{r['avg_waiting']:>12.1f}ms")


def main():
    db = Database()
    db.init_schema()
    from wms import models
    models.seed_job_ids(db.max_job_id() + 1)
    users = Users(db)
    weight_fn = users.weight_of

    print(f"DB backend: {config.DB_BACKEND} | workers: 1 | "
          f"RR/WFQ quantum: {config.RR_QUANTUM_MS} ms | "
          f"PREMIUM weight: {__import__('wms.users', fromlist=['TIER_WEIGHT']).TIER_WEIGHT['PREMIUM']}x")

    classic_comparison(db, users, weight_fn)
    fairness_comparison(db, users, weight_fn)

    print("\nDone. Open the web dashboard (/analytics) to see the fairness tables.")


if __name__ == "__main__":
    main()
