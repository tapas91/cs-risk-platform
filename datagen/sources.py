"""Source emitters: what each system would have recorded about the hidden world.

Each emitter returns {table: [row, ...]}. Every row carries two private fields used by the sync
layer and dropped before writing:
  _pk          primary key (mutable tables keep one row per version)
  _changed_at  when the change happened in the source system (UTC)
Rows are "clean" here apart from defects that only make sense with world knowledge (identity gaps,
duplicates in SFDC/Stripe, missing values typed in by people); those are logged to the defect log."""
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
import hashlib
import json

import numpy as np

from . import config as C
from . import corpus as T
from . import names as N
from .world import World, Account, rand_date, pick, DAY

UTC = timezone.utc


def tz_hours(tz: str) -> float:
    sign = -1 if tz.startswith("-") else 1
    h, m = tz[1:].split(":")
    return sign * (int(h) + int(m) / 60)


class Ctx:
    def __init__(self, world: World):
        self.w = world
        self.rng = world.rng
        self.ids = world.ids
        self.defects: List[dict] = []
        self.text_truth: List[dict] = []
        self.contacts: Dict[int, List[dict]] = {}
        self.agents: Dict[str, List[dict]] = {}
        self.org_id: Dict[int, Optional[int]] = {}
        self.workspaces: Dict[int, List[dict]] = {}
        self.identity_truth: List[dict] = []  # which account each Stripe/Zendesk/product record really belongs to

    def identity(self, a, source_system: str, source_id):
        self.identity_truth.append(dict(tenant=a.tenant, source_system=source_system, source_id=str(source_id),
                                        account_id=a.account_id))

    def defect(self, table, key, kind, detail=""):
        self.defects.append(dict(table=table, key=str(key), defect=kind, detail=detail))

    def when(self, d: date, tz: str, business: bool = True) -> datetime:
        """A plausible local time on day d, returned in UTC."""
        if business:
            hour = float(np.clip(self.rng.normal(12.5, 2.6), 6, 22))
        else:
            hour = float(self.rng.uniform(0, 24))
        local = datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(hours=hour, seconds=int(self.rng.integers(0, 60)))
        return local - timedelta(hours=tz_hours(tz))

    def poisson(self, intensity: np.ndarray, target: float) -> np.ndarray:
        total = intensity.sum()
        if total <= 0:
            return np.zeros_like(intensity, dtype=int)
        return self.rng.poisson(intensity * (target / total))

    def tenant(self, a: Account) -> dict:
        return self.w.tenants[a.tenant]

    def fill(self, text: str, a: Account, first: str = "", agent: str = "") -> str:
        t = self.tenant(a)
        r = self.rng
        return text.format(product=t["product"], feature=str(r.choice(t["features"])),
                           integration=str(r.choice(t["integrations"])), company=a.name, first=first or "there",
                           agent=agent or "team", n=int(r.integers(3, 60)), days=int(r.integers(4, 30)),
                           q=1, year=C.WINDOW_END.year, fix=str(r.choice(T.FIXES)))


def name_variant(rng, name: str) -> str:
    """How another system might spell the same company."""
    parts = name.replace(",", "").split()
    legal = {"Inc.", "Inc", "LLC", "Corp.", "Ltd", "Limited", "Ltd.", "plc", "GmbH", "AG", "B.V.", "KG", "&", "Co."}
    core = " ".join(p for p in parts if p not in legal)
    choice = rng.integers(0, 6)
    if choice == 0:
        return name
    if choice == 1:
        return core
    if choice == 2:
        return core.upper()
    if choice == 3:
        return core + ", Inc." if "Inc" not in name else core + " Incorporated"
    if choice == 4:
        return core.replace(" ", "")
    return core + " (" + parts[-1] + ")" if len(parts) > 2 else core


# ---------------------------------------------------------------- people

def build_people(ctx: Ctx):
    rng, w = ctx.rng, ctx.w
    for t in C.TENANTS:
        ctx.agents[t["key"]] = [dict(id=int(ctx.ids.seq("zd_agent" + t["key"], 360000000)), first=str(rng.choice(
            ["Maya", "Leo", "Grace", "Tom", "Aditi", "Ruben", "Sara", "Jonas", "Mei", "Kwame"])))
            for _ in range(max(2, round(8 * w.scale)))]
    for a in w.accounts:
        t = ctx.tenant(a)
        if a.lifecycle == "prospect":
            roles = ["champion"] + ["end_user"] * int(rng.integers(0, 3))
        else:
            k = {"smb": (1, 3), "mid": (2, 5), "enterprise": (4, 9)}[a.tier]
            roles = ["champion", "economic_buyer"] + (["admin"] if a.tier != "smb" else []) + ["end_user"] * int(rng.integers(*k))
        if a.is_test:
            roles = ["admin"]
        contacts = []
        base = a.created_date if a.lifecycle == "prospect" else min(a.created_date, a.contract_start)
        for role in roles:
            first, last = str(rng.choice(N.FIRST_NAMES)), str(rng.choice(N.LAST_NAMES))
            local = f"{first}.{last}".lower().replace("'", "")
            domain = a.domain
            if a.personal_domain:
                domain = str(rng.choice(N.PERSONAL_DOMAINS))
                local = f"{first}{last}{int(rng.integers(1, 99))}".lower().replace("'", "")
            contacts.append(dict(id=ctx.ids.sfdc("003", t["code"]), first=first, last=last, email=f"{local}@{domain}",
                                 role=role, title=str(rng.choice(N.CONTACT_TITLES[role])), is_champion=role == "champion",
                                 created=base + timedelta(days=int(rng.integers(0, 30))), inactive=None))
        if a.personal_domain:
            ctx.defect("salesforce.contact", a.account_id, "personal_email_domain")
        # champion leaves at onset; a recovered account finds a new champion later
        if a.archetype == "champion_loss" and a.onset:
            contacts[0]["inactive"] = a.onset
            if a.outcome == "recovered":
                f, l = str(rng.choice(["Iris", "Felix", "Noor", "Pavel"])), str(rng.choice(["Stone", "Ahmed", "Berg"]))
                contacts.append(dict(id=ctx.ids.sfdc("003", t["code"]), first=f, last=l,
                                     email=f"{f}.{l}".lower() + "@" + a.domain, role="champion",
                                     title="Head of Operations", is_champion=True,
                                     created=a.onset + timedelta(days=int(rng.integers(40, 110))), inactive=None))
        for c in contacts[1:]:
            if rng.random() < 0.05 and a.lifecycle == "customer":
                c["inactive"] = rand_date(rng, max(c["created"], C.WINDOW_START), C.WINDOW_END)
        ctx.contacts[a.idx] = contacts


