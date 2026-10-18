"""Fivetran sync simulation and transport-level corruption.

What this layer models:
  * Initial historical sync at each tenant's connector setup date. Mutable records changed before
    setup arrive as ONE row with their state at setup time; their earlier history is lost. Append-only
    rows from before setup all arrive in that initial sync.
  * Incremental syncs every 6 hours afterwards.
  * Late arrival (API lag, re-syncs), retried duplicates, clock skew, soft deletes.
  * The dump is taken the day after the window ends: anything that would have synced later is
    simply not in the lake yet.
Every injected defect is logged with the row key."""
from datetime import datetime, timedelta, timezone
from typing import List

import numpy as np

from . import config as C

UTC = timezone.utc
SYNC_HOURS = 6
DUMP_AT = datetime(C.WINDOW_END.year, C.WINDOW_END.month, C.WINDOW_END.day, tzinfo=UTC) + timedelta(days=1, hours=3)

MUTABLE = {"salesforce.user", "salesforce.account", "salesforce.contact", "salesforce.opportunity",
           "zendesk.organization", "zendesk.ticket", "stripe.customer", "stripe.subscription", "stripe.invoice",
           "product.workspace"}
EVENT_TIME = {"product.event": "event_time"}


EPOCH = datetime(2020, 1, 1, tzinfo=UTC)


def _slot(ts: datetime) -> int:
    return int(np.ceil((ts - EPOCH).total_seconds() / (SYNC_HOURS * 3600)))


def _next_sync(ts: datetime, rng) -> datetime:
    return EPOCH + timedelta(hours=_slot(ts) * SYNC_HOURS, minutes=int(rng.integers(1, 40)), seconds=int(rng.integers(0, 60)))


