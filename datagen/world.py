"""The hidden world: tenants, their staff, their accounts and what really happens to each account.

Nothing here is written to the lake directly. Source emitters read this state and produce what
each system would have recorded; the corruption layer then damages those records."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Tuple, Dict
import re

import numpy as np

from . import config as C
from . import names as N

DAY = timedelta(days=1)


def pick(rng, dist: Dict[str, float]) -> str:
    keys = list(dist)
    p = np.array([dist[k] for k in keys], dtype=float)
    return keys[rng.choice(len(keys), p=p / p.sum())]


def quota(dist: Dict[str, float], n: int) -> Dict[str, int]:
    """Exact integer counts that follow `dist` (largest-remainder rounding)."""
    total = sum(dist.values())
    raw = {k: n * v / total for k, v in dist.items()}
    out = {k: int(np.floor(v)) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: n - sum(out.values())]:
        out[k] += 1
    return out


def rand_date(rng, lo: date, hi: date) -> date:
    span = max((hi - lo).days, 0)
    return lo + timedelta(days=int(rng.integers(0, span + 1)))


def add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + n, day=28)


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, 28))


class Ids:
    """Per-tenant sequential IDs in each system's own format."""
    def __init__(self, rng):
        self.rng = rng
        self.counters: Dict[str, int] = {}

    def sfdc(self, prefix: str, tcode: str) -> str:
        k = prefix + tcode
        self.counters[k] = self.counters.get(k, 0) + 1
        n = self.counters[k] * 7919 + 104729  # spread so IDs don't look sequential
        return f"{prefix}{tcode}0000{np.base_repr(n, 36).rjust(8, '0')}"

    def seq(self, key: str, start: int) -> int:
        self.counters[key] = self.counters.get(key, start) + 1
        return self.counters[key]

    def hexid(self, prefix: str, n: int = 14) -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return prefix + "".join(alphabet[i] for i in self.rng.integers(0, len(alphabet), n))


@dataclass
class User:
    tenant: str
    user_id: str
    name: str
    email: str
    role: str            # CSM | AE | CS Manager
    start_date: date
    end_date: Optional[date]
    tz: str


@dataclass
class Account:
    tenant: str
    idx: int
    account_id: str
    name: str
    domain: str
    industry: str
    employee_band: str
    country: str
    tier: str
    seats: int
    arr: float
    currency: str
    billing_interval: str            # year | month
    lifecycle: str                   # customer | prospect
    archetype: str                   # customer archetype, or "prospect"
    created_date: date
    activity_mult: float
    personal_domain: bool
    is_test: bool = False
    owner_ae: Optional[str] = None
    # pre-sales
    opp_created: Optional[date] = None
    presales_close: Optional[date] = None
    presales_outcome: Optional[str] = None   # won | lost | open | nurture | pre_window
    lost_reason: Optional[str] = None
    stage_history: List[Tuple[date, str]] = field(default_factory=list)
    has_trial: bool = False
    trial_start: Optional[date] = None
    trial_end: Optional[date] = None
    engagement: float = 0.0
    # post-sales
    contract_start: Optional[date] = None
    acquired_in_window: bool = False
    onset: Optional[date] = None
    crisis_end: Optional[date] = None
    outcome: str = "n/a"             # renewed | churned | downsold | recovered | at_risk | n/a
    outcome_date: Optional[date] = None
    churn_date: Optional[date] = None
    churn_type: Optional[str] = None   # voluntary | involuntary
    detectable: Optional[bool] = None
    renewals: List[Tuple[date, str, int, int]] = field(default_factory=list)  # (date, result, seats_before, seats_after)
    expansions: List[Tuple[date, int]] = field(default_factory=list)          # (date, seats_added)
    owner_history: List[Tuple[date, Optional[str]]] = field(default_factory=list)
    parent_id: Optional[str] = None      # SFDC parent account (subsidiary structure)
    same_company_as: Optional[str] = None  # account in another tenant that is the same real company
    intervention: Optional[date] = None  # CSM save play started
    duplicate_id: Optional[str] = None   # SFDC duplicate merged into this account
    duplicate_merged: Optional[date] = None

    @property
    def eff_start(self) -> Optional[date]:
        if self.contract_start is None:
            return None
        return max(self.contract_start, C.WINDOW_START)

    def billing_dates(self, until: date) -> List[date]:
        """Every billing date from contract start up to `until`."""
        out, d, k = [], self.contract_start, 0
        while d <= until:
            out.append(d)
            k += 1
            d = add_years(self.contract_start, k) if self.billing_interval == "year" else add_months(self.contract_start, k)
        return out

    def anniversaries(self, until: date) -> List[date]:
        out, k = [], 1
        while add_years(self.contract_start, k) <= until:
            out.append(add_years(self.contract_start, k))
            k += 1
        return out

    def owner_on(self, d: date) -> Optional[str]:
        owner = None
        for start, uid in self.owner_history:
            if start <= d:
                owner = uid
        return owner

    def seats_on(self, d: date) -> int:
        s = self.seats
        for ed, added in self.expansions:  # negative entries are downsells
            if ed <= d:
                s += added
        return max(s, 1)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


