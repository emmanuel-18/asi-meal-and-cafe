"""Bounded synthetic data generator for the isolated development demo.

This module intentionally has no database access.  Apply mode uses only the
authenticated HTTP client and refuses non-loopback targets.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5
from urllib.parse import urlsplit

from asi_meal_api.demo_client import DemoClient, DemoClientError, ORIGIN

NAMESPACE = UUID("1f87a2b4-0dc0-47b0-94aa-8d6f41d681e2")
PROTECTED_ORIGIN = "192.168.45.145:43873"


class SeedError(RuntimeError):
    pass


def _dates(start: date, count: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(count)]


def _plan(args: argparse.Namespace) -> dict:
    rng = random.Random(args.seed)
    service_dates = _dates(args.start, args.days)
    statuses = ["received"] * round(args.orders * 0.75) + ["pending"] * (args.orders - round(args.orders * 0.75))
    rng.shuffle(statuses)
    payments = ["cash", "gcash", "sd", "incentive", "finance", "split"]
    orders = []
    for number, status in enumerate(statuses, 1):
        key = str(uuid5(NAMESPACE, f"{args.seed}:order:{number}"))
        orders.append({"sequence": number, "request_key": key, "service_date": str(rng.choice(service_dates)),
                       "customer": "employee" if number % 7 else "visitor", "status": status,
                       "payment": payments[number % len(payments)]})
    visitors = [{"sequence": i, "scenario": ("VIP" if i % 4 == 0 else "Client representative" if i % 4 == 1 else "Audit visitor" if i % 4 == 2 else "Partner")}
                for i in range(1, args.visitors + 1)]
    return {"seed": args.seed, "service_dates": [str(d) for d in service_dates],
            "menus": max(1, min(args.days, 10)), "visitors": visitors, "orders": orders}


def _safe_target(origin: str) -> None:
    if origin != ORIGIN or PROTECTED_ORIGIN in origin or not origin.startswith("http://127.0.0.1:"):
        raise SeedError("Refusing non-isolated development target.")


def _verify_database_target(expected_name: str) -> None:
    raw = os.environ.get("ASI_DATABASE_URL", "")
    parsed = urlsplit(raw)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path.lstrip("/") != expected_name:
        raise SeedError("ASI_DATABASE_URL is not the verified isolated development database.")
    if "192.168.45.145" in raw or os.environ.get("ASI_DEMO_CONTAINER") != "asi-meal-demo-postgres-438864ebc209":
        raise SeedError("Refusing the protected or unidentified database target.")


def _journal(path: Path, event: str, **values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": event, **values}, sort_keys=True) + "\n")


def _apply(plan: dict, args: argparse.Namespace) -> None:
    _safe_target(ORIGIN)
    _verify_database_target(args.database_name)
    password = getpass.getpass("Demo seeder password: ")
    client = DemoClient()
    journal = Path(args.journal)
    try:
        client.login(password)
        _journal(journal, "authenticated", account="demo_seeder")
        employees = client.request("GET", "/api/employees?limit=100&offset=0")
        if not employees:
            raise SeedError("No employees are available in the isolated demo.")
        dishes = client.request("GET", "/api/dishes?limit=100&offset=0&active=true")
        by_category = {category: [d for d in dishes if d.get("category_code") == category]
                       for category in ("vegetable", "non_vegetable")}
        if not all(by_category.values()):
            raise SeedError("Both active vegetable and non-vegetable dishes are required before writing.")
        menu_ids = {}
        for day in plan["service_dates"]:
            try:
                dated = client.request("GET", f"/api/menus/by-date/{day}")
                menu_ids[day] = dated["id"]
            except DemoClientError as exc:
                if "HTTP 404" not in str(exc):
                    raise SeedError("Could not verify a menu assignment; stopping before writes.") from exc
        missing = [day for day in plan["service_dates"] if day not in menu_ids]
        if missing:
            selected = [by_category["vegetable"][0]["id"], by_category["non_vegetable"][0]["id"]]
            created = client.request("POST", "/api/menus", {"label": "Synthetic demo menu", "dish_ids": selected,
                "assignments": [{"service_date": day, "expected_menu_id": None} for day in missing],
                "include_default_rice": True})
            for day in missing:
                menu_ids[day] = created["id"]
            _journal(journal, "menu_created", count=len(missing))
        visitor_ids = []
        for item in plan["visitors"]:
            created = client.request("POST", "/api/visitors", {"display_name": f"Demo Visitor {item['sequence']:02d} - {item['scenario']}"})
            visitor_ids.append(created["id"])
            _journal(journal, "visitor_created", sequence=item["sequence"])
        for item in plan["orders"]:
            menu = client.request("GET", f"/api/menus/{menu_ids[item['service_date']]}")
            offerings = menu["items"]
            veg = next(x for x in offerings if x["category_code"] == "vegetable")
            nonveg = next(x for x in offerings if x["category_code"] == "non_vegetable")
            rice = next((x for x in offerings if x["category_code"] == "extra_rice"), None)
            selected = [{"menu_item_id": veg["id"], "quantity": 1}, {"menu_item_id": nonveg["id"], "quantity": 1}]
            if rice and item["sequence"] % 3 == 0:
                selected.append({"menu_item_id": rice["id"], "quantity": 1})
            total = sum((Decimal(str(next(x["unit_price"] for x in offerings if x["id"] == s["menu_item_id"]))) * s["quantity"] for s in selected), Decimal("0"))
            customer = item["sequence"] % 7 == 0
            payload = {"request_key": item["request_key"], "service_date": item["service_date"], "menu_id": menu["id"],
                       "items": selected, "allocations": [{"category": "finance", "amount": str(total)}] if customer else
                       [{"category": "sd" if item["sequence"] % 5 == 0 else "cash", "amount": str(total)}]}
            if customer:
                payload["visitor_id"] = visitor_ids[(item["sequence"] // 7) % len(visitor_ids)]
            else:
                payload["employee_number"] = employees[item["sequence"] % len(employees)]["employee_number"]
            result = client.create_order(payload)
            _journal(journal, "order_created", sequence=item["sequence"], order_id=result.get("order_id"), status="pending")
            if item["status"] == "received":
                client.request("POST", f"/api/orders/{result['order_id']}/received", {"expected_version": result["version"]})
                _journal(journal, "order_received", sequence=item["sequence"])
        if args.phase == "pilot":
            _journal(journal, "pilot_completed", orders=len(plan["orders"]))
    finally:
        client.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate bounded synthetic data in the isolated ASI Meal demo.")
    parser.add_argument("--apply", action="store_true", help="write through the authenticated demo API")
    parser.add_argument("--phase", choices=("pilot", "full"), default="pilot")
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--orders", type=int, default=600)
    parser.add_argument("--visitors", type=int, default=40)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 10, 24))
    parser.add_argument("--journal", default=".demo-seed-journal.jsonl")
    parser.add_argument("--database-name", default="asi_demo_438864ebc209")
    args = parser.parse_args(argv)
    if args.apply and args.phase == "pilot" and (args.orders > 10 or args.visitors > 10 or args.days > 10):
        parser.error("pilot phase is limited to 10 orders, visitors and service dates")
    if args.phase == "full":
        journal_path = Path(args.journal)
        if not journal_path.exists() or '"event": "pilot_completed"' not in journal_path.read_text(encoding="utf-8"):
            parser.error("full phase requires the completed pilot journal")
    if not 1 <= args.orders <= 600 or not 0 <= args.visitors <= 40 or not 1 <= args.days <= 60:
        parser.error("counts and days exceed the bounded development-demo limits")
    plan = _plan(args)
    print(json.dumps({"seed": plan["seed"], "dates": len(plan["service_dates"]), "menus": plan["menus"],
                      "visitors": len(plan["visitors"]), "orders": len(plan["orders"]),
                      "received": sum(x["status"] == "received" for x in plan["orders"]),
                      "pending": sum(x["status"] == "pending" for x in plan["orders"])}, indent=2))
    if not args.apply:
        print("Dry run only; no authentication or records were used.")
        return 0
    try:
        _apply(plan, args)
    except (DemoClientError, SeedError, OSError, ValueError) as exc:
        print(f"Stopped safely: {exc}", file=sys.stderr)
        return 1
    print("Synthetic demo population completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