def active_contacts(ctx: Ctx, a: Account, d: date) -> List[dict]:
    cs = [c for c in ctx.contacts[a.idx] if c["created"] <= d and (c["inactive"] is None or c["inactive"] > d)]
    return cs or ctx.contacts[a.idx][:1]


# ---------------------------------------------------------------- salesforce

def emit_salesforce(ctx: Ctx) -> Dict[str, List[dict]]:
    rng, w = ctx.rng, ctx.w
    out = {"user": [], "account": [], "contact": [], "opportunity": [], "task": []}
    for u in w.users:
        base = dict(id=u.user_id, name=u.name, email=u.email, user_role=u.role, time_zone=u.tz,
                    created_date=u.start_date, is_active=True)
        out["user"].append(dict(base, last_modified_date=ctx.when(u.start_date, u.tz), _pk=u.user_id,
                                _tenant=u.tenant, _changed_at=ctx.when(u.start_date, u.tz)))
        if u.end_date:
            t = ctx.when(u.end_date, u.tz)
            out["user"].append(dict(base, is_active=False, last_modified_date=t, _pk=u.user_id, _tenant=u.tenant, _changed_at=t))

    for a in w.accounts:
        t = ctx.tenant(a)
        tz = t["tz"]
        arr_missing = rng.random() < C.DEFECTS["null_arr"]
        ren_missing = rng.random() < C.DEFECTS["null_renewal_date"]
        ind_missing = rng.random() < C.DEFECTS["null_industry"]
        for flag, kind in ((arr_missing, "null_arr"), (ren_missing, "null_renewal_date"), (ind_missing, "null_industry")):
            if flag and a.lifecycle == "customer":
                ctx.defect("salesforce.account", a.account_id, kind)

        def acct_row(at: date, **kw):
            row = dict(id=a.account_id, name=a.name, website=None if a.personal_domain else "https://www." + a.domain,
                       industry=None if ind_missing else a.industry, type="Prospect", owner_id=a.owner_ae,
                       arr=None, currency_iso_code=a.currency, contract_start_date=None, renewal_date=None,
                       tier=a.tier, employee_band=a.employee_band, billing_country=a.country,
                       created_date=a.created_date, master_record_id=None, is_deleted=False, parent_id=a.parent_id)
            row.update(kw)
            if arr_missing:
                row["arr"] = None
            if ren_missing:
                row["renewal_date"] = None
            ts = ctx.when(at, tz)
            row.update(last_modified_date=ts, _pk=a.account_id, _tenant=a.tenant, _changed_at=ts)
            return row

        rows = [acct_row(a.created_date)]
        if a.lifecycle == "customer":
            def state(at):
                seats = a.seats_on(at)
                nxt = next((d for d in a.anniversaries(at + timedelta(days=800)) if d > at), None)
                return dict(type="Customer", owner_id=a.owner_on(at), arr=round(a.arr * seats / a.seats, -2),
                            contract_start_date=a.contract_start, renewal_date=nxt)
            changes = {a.contract_start}
            changes |= {d for d, _ in a.owner_history if d >= a.contract_start}
            changes |= {d for d, *_ in a.renewals} | {d for d, _ in a.expansions}
            for d in sorted(changes):
                if a.churn_date and d >= a.churn_date:
                    continue
                rows.append(acct_row(d, **state(d)))
            if a.churn_date:
                # the CSM updates the record a few weeks after the customer is gone
                lag = a.churn_date + timedelta(days=int(rng.integers(3, 40)))
                rows.append(acct_row(min(lag, C.WINDOW_END), **dict(state(a.churn_date - DAY), type="Former Customer")))
        out["account"] += rows

        if a.duplicate_id:
            created = rand_date(rng, a.created_date, min(C.WINDOW_END, a.created_date + timedelta(days=500)))
            merged = created + timedelta(days=int(rng.integers(20, 400)))
            a.duplicate_merged = merged if merged < C.WINDOW_END else None
            dup = dict(id=a.duplicate_id, name=name_variant(rng, a.name), website="https://" + a.domain, industry=None,
                       type="Prospect", owner_id=a.owner_ae, arr=None, currency_iso_code=a.currency,
                       contract_start_date=None, renewal_date=None, tier=a.tier, employee_band=None,
                       billing_country=a.country, created_date=created, master_record_id=None, is_deleted=False, parent_id=None)
            ts = ctx.when(created, tz)
            out["account"].append(dict(dup, last_modified_date=ts, _pk=a.duplicate_id, _tenant=a.tenant, _changed_at=ts))
            if a.duplicate_merged:
                ts = ctx.when(a.duplicate_merged, tz)
                out["account"].append(dict(dup, master_record_id=a.account_id, is_deleted=True, last_modified_date=ts,
                                           _pk=a.duplicate_id, _tenant=a.tenant, _changed_at=ts))
            ctx.defect("salesforce.account", a.duplicate_id, "duplicate_account", f"master={a.account_id}")

        for c in ctx.contacts[a.idx]:
            base = dict(id=c["id"], account_id=a.account_id, first_name=c["first"], last_name=c["last"], email=c["email"],
                        title=c["title"], contact_role=c["role"].replace("_", " ").title(), is_champion=c["is_champion"],
                        created_date=c["created"], inactive_date=None, email_bounced=False)
            ts = ctx.when(c["created"], tz)
            out["contact"].append(dict(base, last_modified_date=ts, _pk=c["id"], _tenant=a.tenant, _changed_at=ts))
            if c["inactive"] and c["inactive"] <= C.WINDOW_END:
                # nobody marks the contact inactive until an email bounces, weeks later
                seen = min(c["inactive"] + timedelta(days=int(rng.integers(10, 75))), C.WINDOW_END)
                ts = ctx.when(seen, tz)
                out["contact"].append(dict(base, inactive_date=c["inactive"], email_bounced=True, last_modified_date=ts,
                                           _pk=c["id"], _tenant=a.tenant, _changed_at=ts))

        out["opportunity"] += _opportunities(ctx, a)
    out["task"] = _tasks(ctx)
    return out