def sync_table(fq: str, rows: List[dict], tenant: dict, rng, defects: List[dict]) -> List[dict]:
    setup = datetime(tenant["connector_setup"].year, tenant["connector_setup"].month, tenant["connector_setup"].day,
                     6, tzinfo=UTC)
    initial_done = setup + timedelta(hours=float(rng.uniform(1, 20)))
    out = []
    if fq in MUTABLE:
        before, after = {}, []
        for r in rows:
            if r["_changed_at"] < setup:
                cur = before.get(r["_pk"])
                if cur is None or r["_changed_at"] >= cur["_changed_at"]:
                    before[r["_pk"]] = r
            else:
                after.append(r)
        lost = sum(1 for r in rows if r["_changed_at"] < setup) - len(before)
        if lost:
            defects.append(dict(table=fq, key=f"tenant={tenant['key']}", defect="history_lost_before_setup", detail=str(lost)))
        for r in before.values():
            out.append(dict(r, _fivetran_synced=initial_done, _fivetran_deleted=False, _initial=True))
        # a record changed several times between two syncs is only seen in its last state
        last = {}
        for r in after:
            k = (r["_pk"], _slot(r["_changed_at"]))
            if k not in last or r["_changed_at"] >= last[k]["_changed_at"]:
                last[k] = r
        collapsed = len(after) - len(last)
        if collapsed:
            defects.append(dict(table=fq, key=f"tenant={tenant['key']}", defect="versions_collapsed_between_syncs", detail=str(collapsed)))
        rows = list(last.values())
    for r in rows:
        if r["_changed_at"] < setup:
            out.append(dict(r, _fivetran_synced=initial_done, _fivetran_deleted=False, _initial=True))
            continue
        synced = _next_sync(r["_changed_at"], rng)
        x = rng.random()
        key = r.get("_pk") or r.get("event_id") or r.get("message_id")
        if x < C.DEFECTS["very_late_rate"]:
            synced += timedelta(days=int(rng.integers(60, 121)))
            defects.append(dict(table=fq, key=str(key), defect="very_late", detail=""))
        elif x < C.DEFECTS["very_late_rate"] + C.DEFECTS["late_arrival_rate"]:
            synced += timedelta(days=int(rng.integers(1, 31)))
            defects.append(dict(table=fq, key=str(key), defect="late", detail=""))
        out.append(dict(r, _fivetran_synced=synced, _fivetran_deleted=False, _initial=False))

    extra = []
    if fq == "product.event":
        for r in out:
            if rng.random() < C.DEFECTS["clock_skew_rate"]:
                r["event_time"] = r["event_time"] + timedelta(hours=float(rng.uniform(1, 48)))
                defects.append(dict(table=fq, key=r["event_id"], defect="clock_skew", detail=""))
            if not r["_initial"] and rng.random() < C.DEFECTS["duplicate_rate_product"]:
                extra.append(dict(r, _fivetran_synced=r["_fivetran_synced"] + timedelta(hours=SYNC_HOURS * int(rng.integers(1, 5)))))
                defects.append(dict(table=fq, key=r["event_id"], defect="duplicate", detail=""))
    if fq == "gmail.message":
        for r in out:
            if not r["_initial"] and rng.random() < C.DEFECTS["duplicate_rate_gmail"]:
                extra.append(dict(r, _fivetran_synced=r["_fivetran_synced"] + timedelta(hours=SYNC_HOURS)))
                defects.append(dict(table=fq, key=r["message_id"], defect="duplicate", detail=""))
    if fq == "zendesk.ticket":
        latest = {}
        for r in out:
            if latest.get(r["_pk"]) is None or r["_fivetran_synced"] > latest[r["_pk"]]["_fivetran_synced"]:
                latest[r["_pk"]] = r
        for pk, r in latest.items():
            if rng.random() < C.DEFECTS["soft_delete_rate_ticket"]:
                extra.append(dict(r, _fivetran_synced=r["_fivetran_synced"] + timedelta(days=int(rng.integers(1, 20))),
                                  _fivetran_deleted=True))
                defects.append(dict(table=fq, key=str(pk), defect="soft_deleted", detail="spam"))
    out += extra

    for o in C.FEED_OUTAGES:
        if o["tenant"] != tenant["key"] or o["table"] != fq:
            continue
        lo = datetime(o["start"].year, o["start"].month, o["start"].day, tzinfo=UTC)
        hi = datetime(o["end"].year, o["end"].month, o["end"].day, 23, 59, tzinfo=UTC)
        n = 0
        survivors = []
        for r in out:
            if o["kind"] == "lost" and lo <= r["_changed_at"] <= hi:
                n += 1
                continue
            if o["kind"] == "delayed" and lo <= r["_fivetran_synced"] <= hi:
                r["_fivetran_synced"] = hi + timedelta(hours=float(rng.uniform(1, 30)))
                n += 1
            survivors.append(r)
        out = survivors
        defects.append(dict(table=fq, key=f"tenant={tenant['key']}", defect=f"feed_outage_{o['kind']}",
                            detail=f"{o['start']}..{o['end']} rows={n}"))

    kept = []
    for r in out:
        if r["_fivetran_synced"] > DUMP_AT:
            defects.append(dict(table=fq, key=str(r.get("_pk") or r.get("event_id") or r.get("message_id")),
                                defect="not_yet_arrived", detail=r["_fivetran_synced"].isoformat()))
            continue
        kept.append(r)
    return kept


def legacy_formats(fq: str, tenant: dict, rows: List[dict], defects: List[dict]):
    """Northwind's first quarter of Salesforce task syncs came through an old export: dates as dd/mm/yyyy
    strings. Whole files are affected (every row synced before 2024), so each file has one type."""
    if fq == "salesforce.task" and tenant["key"] == "northwind":
        cutoff = datetime(2024, 1, 1, tzinfo=UTC)
        n = 0
        for r in rows:
            if r["_fivetran_synced"] < cutoff:
                r["activity_date"] = r["activity_date"].strftime("%d/%m/%Y")
                n += 1
        if n:
            defects.append(dict(table=fq, key="tenant=northwind", defect="legacy_date_format", detail=f"{n} rows dd/mm/yyyy"))