TLD = {"US": ".com", "CA": ".ca", "GB": ".co.uk", "IE": ".ie", "DE": ".de", "AT": ".at",
       "NL": ".nl", "PL": ".pl", "IN": ".in"}


class World:
    def __init__(self, scale: float, seed: int):
        self.rng = np.random.default_rng(seed)
        self.ids = Ids(self.rng)
        self.scale = scale
        start = C.WINDOW_START - timedelta(days=C.WINDOW_START.weekday())
        self.weeks = [start + timedelta(weeks=i) for i in range(((C.WINDOW_END - start).days // 7) + 1)]
        self.tenants = {t["key"]: t for t in C.TENANTS}
        self.users: List[User] = []
        self.accounts: List[Account] = []
        self._build_users()
        self._build_accounts()
        self.health = np.zeros((len(self.accounts), len(self.weeks)))
        for a in self.accounts:
            self._simulate_lifecycle(a)
            self.health[a.idx] = self._health_curve(a)

    # ---------- staff ----------
    def _person(self):
        return str(self.rng.choice(N.FIRST_NAMES)), str(self.rng.choice(N.LAST_NAMES))

    def _new_user(self, t, role, start, end=None, tz=None):
        f, l = self._person()
        email = f"{f}.{l}".lower().replace("'", "") + "@" + t["domain"]
        u = User(t["key"], self.ids.sfdc("005", t["code"]), f"{f} {l}", email, role, start, end, tz or t["tz"])
        self.users.append(u)
        return u

    def _build_users(self):
        rng = self.rng
        for t in C.TENANTS:
            n_csm = max(1, round(t["csms"] * self.scale))
            n_ae = max(1, round(t["aes"] * self.scale))
            self._new_user(t, "CS Manager", C.WINDOW_START - timedelta(days=900))
            for _ in range(n_ae):
                self._new_user(t, "AE", C.WINDOW_START - timedelta(days=int(rng.integers(100, 1200))))
            for _ in range(n_csm):
                tz = t["tz"] if rng.random() > 0.15 else str(rng.choice(["-08:00", "+01:00", "+05:30"]))
                u = self._new_user(t, "CSM", C.WINDOW_START - timedelta(days=int(rng.integers(60, 1500))), tz=tz)
                if rng.random() < C.DEFECTS["csm_departure_rate"]:
                    u.end_date = rand_date(rng, C.WINDOW_START + timedelta(days=90), C.WINDOW_END - timedelta(days=60))
                    # replacement joins after a gap; the departed CSM's book is unowned in between
                    self._new_user(t, "CSM", u.end_date + timedelta(days=int(rng.integers(7, 45))), tz=t["tz"])

    def staff(self, tenant: str, role: str, on: date) -> List[User]:
        return [u for u in self.users if u.tenant == tenant and u.role == role
                and u.start_date <= on and (u.end_date is None or u.end_date > on)]

    # ---------- accounts ----------
    def _company_name(self, tkey):
        p = str(self.rng.choice(N.PREFIXES))
        s = str(self.rng.choice(N.SUFFIX_BY_TENANT[tkey]))
        return p, s

    def _build_accounts(self):
        rng = self.rng
        n = int(round(C.FULL_ACCOUNTS * self.scale))
        shares = {t["key"]: t["share"] for t in C.TENANTS}
        tenant_bag = [k for k, c in quota(shares, n).items() for _ in range(c)]
        rng.shuffle(tenant_bag)
        life_bag = {}
        for k, c in quota(shares, n).items():
            b = ["prospect"] * int(round(c * C.PROSPECT_SHARE))
            b += ["customer"] * (c - len(b))
            rng.shuffle(b)
            life_bag[k] = b
        used = set()
        for i in range(n):
            tkey = tenant_bag[i]
            t = self.tenants[tkey]
            for _ in range(20):
                p, s = self._company_name(tkey)
                if (tkey, p, s) not in used:
                    break
            used.add((tkey, p, s))
            legal = str(rng.choice(N.LEGAL_SUFFIX[tkey]))
            name = f"{p} {s} {legal}".strip()
            country = pick(rng, N.COUNTRY_BY_TENANT[tkey])
            domain = slug(p + s.split()[0]) + TLD.get(country, ".com")
            tier = pick(rng, C.TIERS)
            lo, hi = C.SEATS[tier]
            seats = int(np.exp(rng.uniform(np.log(lo), np.log(hi))))
            arr = round(seats * C.PRICE_PER_SEAT_YEAR[tier] * float(rng.lognormal(0, 0.15)), -2)
            monthly_p = 0 if tier == "enterprise" else t["monthly_share"] * (2.0 if tier == "smb" else 0.6)
            band = {"enterprise": ["1001-5000", "5001+"], "mid": ["201-1000", "51-200"],
                    "smb": ["1-10", "11-50"]}[tier]
            a = Account(
                tenant=tkey, idx=i, account_id=self.ids.sfdc("001", t["code"]), name=name, domain=domain,
                industry=str(rng.choice(N.INDUSTRY_BY_TENANT[tkey])), employee_band=str(rng.choice(band)),
                country=country, tier=tier, seats=seats, arr=arr, currency=pick(rng, t["currencies"]),
                billing_interval="month" if rng.random() < monthly_p else "year",
                lifecycle=life_bag[tkey].pop(),
                archetype="prospect", created_date=C.WINDOW_START,
                activity_mult=float(rng.lognormal(0, 0.6)),  # heavy-tailed activity
                # small businesses run on personal mailboxes; rate is set per account overall
                personal_domain=tier == "smb" and rng.random() < C.DEFECTS["personal_email_domain_accounts"] / C.TIERS["smb"],
            )
            self.accounts.append(a)
        self._assign_contracts()
        self._assign_archetypes()
        self._company_structure()
        # SFDC duplicates: a second record for the same company, later merged
        for a in self.accounts:
            if not a.is_test and rng.random() < C.DEFECTS["sfdc_duplicate_account_rate"]:
                a.duplicate_id = self.ids.sfdc("001", self.tenants[a.tenant]["code"])

    def _assign_contracts(self):
        """Contract start is fixed before archetypes so risk archetypes only go to accounts with
        enough time left in the window for the risk to play out."""
        rng = self.rng
        customers = [a for a in self.accounts if a.lifecycle == "customer"]
        n_new = int(round(len(customers) * C.CUSTOMER_ACQUIRED_IN_WINDOW))
        order = rng.permutation(len(customers))
        for rank, i in enumerate(order):
            a = customers[i]
            if rank < n_new:
                a.acquired_in_window = True
                a.contract_start = rand_date(rng, C.WINDOW_START + timedelta(days=30), C.WINDOW_END - timedelta(days=45))
            else:
                a.contract_start = rand_date(rng, C.WINDOW_START - timedelta(days=3 * 365), C.WINDOW_START - DAY)
        n_test = max(1, int(round(len(self.accounts) * C.DEFECTS["test_account_rate"])))
        for i in rng.choice(len(customers), size=n_test, replace=False):
            a = customers[i]
            t = self.tenants[a.tenant]
            a.is_test, a.archetype = True, "healthy"
            a.name, a.domain, a.tier, a.personal_domain = "Test Account - DO NOT USE", t["domain"], "smb", False

    def _company_structure(self):
        rng = self.rng
        # parent/child inside a tenant: a subsidiary signs its own contract
        for tkey in self.tenants:
            big = [a for a in self.accounts if a.tenant == tkey and a.tier == "enterprise" and not a.is_test]
            kids = [a for a in self.accounts if a.tenant == tkey and a.tier in ("mid", "enterprise") and not a.is_test]
            for a in kids:
                if big and rng.random() < C.PARENT_CHILD_RATE:
                    parent = big[int(rng.integers(len(big)))]
                    if parent is not a:
                        a.parent_id = parent.account_id
                        a.name = parent.name.split()[0] + " " + a.name.split()[1] + " " + str(rng.choice(["UK", "EMEA", "West", "Europe", "APAC"]))
        # one real company buying from two tenants: same name and domain, unrelated records
        customers = [a for a in self.accounts if a.lifecycle == "customer" and not a.is_test]
        for a in customers:
            if rng.random() < C.CROSS_TENANT_COMPANY_RATE:
                others = [b for b in customers if b.tenant != a.tenant and b.same_company_as is None and b.parent_id is None]
                if others:
                    b = others[int(rng.integers(len(others)))]
                    b.name, b.domain, b.country = a.name, a.domain, a.country
                    b.same_company_as, a.same_company_as = a.account_id, b.account_id

    def _assign_archetypes(self):
        """Exact archetype counts from config.ARCHETYPES, placed where each one can happen."""
        rng = self.rng
        pool = [a for a in self.accounts if a.lifecycle == "customer" and not a.is_test]
        bag = quota(C.ARCHETYPES, len(pool))
        free = list(range(len(pool)))
        room = lambda days: (lambda a: a.eff_start <= C.WINDOW_END - timedelta(days=days))

        def take(arch, ok=lambda a: True, prefer=None, prefer_share=1.0):
            cand = [i for i in free if ok(pool[i])]
            rng.shuffle(cand)
            if prefer:
                pref = [i for i in cand if prefer(pool[i])]
                rest = [i for i in cand if not prefer(pool[i])]
                k = min(len(pref), int(round(bag[arch] * prefer_share)))
                cand = pref[:k] + rest + pref[k:]
            for i in cand[:bag[arch]]:
                pool[i].archetype = arch
                free.remove(i)

        take("payment_failure", room(100), prefer=lambda a: a.billing_interval == "month")  # card billing fails
        for arch in ("slow_decline", "champion_loss", "support_crisis"):
            take(arch, room(100))
        take("silent_churn", room(150))
        take("seasonal", prefer=lambda a: a.tenant == "brightpath", prefer_share=0.6)
        take("dormant", ok=lambda a: a.tier != "enterprise")
        for arch in ("noisy_loyal", "expanding", "healthy"):
            take(arch)
        for i in free:  # rounding leftovers
            pool[i].archetype = "healthy"

    # ---------- lifecycle ----------
    def _presales(self, a: Account, outcome: str, close: Optional[date] = None):
        rng = self.rng
        cycle = {"smb": (14, 45), "mid": (30, 100), "enterprise": (60, 200)}[a.tier]
        length = int(rng.integers(*cycle))
        a.presales_outcome = outcome
        aes = self.staff(a.tenant, "AE", close or C.WINDOW_START) or [u for u in self.users if u.tenant == a.tenant and u.role == "AE"]
        a.owner_ae = aes[int(rng.integers(len(aes)))].user_id
        if outcome == "nurture":
            a.created_date = rand_date(rng, C.WINDOW_START, C.WINDOW_END - timedelta(days=20))
            return
        if outcome == "won":
            a.presales_close = close
            a.opp_created = close - timedelta(days=length)
        elif outcome == "lost":
            a.opp_created = rand_date(rng, C.WINDOW_START, C.WINDOW_END - timedelta(days=40))
            a.presales_close = a.opp_created + timedelta(days=int(length * rng.uniform(0.6, 1.2)))
            if a.presales_close >= C.WINDOW_END:
                outcome = a.presales_outcome = "open"
                a.presales_close = None
            else:
                a.lost_reason = pick(rng, C.LOST_REASONS)
        if outcome == "open":
            a.opp_created = a.opp_created or rand_date(rng, C.WINDOW_END - timedelta(days=220), C.WINDOW_END - timedelta(days=5))
        a.created_date = a.opp_created - timedelta(days=int(rng.integers(0, 60)))
        stages = ["Prospecting", "Discovery", "Demo", "Proposal", "Negotiation"]
        if outcome == "won":
            reach = len(stages)
        elif outcome == "lost":
            reach = int(rng.integers(2, len(stages) + 1))
        else:
            elapsed = (C.WINDOW_END - a.opp_created).days / max(length, 1)
            reach = int(np.clip(np.ceil(elapsed * len(stages)), 1, len(stages)))
        end = a.presales_close or C.WINDOW_END
        span = max((end - a.opp_created).days, reach)
        cuts = sorted(rng.choice(np.arange(1, span), size=reach - 1, replace=False)) if reach > 1 and span > reach else []
        a.stage_history = [(a.opp_created, stages[0])] + [(a.opp_created + timedelta(days=int(c)), stages[k + 1]) for k, c in enumerate(cuts)]
        if outcome in ("won", "lost"):
            a.stage_history.append((a.presales_close, "Closed Won" if outcome == "won" else "Closed Lost"))
        demo_dates = [d for d, s in a.stage_history if s == "Demo"]
        trial_p = {"smb": 0.7, "mid": 0.55, "enterprise": 0.3}[a.tier]
        if demo_dates and rng.random() < trial_p:
            a.has_trial = True
            a.trial_start = demo_dates[0] + timedelta(days=int(rng.integers(0, 5)))
            a.trial_end = min(a.trial_start + timedelta(days=int(rng.choice([14, 30]))), C.WINDOW_END)
            beta = {"won": (5, 2), "open": (3, 3), "Price": (4, 3), "Competitor": (3, 3), "No Decision": (2, 4),
                    "Missing Feature": (2, 3), "Timing / Budget": (3, 3)}[a.lost_reason or outcome]
            a.engagement = float(rng.beta(*beta))

    def _first_billing_on_or_after(self, a: Account, d: date) -> date:
        dates = a.billing_dates(d + timedelta(days=400))
        return next(x for x in dates if x >= d)

    def _simulate_lifecycle(self, a: Account):
        rng = self.rng
        if a.lifecycle == "prospect":
            self._presales(a, pick(rng, C.PROSPECT_OUTCOMES))
            return
        if a.acquired_in_window:
            self._presales(a, "won", close=a.contract_start - timedelta(days=int(rng.integers(0, 8))))
        else:
            a.presales_outcome = "pre_window"
            a.created_date = a.contract_start - timedelta(days=int(rng.integers(30, 200)))
            aes = [u for u in self.users if u.tenant == a.tenant and u.role == "AE"]
            a.owner_ae = aes[int(rng.integers(len(aes)))].user_id

        # owner: a CSM active at the start; follow departures to the replacement
        start = a.eff_start
        csms = self.staff(a.tenant, "CSM", start) or [u for u in self.users if u.tenant == a.tenant and u.role == "CSM"]
        owner = csms[int(rng.integers(len(csms)))]
        a.owner_history = [(a.created_date, a.owner_ae), (a.contract_start, owner.user_id)]
        while owner.end_date and owner.end_date < C.WINDOW_END:
            a.owner_history.append((owner.end_date, None))
            nxt = [u for u in self.users if u.tenant == a.tenant and u.role == "CSM" and u.start_date > owner.end_date]
            if not nxt or rng.random() < 0.12:
                break  # left unassigned
            owner = min(nxt, key=lambda u: u.start_date)
            a.owner_history.append((owner.start_date, owner.user_id))

        arch = a.archetype
        negative = arch in ("slow_decline", "champion_loss", "support_crisis", "payment_failure")
        lo_onset, hi_onset = start + timedelta(days=60), C.WINDOW_END - timedelta(days=20)
        if negative and lo_onset > hi_onset:
            a.archetype = arch = "healthy"
            negative = False
        if negative:
            a.onset = rand_date(rng, lo_onset, hi_onset)
        a.detectable = arch != "silent_churn"

        if arch == "slow_decline":
            lead = int(rng.integers(120, 270)) if a.billing_interval == "year" else int(rng.integers(60, 150))
            self._set_outcome(a, a.onset + timedelta(days=lead), "churned" if rng.random() < 0.65 else "downsold")
        elif arch == "champion_loss":
            lead = int(rng.integers(60, 200))
            self._set_outcome(a, a.onset + timedelta(days=lead), "churned" if rng.random() < 0.70 else "recovered")
        elif arch == "support_crisis":
            a.crisis_end = a.onset + timedelta(weeks=int(rng.integers(4, 11)))
            self._set_outcome(a, a.onset + timedelta(days=60), "churned" if rng.random() < 0.5 else "recovered")
        elif arch == "payment_failure":
            if rng.random() < 0.65:
                d = a.onset + timedelta(days=int(rng.integers(21, 36)))
                a.outcome, a.churn_type = "churned", "involuntary"
                a.outcome_date = d
                if d <= C.WINDOW_END:
                    a.churn_date = d
                else:
                    a.outcome = "at_risk"
            else:
                a.outcome, a.outcome_date = "recovered", a.onset + timedelta(days=int(rng.integers(5, 20)))
        elif arch == "silent_churn":
            renewals = [d for d in a.billing_dates(C.WINDOW_END + timedelta(days=200)) if d > start + timedelta(days=120)]
            target = renewals[int(rng.integers(len(renewals)))] if renewals else C.WINDOW_END + timedelta(days=60)
            self._set_outcome(a, target, "churned", exact=True)
        elif arch == "dormant" and rng.random() < 0.4:
            renewals = [d for d in a.billing_dates(C.WINDOW_END + timedelta(days=200)) if d > start + timedelta(days=60)]
            target = renewals[int(rng.integers(len(renewals)))] if renewals else C.WINDOW_END + timedelta(days=60)
            self._set_outcome(a, target, "churned", exact=True)
        else:
            a.outcome = "renewed"

        # expansions
        n_exp = int(rng.integers(1, 4)) if arch == "expanding" else int(rng.random() < 0.12)
        last = a.churn_date or a.onset or C.WINDOW_END
        for _ in range(n_exp):
            lo = start + timedelta(days=90)
            if lo < last:
                a.expansions.append((rand_date(rng, lo, last), max(1, int(a.seats * rng.uniform(0.1, 0.4)))))
        a.expansions.sort()

        # CSM save play: most recoveries had one, some losses got one too late
        if a.onset and a.detectable and rng.random() < C.INTERVENTION_RATE.get(a.outcome, 0):
            late = a.outcome == "churned"
            lo = a.onset + timedelta(days=60 if late else 10)
            hi = (a.outcome_date - timedelta(days=5)) if late and a.outcome_date else a.onset + timedelta(days=50)
            if lo < min(hi, C.WINDOW_END):
                a.intervention = rand_date(rng, lo, min(hi, C.WINDOW_END))

        if a.outcome == "downsold":
            before = a.seats_on(a.outcome_date - DAY)
            a.expansions.append((a.outcome_date, -max(1, int(before * rng.uniform(0.25, 0.6)))))
            a.expansions.sort()

        # renewal outcomes on each anniversary inside the window (annual terms are tracked in SFDC
        # even for monthly billing; a monthly churn between anniversaries never shows up here)
        for d in a.anniversaries(C.WINDOW_END):
            if d < C.WINDOW_START or (a.churn_date and d > a.churn_date):
                continue
            before = a.seats_on(d - DAY)
            if a.churn_date == d:
                a.renewals.append((d, "churned", before, 0))
            elif a.outcome == "downsold" and a.outcome_date == d:
                a.renewals.append((d, "downsold", before, a.seats_on(d)))
            else:
                a.renewals.append((d, "renewed", before, before))

    def _set_outcome(self, a: Account, earliest: date, outcome: str, exact: bool = False):
        # annual contracts can only end on an anniversary; monthly ones on the next billing date
        d = earliest if exact else self._first_billing_on_or_after(a, earliest)
        a.outcome_date = d
        a.churn_type = "voluntary" if outcome == "churned" else None
        if d > C.WINDOW_END:
            # the outcome lands after the dump: the account is still live, at risk or recovering
            a.outcome = "at_risk" if outcome in ("churned", "downsold") else "recovering"
            return
        a.outcome = outcome
        if outcome == "churned":
            a.churn_date = d

    # ---------- health ----------
    def _health_curve(self, a: Account) -> np.ndarray:
        rng = self.rng
        h = np.zeros(len(self.weeks))
        if a.lifecycle != "customer":
            return h
        base = {"healthy": 0.80, "expanding": 0.82, "seasonal": 0.78, "noisy_loyal": 0.74, "slow_decline": 0.76,
                "champion_loss": 0.78, "support_crisis": 0.76, "payment_failure": 0.75, "silent_churn": 0.80,
                "dormant": 0.22}[a.archetype] + rng.normal(0, 0.04)
        noise = 0.0
        champ_drop = a.onset + timedelta(days=int(rng.integers(30, 90))) if a.archetype == "champion_loss" else None
        for w, wk in enumerate(self.weeks):
            if wk < a.contract_start - timedelta(days=6) or (a.churn_date and wk > a.churn_date):
                continue
            v = base
            if a.archetype == "expanding":
                v = base + 0.12 * min(1, max(0, (wk - a.eff_start).days / 365))
            if a.onset and wk >= a.onset:
                od = a.outcome_date or C.WINDOW_END
                frac = min(1, max(0, (wk - a.onset).days / max((od - a.onset).days, 7)))
                if a.archetype == "slow_decline":
                    v = base - (base - 0.2) * frac
                    if a.outcome == "downsold" and wk > od:
                        v = 0.55
                elif a.archetype == "champion_loss" and wk >= champ_drop:
                    v = 0.5 - 0.25 * frac
                    if a.outcome == "recovered" and wk > a.onset + timedelta(days=120):
                        v = 0.72
                elif a.archetype == "support_crisis":
                    if wk <= a.crisis_end:
                        v = 0.35
                    elif a.outcome == "recovered":
                        v = min(base, 0.35 + 0.07 * ((wk - a.crisis_end).days / 7))
                    else:
                        v = 0.45 - 0.15 * frac
            # onboarding ramp for new customers
            if a.acquired_in_window and wk < a.contract_start + timedelta(weeks=8):
                v = 0.55 + (v - 0.55) * max(0, (wk - a.contract_start).days) / 56
            noise = 0.7 * noise + rng.normal(0, 0.035)
            h[w] = float(np.clip(v + noise, 0.02, 0.99))
        return h

    def seasonal(self, a: Account, d: date) -> float:
        t = self.tenants[a.tenant]
        md = (d.month, d.day)
        holiday = md >= (12, 20) or md <= (1, 3)
        if t["seasonality"] == "academic":
            if d.month in (7, 8):
                return 0.25
            return 0.35 if holiday else 1.0
        if a.archetype == "seasonal":
            if d.month in (7, 8):
                return 0.4
            return 0.4 if holiday else 1.0
        if holiday:
            return 0.6
        return 0.85 if d.month == 8 else 1.0