def _opportunities(ctx: Ctx, a: Account) -> List[dict]:
    rng = ctx.rng
    t = ctx.tenant(a)
    rows = []

    def opp(oid, name, typ, owner, created, versions, amount):
        for at, stage, close, extra in versions:
            prob = {"Prospecting": 10, "Discovery": 20, "Demo": 35, "Proposal": 55, "Negotiation": 75,
                    "Renewal Open": 70, "Closed Won": 100, "Closed Lost": 0}[stage]
            ts = ctx.when(at, t["tz"])
            row = dict(id=oid, account_id=a.account_id, name=name, type=typ, stage_name=stage,
                       amount=extra.get("amount", amount), currency_iso_code=a.currency, close_date=close,
                       probability=prob, is_closed=stage.startswith("Closed"), is_won=stage == "Closed Won",
                       closed_lost_reason=extra.get("reason"), owner_id=owner, created_date=created,
                       last_modified_date=ts, _pk=oid, _tenant=a.tenant, _changed_at=ts)
            rows.append(row)

    if a.stage_history:
        oid = ctx.ids.sfdc("006", t["code"])
        expected = a.opp_created + timedelta(days={"smb": 30, "mid": 60, "enterprise": 120}[a.tier])
        versions = []
        for d, stage in a.stage_history:
            if stage.startswith("Closed"):
                versions.append((d, stage, d, {"reason": a.lost_reason}))
            else:
                if d > expected:  # deal slipped, close date pushed out
                    expected = d + timedelta(days=int(rng.integers(14, 45)))
                versions.append((d, stage, expected, {}))
        est = a.arr * (rng.uniform(0.8, 1.3) if a.presales_outcome != "won" else 1)
        opp(oid, f"{a.name} - New Business", "New Business", a.owner_ae, a.opp_created, versions, round(est, -2))

    if a.lifecycle == "customer" and a.billing_interval == "year":
        horizon = C.WINDOW_END + timedelta(days=90)
        for d in a.anniversaries(horizon):
            created = d - timedelta(days=90)
            if d < C.WINDOW_START or created > C.WINDOW_END or (a.churn_date and d > a.churn_date):
                continue
            owner = a.owner_on(created) or a.owner_ae
            before = a.seats_on(d - DAY)
            amount = round(a.arr * before / a.seats, -2)
            oid = ctx.ids.sfdc("006", t["code"])
            versions = [(created, "Renewal Open", d, {})]
            if d - timedelta(days=30) <= C.WINDOW_END and a.tier != "smb":  # small accounts auto-renew
                versions.append((d - timedelta(days=30), "Negotiation", d, {}))
            if d <= C.WINDOW_END:
                if a.churn_date == d:
                    reason = {"slow_decline": "Churn - Low Adoption", "champion_loss": "Churn - Champion Left",
                              "support_crisis": "Churn - Product / Support", "silent_churn":
                              str(rng.choice(["Churn - Budget", "Churn - Acquired", "Churn - Other"])),
                              "dormant": "Churn - Low Adoption"}.get(a.archetype, "Churn - Other")
                    # closed-lost is often logged weeks late
                    versions.append((d + timedelta(days=int(rng.integers(0, 35))), "Closed Lost", d, {"reason": reason}))
                else:
                    after = a.seats_on(d)
                    versions.append((d, "Closed Won", d, {"amount": round(a.arr * after / a.seats, -2)}))
            versions = [v for v in versions if v[0] <= C.WINDOW_END]
            opp(oid, f"{a.name} - Renewal {d.year}", "Renewal", owner, created, versions, amount)

    for d, added in a.expansions:
        if added <= 0 or d < C.WINDOW_START:
            continue
        oid = ctx.ids.sfdc("006", t["code"])
        created = d - timedelta(days=int(rng.integers(10, 45)))
        owner = a.owner_on(d) or a.owner_ae
        amt = round(a.arr * added / a.seats, -2)
        opp(oid, f"{a.name} - Expansion +{added} seats", "Expansion", owner, created,
            [(created, "Proposal", d, {}), (d, "Closed Won", d, {})], amt)
    return rows


def _tasks(ctx: Ctx) -> List[dict]:
    rng, w = ctx.rng, ctx.w
    nA, nW = len(w.accounts), len(w.weeks)
    lam = np.zeros((nA, nW))
    for a in w.accounts:
        for i, wk in enumerate(w.weeks):
            if a.opp_created and a.opp_created <= wk <= (a.presales_close or C.WINDOW_END):
                lam[a.idx, i] = 1.2
            elif a.lifecycle == "customer" and w.health[a.idx, i] > 0 and a.owner_on(wk):
                tierw = {"enterprise": 0.5, "mid": 0.15, "smb": 0.04}[a.tier]
                onboard = 4 if a.acquired_in_window and wk < a.contract_start + timedelta(weeks=6) else 1
                lam[a.idx, i] = tierw * onboard
    counts = ctx.poisson(lam, C.STREAM_TARGETS["salesforce.task"] * w.scale)
    rows = []
    for a in w.accounts:
        if not a.intervention or not a.owner_on(a.intervention):
            continue
        t = ctx.tenant(a)
        for k, subj in enumerate(["Save plan: risk review", "Executive sponsor escalation call", "Success plan follow-up"]):
            d = a.intervention + timedelta(days=k * int(rng.integers(5, 15)))
            if d > C.WINDOW_END or (k and rng.random() < 0.4):
                break
            tid = ctx.ids.sfdc("00T", t["code"])
            ts = ctx.when(d, t["tz"])
            who = active_contacts(ctx, a, d)
            rows.append(dict(id=tid, account_id=a.account_id, who_id=who[0]["id"], owner_id=a.owner_on(d),
                             type="Meeting" if k == 1 else "Call", subject=subj, status="Completed", activity_date=d,
                             created_date=ts, _pk=tid, _tenant=a.tenant, _changed_at=ts))
    for ai, wi in zip(*np.nonzero(counts)):
        a = w.accounts[ai]
        t = ctx.tenant(a)
        for _ in range(counts[ai, wi]):
            d = w.weeks[wi] + timedelta(days=int(rng.integers(0, 5)))
            if d > C.WINDOW_END:
                continue
            presales = a.opp_created and a.opp_created <= d <= (a.presales_close or C.WINDOW_END)
            if presales:
                typ, subj = str(rng.choice(["Call", "Meeting", "Email"])), str(rng.choice(
                    ["Discovery call", "Product demo", "Technical deep-dive", "Pricing discussion", "Follow-up"]))
                owner = a.owner_ae
            else:
                typ = str(rng.choice(["Call", "Meeting", "Email"]))
                subj = "Onboarding session" if a.acquired_in_window and d < a.contract_start + timedelta(weeks=6) else str(
                    rng.choice(["QBR", "Check-in call", "Renewal call", "Executive sponsor sync", "Training session"]))
                owner = a.owner_on(d)
            who = active_contacts(ctx, a, d)
            tid = ctx.ids.sfdc("00T", t["code"])
            ts = ctx.when(d, t["tz"])
            rows.append(dict(id=tid, account_id=a.account_id, who_id=who[int(rng.integers(len(who)))]["id"],
                             owner_id=owner, type=typ, subject=subj, status="Completed", activity_date=d,
                             created_date=ts, _pk=tid, _tenant=a.tenant, _changed_at=ts))
    return rows


