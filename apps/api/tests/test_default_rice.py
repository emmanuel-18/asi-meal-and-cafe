"""Synthetic default-offering tests on the isolated PostgreSQL harness."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from asi_meal_api.business_services import BusinessService
from asi_meal_api.orders import Conflict
from test_database import sql
from test_orders import concurrent_env
from test_auth import auth_env, passwords


@pytest.mark.parametrize("legacy_count", [0, 1, 2])
def test_default_rice_is_deterministic_and_preserves_old_snapshots(concurrent_env, legacy_count):
    engine, g, _, actor = concurrent_env
    service = BusinessService(sessionmaker(bind=engine))
    with engine.begin() as c:
        sql(c, "UPDATE item_categories SET default_unit_price=27.50 WHERE code='extra_rice'")
        legacy = [sql(c, "INSERT INTO dishes (name,category_code) VALUES ('Extra Rice','extra_rice') RETURNING id").scalar_one()
                  for _ in range(legacy_count)]
        before = sql(c, "SELECT id,item_name,unit_price FROM menu_items WHERE menu_id=:id ORDER BY id", id=g["menu"]).all()
    assert service.menu_defaults(actor)["extra_rice_price"] == Decimal("27.50")
    menus = [service.create_menu(actor, None, g["dishes"][:2], [], True) for _ in range(2)]
    rice = [[item for item in menu["items"] if item["category_code"] == "extra_rice"] for menu in menus]
    assert all(len(items) == 1 and items[0]["unit_price"] == Decimal("27.50") for items in rice)
    assert rice[0][0]["dish_id"] == rice[1][0]["dish_id"]
    if legacy:
        assert rice[0][0]["dish_id"] == min(legacy)
    with engine.connect() as c:
        assert sql(c, "SELECT count(*) FROM dishes WHERE name='Extra Rice' AND category_code='extra_rice'").scalar_one() == max(legacy_count, 1)
        assert sql(c, "SELECT id,item_name,unit_price FROM menu_items WHERE menu_id=:id ORDER BY id", id=g["menu"]).all() == before


def test_concurrent_default_creation_has_one_canonical_dish(concurrent_env):
    engine, g, _, actor = concurrent_env
    service = BusinessService(sessionmaker(bind=engine))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.create_menu(actor, None, g["dishes"][:2], [], True), range(2)))
    rice_ids = [[item["dish_id"] for item in result["items"] if item["category_code"] == "extra_rice"] for result in results]
    assert len(rice_ids[0]) == 1 and rice_ids[0] == rice_ids[1]
    with engine.connect() as c:
        assert sql(c, "SELECT count(*) FROM dishes WHERE name='Extra Rice' AND category_code='extra_rice'").scalar_one() == 1


def test_conflicting_assignment_creates_neither_menu_nor_rice(concurrent_env):
    engine, g, _, actor = concurrent_env
    service = BusinessService(sessionmaker(bind=engine))
    with engine.connect() as c:
        menus_before = sql(c, "SELECT count(*) FROM menus").scalar_one()
    with pytest.raises(Conflict):
        service.create_menu(actor, None, g["dishes"][:2], [(g["day"], None)], True)
    with engine.connect() as c:
        assert sql(c, "SELECT count(*) FROM menus").scalar_one() == menus_before
        assert sql(c, "SELECT count(*) FROM dishes WHERE name='Extra Rice' AND category_code='extra_rice'").scalar_one() == 0


def test_default_rice_http_assignment_and_rejection(auth_env):
    from test_auth import client, login_http
    from test_business_http import headers

    engine, g, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        assert c.get("/api/menu-defaults").status_code == 401
        h = headers(login_http(c, password).json()["csrf_token"])
        assert c.get("/api/menu-defaults").json() == {"extra_rice_price": "15.00"}
        body = {"dish_ids": g["dishes"][:2], "include_default_rice": True,
                "assignments": [{"service_date": "2040-01-04", "expected_menu_id": None}]}
        response = c.post("/api/menus", json=body, headers=h)
        assert response.status_code == 201, response.text
        saved = response.json()
        assert len([item for item in saved["items"] if item["category_code"] == "extra_rice"]) == 1
        assert c.get("/api/menus/by-date/2040-01-04").json()["items"] == saved["items"]
        from uuid import uuid4
        rice = next(item for item in saved["items"] if item["category_code"] == "extra_rice")
        order = c.post("/api/orders", headers=h, json={"request_key": str(uuid4()),
            "service_date": "2040-01-04", "menu_id": saved["id"], "employee_number": g["employee"],
            "items": [{"menu_item_id": rice["id"], "quantity": 3}],
            "allocations": [{"category": "cash", "amount": "45.00"}]})
        assert order.status_code == 201, order.text
        order_id = order.json()["order_id"]
        with engine.begin() as connection:
            sql(connection, "UPDATE item_categories SET default_unit_price=25 WHERE code='extra_rice'")
        assert c.get(f"/api/orders/{order_id}").json()["items"][0]["unit_price"] == "15.00"
        assert c.get("/api/menus/by-date/2040-01-04").json()["items"] == saved["items"]
        assert c.post("/api/menus", json=body, headers=h).status_code == 409
