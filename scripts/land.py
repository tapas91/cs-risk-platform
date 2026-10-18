"""Stand-in for Fivetran: move generated files into ./landing, the folder Airflow reads as its bucket.

    python3 scripts/land.py --until 2026-06   # everything synced up to June 2026
    python3 scripts/land.py --next            # the next synced month (new and late files arrive together)
    python3 scripts/land.py --all             # the rest
    python3 scripts/land.py --status

Landed files are hard links to the generated ones, so landing/ takes no extra disk space.
Files are grouped by the month Fivetran synced them, so advancing a month brings in that month's
incremental files, including late rows about much older events. Uses only the standard library."""
import argparse
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "lake" / "s3" / "cs-risk-raw"
LANDING = ROOT / "landing"
STAGING = ROOT / ".landing-staging"
MONTH = re.compile(r"synced_month=(\d{4}-\d{2})")


def files():
    for f in sorted(LAKE.rglob("*.parquet")):
        yield f, MONTH.search(str(f)).group(1)


def landed_months():
    return sorted({MONTH.search(str(f)).group(1) for f in LANDING.rglob("*.parquet")})


def land(until: str) -> int:
    n = 0
    for f, month in files():
        if month <= until:
            dest = LANDING / f.relative_to(LAKE)
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(f, dest)  # a hard link: same bytes on disk, appears atomically, no second copy
                except OSError:
                    tmp = STAGING / f"{n}.part"  # different filesystem: copy beside, then rename in
                    STAGING.mkdir(exist_ok=True)
                    shutil.copy2(f, tmp)
                    tmp.rename(dest)
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--until", help="land every file synced up to this month (YYYY-MM)")
    g.add_argument("--next", action="store_true", help="land the next synced month")
    g.add_argument("--all", action="store_true")
    g.add_argument("--status", action="store_true")
    args = ap.parse_args()
    months = sorted({m for _, m in files()})
    done = landed_months()
    if args.status:
        print(f"landed {len(done)} of {len(months)} months; last landed: {done[-1] if done else 'none'}")
        return
    if args.all:
        until = months[-1]
    elif args.next:
        pending = [m for m in months if not done or m > done[-1]]
        if not pending:
            print("nothing left to land")
            return
        until = pending[0]
    else:
        until = args.until
    print(f"landed {land(until)} new files (synced up to {until})")


if __name__ == "__main__":
    main()