# ---------------------------------------------------------------- zendesk

def _ticket_topic(ctx: Ctx, a: Account, d: date, h: float, trial: bool) -> str:
    r = ctx.rng
    if trial:
        return "trial_question" if r.random() < 0.7 else str(r.choice(["integration", "how_to", "sso"]))
    dist = {"how_to": 30, "feature_request": 16, "bug": 14, "integration": 10, "praise": 7, "billing": 6, "sso": 5,
            "performance": 4, "data_export": 3, "renewal_pricing": 3, "incident": 2}
    if a.acquired_in_window and d < a.contract_start + timedelta(weeks=8):
        dist = {"onboarding": 45, "how_to": 25, "integration": 15, "sso": 8, "bug": 7}
    if a.archetype == "support_crisis" and a.onset and a.onset <= d <= a.crisis_end:
        dist = {"incident": 35, "bug": 20, "performance": 20, "escalation": 15, "data_export": 5, "how_to": 5}
    if a.archetype == "payment_failure" and a.onset and a.onset <= d <= a.onset + timedelta(days=40):
        dist = {"billing": 60, "how_to": 25, "bug": 15}
    if a.churn_date and a.churn_type == "voluntary" and a.detectable and a.churn_date - timedelta(days=60) <= d <= a.churn_date:
        dist = {"cancellation": 25, "data_export": 25, "renewal_pricing": 20, "how_to": 15, "billing": 15}
    if a.archetype == "noisy_loyal":
        dist = dict(dist, feature_request=dist.get("feature_request", 0) + 15, praise=dist.get("praise", 0) + 8)
    if a.renewals and any(0 <= (rd - d).days <= 45 for rd, *_ in a.renewals) and r.random() < 0.3:
        return "renewal_pricing"
    return pick(r, dist)


def _sentiment(ctx: Ctx, topic: str, h: float) -> str:
    r = ctx.rng
    if topic == "praise":
        return "positive"
    if topic in ("incident", "escalation"):
        return "negative" if r.random() < 0.85 else "neutral"
    p_neg = float(np.clip(0.75 - 0.8 * h, 0.05, 0.8))
    p_pos = float(np.clip(0.9 * h - 0.45, 0.05, 0.5))
    x = r.random()
    return "negative" if x < p_neg else "positive" if x < p_neg + p_pos else "neutral"


def _body(ctx: Ctx, a: Account, topic: str, sentiment: str, first: str, agent: str):
    r = ctx.rng
    pool = [b for b in T.LLM_BODIES if b[0] == topic and b[1] == sentiment] or [b for b in T.LLM_BODIES if b[0] == topic]
    if pool and r.random() < C.LLM_TEXT_SHARE:
        return ctx.fill(pool[int(r.integers(len(pool)))][2], a, first, agent), "llm"
    text = " ".join([str(r.choice(T.OPENERS[sentiment])), str(r.choice(T.CORES[topic])), str(r.choice(T.CLOSERS[sentiment])),
                     first.split()[0] if first else ""]).strip()
    return ctx.fill(text, a, first, agent), "template"


