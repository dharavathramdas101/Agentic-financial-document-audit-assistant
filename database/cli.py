"""
Simple CLI for the human review queue.

Usage:
  python -m database.cli list
  python -m database.cli approve <id> [--note "..."]
  python -m database.cli reject  <id> [--note "..."]
  python -m database.cli stats
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import ReviewQueue
from database.session import SessionLocal, create_tables


def cmd_list(args) -> None:
    create_tables()
    status_filter = getattr(args, "status", "pending")
    with SessionLocal() as db:
        query = db.query(ReviewQueue)
        if status_filter != "all":
            query = query.filter_by(status=status_filter)
        rows = query.order_by(ReviewQueue.id).all()

    if not rows:
        print(f"No items with status='{status_filter}'.")
        return

    header = f"{'ID':>4}  {'CONF':>5}  {'FLAG':<22}  {'STATUS':<10}  CLAIM"
    print(header)
    print("-" * 90)
    for r in rows:
        claim_short = r.claim[:60] + "…" if len(r.claim) > 60 else r.claim
        print(f"{r.id:>4}  {r.confidence:>5.2f}  {r.flag_reason:<22}  {r.status:<10}  {claim_short}")
        if r.reviewer_note:
            print(f"      Note: {r.reviewer_note}")


def cmd_approve(args) -> None:
    _update_status(args.id, "approved", args.note)


def cmd_reject(args) -> None:
    _update_status(args.id, "rejected", args.note)


def cmd_stats(args) -> None:
    create_tables()
    with SessionLocal() as db:
        total    = db.query(ReviewQueue).count()
        pending  = db.query(ReviewQueue).filter_by(status="pending").count()
        approved = db.query(ReviewQueue).filter_by(status="approved").count()
        rejected = db.query(ReviewQueue).filter_by(status="rejected").count()

    print(f"Review queue stats:")
    print(f"  Total    : {total}")
    print(f"  Pending  : {pending}")
    print(f"  Approved : {approved}")
    print(f"  Rejected : {rejected}")


def _update_status(item_id: int, new_status: str, note: str) -> None:
    create_tables()
    with SessionLocal() as db:
        row = db.get(ReviewQueue, item_id)
        if row is None:
            print(f"Error: item {item_id} not found.")
            sys.exit(1)
        if row.status != "pending":
            print(f"Error: item {item_id} is already '{row.status}'.")
            sys.exit(1)
        row.status = new_status
        row.reviewer_note = note or None
        db.commit()
    print(f"Item {item_id} marked as '{new_status}'." + (f" Note: {note}" if note else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="FinAudit review queue CLI")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="List review items")
    p_list.add_argument("--status", default="pending",
                        choices=["pending", "approved", "rejected", "all"])

    p_approve = sub.add_parser("approve", help="Approve a pending item")
    p_approve.add_argument("id", type=int)
    p_approve.add_argument("--note", default="", help="Reviewer note")

    p_reject = sub.add_parser("reject", help="Reject a pending item")
    p_reject.add_argument("id", type=int)
    p_reject.add_argument("--note", default="", help="Rejection reason")

    sub.add_parser("stats", help="Show queue statistics")

    args = parser.parse_args()
    dispatch = {"list": cmd_list, "approve": cmd_approve,
                "reject": cmd_reject, "stats": cmd_stats}

    if args.command not in dispatch:
        parser.print_help()
        sys.exit(1)

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