def emit_zendesk(ctx: Ctx) -> Dict[str, List[dict]]:
    rng, w = ctx.rng, ctx.w
    out = {"organization": [], "ticket": [], "ticket_comment": []}
    for a in w.accounts:
        has = (a.lifecycle == "customer" and rng.random() < C.DEFECTS["zendesk_org_coverage"]) or (a.has_trial and rng.random() < 0.5)
        if not has:
            ctx.org_id[a.idx] = None
            if a.lifecycle == "customer":
                ctx.defect("zendesk.organization", a.account_id, "no_zendesk_org")
            continue
        t = ctx.tenant(a)
        oid = ctx.ids.seq("zd_org" + a.tenant, 4400)
        ctx.org_id[a.idx] = oid
        ext = a.account_id
        if rng.random() < C.DEFECTS["zendesk_org_external_id_missing"]:
            ext = None
            ctx.defect("zendesk.organization", oid, "missing_external_id", a.account_id)
        elif a.duplicate_id and rng.random() < 0.4:
            ext = a.duplicate_id
            ctx.defect("zendesk.organization", oid, "stale_external_id", a.account_id)
        created = a.trial_start or a.contract_start
        created = max(created, C.WINDOW_START - timedelta(days=800))
        ts = ctx.when(created, t["tz"])
        ctx.identity(a, "zendesk.organization", oid)
        out["organization"].append(dict(id=oid, name=name_variant(rng, a.name), domain_names=[] if a.personal_domain else [a.domain],
                                        external_id=ext, created_at=ts, updated_at=ts, _pk=oid, _tenant=a.tenant, _changed_at=ts))

    nA, nW = len(w.accounts), len(w.weeks)
    lam = np.zeros((nA, nW))
    for a in w.accounts:
        h = w.health[a.idx]
        for i, wk in enumerate(w.weeks):
            if a.has_trial and a.trial_start <= wk <= a.trial_end:
                lam[a.idx, i] = 0.6
            if h[i] <= 0:
                continue
            v = (0.5 + a.seats_on(wk) ** 0.3) * a.activity_mult ** 0.5 * (0.7 + 0.3 * h[i])
            if a.archetype == "noisy_loyal":
                v *= 3
            if a.archetype == "support_crisis" and a.onset <= wk <= a.crisis_end:
                v *= 8
            if a.acquired_in_window and wk < a.contract_start + timedelta(weeks=8):
                v *= 2.5
            if a.archetype == "payment_failure" and a.onset and a.onset <= wk <= a.onset + timedelta(days=40):
                v *= 2
            if a.churn_date and a.detectable and a.churn_date - timedelta(days=60) <= wk:
                v *= 1.5
            lam[a.idx, i] = v * w.seasonal(a, wk)
    counts = ctx.poisson(lam, C.STREAM_TARGETS["zendesk.ticket"] * w.scale)

    comment_id = 0
    for ai, wi in zip(*np.nonzero(counts)):
        a = w.accounts[ai]
        t = ctx.tenant(a)
        hval = float(w.health[ai, wi]) or a.engagement
        trial = a.has_trial and a.trial_start <= w.weeks[wi] <= a.trial_end and w.health[ai, wi] <= 0
        for _ in range(counts[ai, wi]):
            d = w.weeks[wi] + timedelta(days=int(rng.integers(0, 7)))
            if d > C.WINDOW_END:
                continue
            topic = _ticket_topic(ctx, a, d, hval, trial)
            sentiment = _sentiment(ctx, topic, hval)
            people = active_contacts(ctx, a, d)
            req = people[int(rng.integers(len(people)))]
            agent = ctx.agents[a.tenant][int(rng.integers(len(ctx.agents[a.tenant])))]
            created = ctx.when(d, t["tz"])
            tid = ctx.ids.seq("zd_ticket" + a.tenant, 80000)
            prio = str(rng.choice(T.PRIORITY[topic]))
            hours = {"urgent": 8, "high": 30, "normal": 60, "low": 110}[prio] * float(rng.lognormal(0, 0.8))
            if topic == "escalation" or (a.archetype == "support_crisis" and sentiment == "negative"):
                hours *= 4
            solved = created + timedelta(hours=hours)
            subject = ctx.fill(str(rng.choice(T.SUBJECTS[topic])), a)
            csat = None
            if rng.random() < 0.3:
                good = 0.92 if sentiment == "positive" else 0.7 if sentiment == "neutral" else 0.3
                csat = "good" if rng.random() < good else "bad"
            base = dict(id=tid, organization_id=ctx.org_id.get(a.idx), requester_email=req["email"], assignee_id=agent["id"],
                        subject=subject, type=T.TICKET_TYPE.get(topic, "question"), priority=prio, tags=[topic],
                        via_channel=str(rng.choice(["email", "web", "chat", "api"], p=[0.5, 0.3, 0.15, 0.05])),
                        created_at=created)
            versions = [(created, "new", None)]
            if rng.random() < 0.4:
                versions.append((created + timedelta(hours=hours * rng.uniform(0.1, 0.6)), "pending", None))
            versions.append((solved, "solved", csat))
            versions.append((solved + timedelta(days=4), "closed", csat))
            end = datetime(C.WINDOW_END.year, C.WINDOW_END.month, C.WINDOW_END.day, 23, 59, tzinfo=UTC)
            for at, status, rating in versions:
                if at > end:
                    break
                row = dict(base, status=status, satisfaction_rating=rating, updated_at=at, _pk=tid, _tenant=a.tenant, _changed_at=at)
                if at.date() >= C.ZENDESK_CUSTOM_FIELD_DATE:
                    row["custom_churn_risk_flag"] = bool(topic in ("cancellation", "escalation") and rng.random() < 0.6)
                out["ticket"].append(row)

            # comments: requester, agent reply, sometimes a follow-up
            body, src = _body(ctx, a, topic, sentiment, req["first"], agent["first"])
            injected = rng.random() < C.PROMPT_INJECTION_RATE
            if injected:
                body += " " + str(rng.choice(T.INJECTIONS))
                ctx.defect("zendesk.ticket_comment", f"ticket={tid}", "prompt_injection", a.account_id)
            seq = [("end-user", body, src, sentiment, created)]
            if rng.random() < 0.65:
                reply = str(rng.choice(T.AGENT_REPLIES.get(topic, T.AGENT_REPLIES["default"])))
                seq.append(("agent", ctx.fill(reply, a, req["first"], agent["first"]), "template", "neutral",
                            created + timedelta(hours=hours * rng.uniform(0.05, 0.5))))
                if rng.random() < 0.3:
                    fs = "negative" if hval < 0.45 or (sentiment == "negative" and rng.random() < 0.5) else "positive" if hval > 0.65 else "neutral"
                    seq.append(("end-user", ctx.fill(str(rng.choice(T.FOLLOW_UPS[fs])), a, req["first"], agent["first"]),
                                "template", fs, created + timedelta(hours=hours * rng.uniform(0.5, 0.95))))
            for role, text, src, sent, at in seq:
                if at > end:
                    continue
                comment_id += 1
                cid = int(ctx.ids.seq("zd_comment" + a.tenant, 9100000))
                out["ticket_comment"].append(dict(id=cid, ticket_id=tid, author_role=role,
                                                  author_email=req["email"] if role == "end-user" else None,
                                                  public=True, body=text, created_at=at, _pk=cid, _tenant=a.tenant, _changed_at=at))
                ctx.text_truth.append(dict(tenant=a.tenant, account_id=a.account_id, ticket_id=tid, comment_id=cid,
                                           author_role=role, topic=topic, sentiment=sent, text_source=src,
                                           prompt_injection=injected and role == "end-user" and at == created))
    return out


# ---------------------------------------------------------------- gmail

def emit_gmail(ctx: Ctx) -> Dict[str, List[dict]]:
    rng, w = ctx.rng, ctx.w
    users = {u.user_id: u for u in w.users}
    nA, nW = len(w.accounts), len(w.weeks)
    lam = np.zeros((nA, nW))
    for a in w.accounts:
        if a.is_test:
            continue
        h = w.health[a.idx]
        for i, wk in enumerate(w.weeks):
            if a.presales_outcome == "nurture" and a.created_date <= wk <= a.created_date + timedelta(days=90):
                lam[a.idx, i] = 0.3
            elif a.opp_created and a.opp_created - timedelta(days=14) <= wk <= (a.presales_close or C.WINDOW_END):
                lam[a.idx, i] = 1.5
            elif h[i] > 0 and a.owner_on(wk):
                v = {"enterprise": 1.0, "mid": 0.35, "smb": 0.12}[a.tier] * a.activity_mult ** 0.3
                if a.acquired_in_window and wk < a.contract_start + timedelta(weeks=8):
                    v *= 2
                if any(0 <= (rd - wk).days <= 60 for rd in a.anniversaries(C.WINDOW_END + timedelta(days=60))):
                    v *= 2
                lam[a.idx, i] = v * w.seasonal(a, wk) ** 0.5
            if a.presales_outcome == "lost" and a.presales_close and 0 <= (wk - a.presales_close).days < 7:
                lam[a.idx, i] += 0.8  # closing-the-loop email
    counts = ctx.poisson(lam, C.STREAM_TARGETS["gmail.message_outbound"] * w.scale)
    rows = []
    end = datetime(C.WINDOW_END.year, C.WINDOW_END.month, C.WINDOW_END.day, 23, 59, tzinfo=UTC)

    def fmt(ts: datetime, tz: str) -> str:
        local = ts + timedelta(hours=tz_hours(tz))
        return local.strftime("%a, %d %b %Y %H:%M:%S ") + tz.replace(":", "")  # RFC 2822 Date header

    for ai, wi in zip(*np.nonzero(counts)):
        a = w.accounts[ai]
        t = ctx.tenant(a)
        for _ in range(counts[ai, wi]):
            d = w.weeks[wi] + timedelta(days=int(rng.integers(0, 5)))
            if d > C.WINDOW_END:
                continue
            h = float(w.health[ai, wi])
            presales = h <= 0
            owner_id = a.owner_ae if presales else a.owner_on(d)
            u = users.get(owner_id)
            if u is None:
                continue
            if presales:
                kind = "presales_lost" if a.presales_outcome == "lost" and a.presales_close and d >= a.presales_close else "presales_out"
                p_reply = {"won": 0.55, "open": 0.4, "lost": 0.3, "nurture": 0.08}.get(a.presales_outcome, 0.3)
            else:
                if a.acquired_in_window and d < a.contract_start + timedelta(weeks=8):
                    kind = "onboarding"
                elif any(0 <= (rd - d).days <= 60 for rd in a.anniversaries(C.WINDOW_END + timedelta(days=60))):
                    kind = "renewal"
                elif h < 0.45 and rng.random() < 0.5:
                    kind = "risk"
                else:
                    kind = "steady"
                p_reply = 0.15 + 0.7 * h
            people = active_contacts(ctx, a, d)
            to = people[int(rng.integers(len(people)))]
            bounce = False
            # emails to a champion who has left bounce until someone updates the CRM
            if a.archetype == "champion_loss" and a.onset and d >= a.onset and rng.random() < 0.5:
                to, bounce = ctx.contacts[a.idx][0], True
            sent = ctx.when(d, u.tz)
            if sent > end:
                continue
            thread = ctx.ids.hexid("t_", 16)
            q = (d.month - 1) // 3 + 1
            subject = ctx.fill(str(rng.choice(T.EMAIL_SUBJECTS[kind])), a).replace("Q1 ", f"Q{q} ")
            replied = (not bounce) and rng.random() < p_reply
            to_domain = to["email"].split("@")[1]
            rows.append(dict(message_id=f"<{ctx.ids.hexid('', 20)}@mail.gmail.com>", thread_id=thread, mailbox=u.email,
                             direction="outbound", from_domain=t["domain"], to_domains=[to_domain],
                             cc_count=int(rng.poisson(0.4)), sent_at=fmt(sent, u.tz), subject=subject,
                             has_reply=replied, bounce=bounce, label_ids=["SENT"], _pk=None, _tenant=a.tenant, _changed_at=sent))
            if bounce:
                rows.append(dict(message_id=f"<{ctx.ids.hexid('', 20)}@mail.gmail.com>", thread_id=thread, mailbox=u.email,
                                 direction="inbound", from_domain="googlemail.com", to_domains=[t["domain"]], cc_count=0,
                                 sent_at=fmt(sent + timedelta(minutes=2), u.tz),
                                 subject="Delivery Status Notification (Failure)", has_reply=False, bounce=True,
                                 label_ids=["INBOX"], _pk=None, _tenant=a.tenant, _changed_at=sent + timedelta(minutes=2)))
            if replied:
                lag = timedelta(hours=float(rng.lognormal(np.log(6 if h > 0.6 else 30), 0.9)))
                at = sent + lag
                if at <= end:
                    rows.append(dict(message_id=f"<{ctx.ids.hexid('', 20)}@{to_domain}>", thread_id=thread, mailbox=u.email,
                                     direction="inbound", from_domain=to_domain, to_domains=[t["domain"]], cc_count=int(rng.poisson(0.3)),
                                     sent_at=fmt(at, u.tz), subject="Re: " + subject, has_reply=False, bounce=False,
                                     label_ids=["INBOX"], _pk=None, _tenant=a.tenant, _changed_at=at))
    # unsolicited inbound from healthy customers
    for a in w.accounts:
        if a.lifecycle != "customer" or a.is_test:
            continue
        for i, wk in enumerate(w.weeks):
            h = w.health[a.idx, i]
            u = users.get(a.owner_on(wk))
            if h <= 0 or u is None or rng.random() > 0.03 * h * {"enterprise": 2.5, "mid": 1, "smb": 0.4}[a.tier]:
                continue
            t = ctx.tenant(a)
            at = ctx.when(wk + timedelta(days=int(rng.integers(0, 5))), t["tz"])
            if at > end:
                continue
            frm = active_contacts(ctx, a, wk)[0]["email"].split("@")[1]
            rows.append(dict(message_id=f"<{ctx.ids.hexid('', 20)}@{frm}>", thread_id=ctx.ids.hexid("t_", 16), mailbox=u.email,
                             direction="inbound", from_domain=frm, to_domains=[t["domain"]], cc_count=0,
                             sent_at=fmt(at, u.tz), subject=ctx.fill(str(rng.choice(T.EMAIL_SUBJECTS["inbound"])), a),
                             has_reply=False, bounce=False, label_ids=["INBOX"], _pk=None, _tenant=a.tenant, _changed_at=at))
    return {"message": rows}


# ---------------------------------------------------------------- stripe

FAIL_CODES = ["card_declined", "insufficient_funds", "expired_card", "do_not_honor", "processing_error"]


def emit_stripe(ctx: Ctx) -> Dict[str, List[dict]]:
    rng, w = ctx.rng, ctx.w
    out = {"customer": [], "subscription": [], "invoice": [], "charge": []}
    for a in w.accounts:
        if a.lifecycle != "customer" or a.is_test:
            continue
        t = ctx.tenant(a)
        tz = t["tz"]
        payer = next((c for c in ctx.contacts[a.idx] if c["role"] == "economic_buyer"), ctx.contacts[a.idx][0])
        email = payer["email"] if rng.random() < 0.6 else "accounts@" + a.domain
        meta = a.account_id
        x = rng.random()
        if x < C.DEFECTS["stripe_missing_sfdc_id"]:
            meta = None
            ctx.defect("stripe.customer", a.account_id, "missing_sfdc_id")
        elif x < C.DEFECTS["stripe_missing_sfdc_id"] + C.DEFECTS["stripe_stale_sfdc_id"] and a.duplicate_id:
            meta = a.duplicate_id
            ctx.defect("stripe.customer", a.account_id, "stale_sfdc_id", a.duplicate_id)
        cus = ctx.ids.hexid("cus_")
        ctx.identity(a, "stripe.customer", cus)
        created = ctx.when(a.contract_start, tz)
        out["customer"].append(dict(id=cus, email=email, name=name_variant(rng, a.name), metadata_sfdc_account_id=meta,
                                    currency=a.currency.lower(), created=created, delinquent=False, _pk=cus, _tenant=a.tenant, _changed_at=created))
        # a second customer record for the same company, created when billing details changed
        dup_cus, dup_from = None, None
        if rng.random() < C.DEFECTS["stripe_duplicate_customer"]:
            dup_from = rand_date(rng, max(a.eff_start, C.WINDOW_START), a.churn_date or C.WINDOW_END)
            dup_cus = ctx.ids.hexid("cus_")
            ctx.identity(a, "stripe.customer", dup_cus)
            ts = ctx.when(dup_from, tz)
            out["customer"].append(dict(id=dup_cus, email=email, name=a.name.upper(), metadata_sfdc_account_id=None,
                                        currency=a.currency.lower(), created=ts, delinquent=False, _pk=dup_cus, _tenant=a.tenant, _changed_at=ts))
            ctx.defect("stripe.customer", dup_cus, "duplicate_customer", a.account_id)

        sub = ctx.ids.hexid("sub_")
        unit = a.arr / a.seats  # per seat per year
        interval = a.billing_interval

        def sub_row(at: datetime, status: str, qty: int, cancel_at=None, canceled_at=None):
            return dict(id=sub, customer_id=cus, plan_id=f"{a.tier}_{interval}ly", interval=interval, quantity=qty,
                        unit_amount=int(round(unit * 100 / (12 if interval == "month" else 1))), currency=a.currency.lower(),
                        status=status, cancel_at=cancel_at, canceled_at=canceled_at, created=created, updated=at,
                        _pk=sub, _tenant=a.tenant, _changed_at=at)
        out["subscription"].append(sub_row(created, "active", a.seats))
        for d, added in a.expansions:
            if not a.churn_date or d < a.churn_date:
                at = ctx.when(d, tz)
                out["subscription"].append(sub_row(at, "active", a.seats_on(d)))
        if a.churn_date and a.churn_type == "voluntary":
            notice = a.churn_date - timedelta(days=int(rng.integers(5, 60)))
            cancel_ts = ctx.when(a.churn_date, tz)
            out["subscription"].append(sub_row(ctx.when(notice, tz), "active", a.seats_on(notice), cancel_at=cancel_ts))
            out["subscription"].append(sub_row(cancel_ts, "canceled", a.seats_on(notice), cancel_at=cancel_ts, canceled_at=cancel_ts))

        for d in a.billing_dates(C.WINDOW_END):
            if d < C.WINDOW_START or (a.churn_date and d >= a.churn_date):
                continue
            customer = dup_cus if dup_cus and d >= dup_from else cus
            qty = a.seats_on(d)
            amount = int(round(unit * qty * 100 / (12 if interval == "month" else 1)))
            _invoice(ctx, out, a, customer, sub, d, amount, tz)
        for d, added in a.expansions:
            if added > 0 and d >= C.WINDOW_START and (not a.churn_date or d < a.churn_date) and interval == "year":
                nxt = next(x for x in a.anniversaries(d + timedelta(days=400)) if x > d)
                frac = (nxt - d).days / 365
                _invoice(ctx, out, a, cus, sub, d, int(round(unit * added * frac * 100)), tz, proration=True)

        if a.archetype == "payment_failure" and a.onset:
            at = ctx.when(a.onset, tz)
            out["subscription"].append(sub_row(at, "past_due", a.seats_on(a.onset)))
            if a.outcome == "recovered" and a.outcome_date <= C.WINDOW_END:
                out["subscription"].append(sub_row(ctx.when(a.outcome_date, tz), "active", a.seats_on(a.onset)))
            elif a.churn_date:
                at = ctx.when(a.churn_date, tz)
                out["subscription"].append(sub_row(at, "canceled", a.seats_on(a.onset), canceled_at=at))
    return out


def _invoice(ctx, out, a: Account, cus, sub, d: date, amount: int, tz: str, proration=False):
    rng = ctx.rng
    inv = ctx.ids.hexid("in_")
    created = ctx.when(d, tz, business=False)
    base = dict(id=inv, customer_id=cus, subscription_id=sub, billing_reason="subscription_update" if proration else "subscription_cycle",
                amount_due=amount, currency=a.currency.lower(), period_start=d, created=created)
    out["invoice"].append(dict(base, status="open", amount_paid=0, attempt_count=0, _pk=inv, _tenant=a.tenant, _changed_at=created))
    failing = a.archetype == "payment_failure" and a.onset and a.onset <= d <= a.onset + timedelta(days=45)
    attempts = [0, 3, 5, 7] if failing else ([0, 3] if rng.random() < 0.03 else [0])
    recovered = not failing or a.outcome == "recovered"
    end = datetime(C.WINDOW_END.year, C.WINDOW_END.month, C.WINDOW_END.day, 23, 59, tzinfo=UTC)
    for k, off in enumerate(attempts):
        at = created + timedelta(days=off, minutes=int(rng.integers(0, 90)))
        if at > end:
            return
        last = k == len(attempts) - 1
        ok = last and recovered
        ch = ctx.ids.hexid("ch_")
        out["charge"].append(dict(id=ch, invoice_id=inv, customer_id=cus, amount=amount, currency=a.currency.lower(),
                                  status="succeeded" if ok else "failed", failure_code=None if ok else str(rng.choice(FAIL_CODES)),
                                  paid=ok, created=at, _pk=ch, _tenant=a.tenant, _changed_at=at))
        if ok:
            out["invoice"].append(dict(base, status="paid", amount_paid=amount, attempt_count=k + 1, _pk=inv, _tenant=a.tenant, _changed_at=at))
        elif last:
            out["invoice"].append(dict(base, status="uncollectible", amount_paid=0, attempt_count=k + 1, _pk=inv,
                                       _tenant=a.tenant, _changed_at=at + timedelta(days=1)))


# ---------------------------------------------------------------- product

EVENTS = ["login_session", "report_created", "dashboard_shared", "export_run", "integration_connected",
          "api_key_created", "admin_settings_changed", "user_invited"]
W_HEALTHY = np.array([45, 20, 10, 7, 3, 2, 5, 8], float)
W_DECLINE = np.array([55, 6, 2, 28, 1, 1, 5, 2], float)
W_TRIAL = np.array([40, 18, 6, 4, 12, 2, 6, 12], float)
RENAMED = {"login_session": "session.start", "report_created": "report.create", "dashboard_shared": "dashboard.share",
           "export_run": "export.run", "integration_connected": "integration.connect", "api_key_created": "api_key.create",
           "admin_settings_changed": "settings.update", "user_invited": "user.invite", "seat_added": "seat.add",
           "seat_removed": "seat.remove"}


def emit_product(ctx: Ctx, target: float) -> Dict[str, List[dict]]:
    rng, w = ctx.rng, ctx.w
    out = {"workspace": [], "event": []}
    for a in w.accounts:
        t = ctx.tenant(a)
        spaces = []
        if a.has_trial or a.lifecycle == "customer":
            start = a.trial_start or a.contract_start
            n = 2 if a.tier == "enterprise" and a.lifecycle == "customer" and rng.random() < 0.25 else 1
            for k in range(n):
                wid = "ws_" + hashlib.md5(f"{a.account_id}{k}".encode()).hexdigest()[:10]
                link = a.account_id if a.lifecycle == "customer" or a.presales_outcome == "won" else None
                miss = C.DEFECTS["trial_workspace_missing_account"] if a.lifecycle == "prospect" else C.DEFECTS["workspace_missing_account"]
                if link is not None and rng.random() < miss:
                    link = None
                    ctx.defect("product.workspace", wid, "missing_account_link", a.account_id)
                if a.lifecycle == "prospect" and rng.random() >= miss:
                    link = a.account_id
                created = ctx.when(start if k == 0 else start + timedelta(days=int(rng.integers(30, 300))), t["tz"])
                ws = dict(id=wid, sfdc_account_id=link, name=(a.name if k == 0 else a.name + " - Sandbox"),
                          plan="trial" if a.has_trial and k == 0 else a.tier, seats_purchased=a.seats if a.lifecycle == "customer" else 5,
                          status="trialing" if a.has_trial and k == 0 else "active", created_at=created)
                out["workspace"].append(dict(ws, updated_at=created, _pk=wid, _tenant=a.tenant, _changed_at=created))
                if a.has_trial and k == 0:
                    at = ctx.when(a.contract_start if a.presales_outcome == "won" else a.trial_end, t["tz"])
                    if at.date() <= C.WINDOW_END:
                        won = a.presales_outcome == "won"
                        out["workspace"].append(dict(ws, plan=a.tier if won else "trial", status="active" if won else "expired",
                                                     seats_purchased=a.seats if won else 5, updated_at=at, _pk=wid, _tenant=a.tenant, _changed_at=at))
                for d, added in a.expansions:
                    if d <= C.WINDOW_END and (not a.churn_date or d < a.churn_date):
                        at = ctx.when(d, t["tz"])
                        out["workspace"].append(dict(ws, plan=a.tier, status="active", seats_purchased=a.seats_on(d), updated_at=at,
                                                     _pk=wid, _tenant=a.tenant, _changed_at=at))
                if a.churn_date:
                    at = ctx.when(a.churn_date + timedelta(days=int(rng.integers(0, 15))), t["tz"])
                    if at.date() <= C.WINDOW_END:
                        out["workspace"].append(dict(ws, plan=a.tier, status="canceled", seats_purchased=a.seats_on(a.churn_date),
                                                     updated_at=at, _pk=wid, _tenant=a.tenant, _changed_at=at))
                ctx.identity(a, "product.workspace", wid)
                spaces.append(wid)
        ctx.workspaces[a.idx] = spaces

    nA, nW = len(w.accounts), len(w.weeks)
    lam = np.zeros((nA, nW))
    for a in w.accounts:
        if not ctx.workspaces[a.idx]:
            continue
        h = w.health[a.idx]
        for i, wk in enumerate(w.weeks):
            v = 0.0
            if a.has_trial and a.trial_start <= wk <= a.trial_end:
                v = 3 * a.engagement * (1 + 0.3 * a.seats ** 0.3)
            if h[i] > 0:
                v += a.seats_on(wk) ** 0.6 * a.activity_mult * h[i] ** 1.5 * w.seasonal(a, wk)
            elif a.churn_date and 0 <= (wk - a.churn_date).days <= 21:
                v += 0.1 * a.seats ** 0.6 * a.activity_mult  # stragglers after cancellation
            lam[a.idx, i] = v
    counts = ctx.poisson(lam, target)
    end = datetime(C.WINDOW_END.year, C.WINDOW_END.month, C.WINDOW_END.day, 23, 59, tzinfo=UTC)

    def emit(a, wid, name, at, users, h, props=None):
        when = at.date()
        if when >= C.PRODUCT_RENAME_DATE:
            name = RENAMED.get(name, name)
        p = props or {}
        if name in ("export_run", "export.run"):
            crisis = a.archetype == "support_crisis" and a.onset and a.onset <= when <= a.crisis_end
            key = "rows" if when >= C.PRODUCT_RENAME_DATE else "row_count"
            p = {key: int(rng.lognormal(7, 1.5)), "status": "failed" if rng.random() < (0.6 if crisis else 0.03) else "ok"}
        elif name in ("login_session", "session.start"):
            p = {"duration_s": int(rng.lognormal(6, 1)), "client": str(rng.choice(["web", "web", "ios", "android"]))}
        elif name in ("integration_connected", "integration.connect"):
            p = {"provider": str(rng.choice(ctx.tenant(a)["integrations"]))}
        uh = users[int(min(len(users) - 1, rng.zipf(1.6) - 1))]
        out["event"].append(dict(event_id=ctx.ids.hexid("e_", 20), workspace_id=wid, user_hash=uh, event_name=name,
                                 event_time=at, properties_json=json.dumps(p), _pk=None, _tenant=a.tenant, _changed_at=at))

    for ai, wi in zip(*np.nonzero(counts)):
        a = w.accounts[ai]
        t = ctx.tenant(a)
        hval = float(w.health[ai, wi])
        wk = w.weeks[wi]
        trial = hval <= 0 and a.has_trial and a.trial_start <= wk <= a.trial_end
        n_users = max(1, a.seats_on(wk) if not trial else int(rng.integers(1, 6)))
        active = max(1, round(n_users * (0.15 + 0.85 * (hval if not trial else a.engagement))))
        users = [hashlib.md5(f"{a.account_id}u{k}".encode()).hexdigest()[:12] for k in range(active)]
        weights = W_TRIAL if trial else W_HEALTHY * hval + W_DECLINE * (1 - hval)
        weights = weights / weights.sum()
        for _ in range(counts[ai, wi]):
            at = ctx.when(wk + timedelta(days=int(rng.integers(0, 7))), t["tz"])
            if at > end:
                continue
            wid = ctx.workspaces[a.idx][0 if len(ctx.workspaces[a.idx]) == 1 or rng.random() < 0.85 else 1]
            emit(a, wid, EVENTS[rng.choice(len(EVENTS), p=weights)], at, users, hval)
    # structural events: seat changes, admin hand-over when the champion leaves
    for a in w.accounts:
        if not ctx.workspaces[a.idx]:
            continue
        wid = ctx.workspaces[a.idx][0]
        users = [hashlib.md5(f"{a.account_id}u0".encode()).hexdigest()[:12]]
        for d, added in a.expansions:
            if C.WINDOW_START <= d <= C.WINDOW_END:
                emit(a, wid, "seat_added" if added > 0 else "seat_removed", ctx.when(d, ctx.tenant(a)["tz"]), users, 1,
                     {"delta": int(added)})
        if a.archetype == "champion_loss" and a.onset:
            emit(a, wid, "admin_settings_changed", ctx.when(a.onset + timedelta(days=int(rng.integers(1, 20))), ctx.tenant(a)["tz"]),
                 users, 0.5, {"change": "owner_transferred"})
    return out
