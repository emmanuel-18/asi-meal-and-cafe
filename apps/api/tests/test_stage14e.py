"""Synthetic operational register coverage on a disposable PostgreSQL schema."""
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from asi_meal_api.business_services import BusinessService
from asi_meal_api.orders import ActorContext, Allocation, Correction, Conflict, OrderError
from test_orders import concurrent_env, request
from test_auth import auth_env, passwords, client, login_http
from test_business_http import headers
from test_database import sql
import pytest


def test_legacy_offset_pagination_skips_after_received_transition(concurrent_env):
    engine, g, orders, actor = concurrent_env
    directory = BusinessService(sessionmaker(bind=engine))
    created = [orders.create_pending(actor, request(g)) for _ in range(21)]
    first = directory.orders(actor, start=g['day'], end=g['day'], pending_first=True, limit=10, offset=0)
    orders.mark_received(actor, first[0]['order_id'], 1)
    second = directory.orders(actor, start=g['day'], end=g['day'], pending_first=True, limit=10, offset=10)
    last = directory.orders(actor, start=g['day'], end=g['day'], pending_first=True, limit=10, offset=20)
    seen = {row['order_id'] for row in first + second + last}
    assert len(seen) < len(created)


def test_listing_revision_detects_creation_and_status_changes(concurrent_env):
    engine, g, orders, actor = concurrent_env
    directory = BusinessService(sessionmaker(bind=engine))
    created = [orders.create_pending(actor, request(g)) for _ in range(21)]
    kwargs = {"start": g['day'], "end": g['day'], "limit": 10}
    first = directory.orders_page(actor, **kwargs)
    revision = first['revision']
    pages = [first] + [directory.orders_page(actor, **kwargs, offset=n, revision=revision) for n in (10, 20)]
    ids = [row['order_id'] for page in pages for row in page['orders']]
    assert len(ids) == len(set(ids)) == 21
    assert ids == [item.order_id for item in reversed(created)]
    with pytest.raises(OrderError): directory.orders_page(actor, **kwargs, offset=10)
    with pytest.raises(OrderError): directory.orders_page(actor, **kwargs, offset=10, revision='bad')
    with pytest.raises(Conflict): directory.orders_page(actor, **kwargs, offset=10, revision='0' * 64)
    with pytest.raises(Conflict): directory.orders_page(actor, **kwargs, offset=10, revision=revision, received=False)
    with pytest.raises(Conflict): directory.orders_page(actor, start=None, end=None, limit=10, offset=10, revision=revision)
    marked = orders.mark_received(actor, created[-1].order_id, created[-1].version)
    with pytest.raises(Conflict): directory.orders_page(actor, **kwargs, offset=10, revision=revision)
    revision = directory.orders_page(actor, **kwargs)['revision']
    orders.reverse_received(actor, marked.order_id, marked.version, Correction('mistaken_click', True))
    with pytest.raises(Conflict): directory.orders_page(actor, **kwargs, offset=10, revision=revision)
    revision = directory.orders_page(actor, **kwargs)['revision']
    orders.create_pending(actor, request(g))
    with pytest.raises(Conflict): directory.orders_page(actor, **kwargs, offset=10, revision=revision)


def test_listing_snapshot_survives_write_between_revision_and_page_query(concurrent_env):
    engine, g, orders, actor = concurrent_env
    directory = BusinessService(sessionmaker(bind=engine))
    created = [orders.create_pending(actor, request(g)) for _ in range(3)]
    checked, release = Event(), Event()
    def pause_after_revision(connection, cursor, statement, parameters, context, executemany):
        if 'string_agg' in statement:
            checked.set()
            assert release.wait(10)
    event.listen(engine, 'after_cursor_execute', pause_after_revision)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(directory.orders_page, actor, start=g['day'], end=g['day'], limit=2)
            assert checked.wait(10)
            orders.mark_received(actor, created[-1].order_id, 1)
            release.set()
            page = result.result(timeout=10)
        assert page['orders'][0]['order_id'] == created[-1].order_id
        assert page['orders'][0]['is_received'] is False
    finally:
        release.set()
        event.remove(engine, 'after_cursor_execute', pause_after_revision)
    with pytest.raises(Conflict):
        directory.orders_page(actor, start=g['day'], end=g['day'], limit=2, offset=2, revision=page['revision'])


def test_status_filter_invalidates_when_order_leaves_or_enters(concurrent_env):
    engine, g, orders, actor = concurrent_env
    directory = BusinessService(sessionmaker(bind=engine))
    created = [orders.create_pending(actor, request(g)) for _ in range(2)]
    query = {"start": g['day'], "end": g['day'], "received": False, "limit": 1}
    first = directory.orders_page(actor, **query)
    marked = orders.mark_received(actor, created[0].order_id, 1)
    with pytest.raises(Conflict):
        directory.orders_page(actor, **query, offset=1, revision=first['revision'])
    next_revision = directory.orders_page(actor, **query)['revision']
    orders.reverse_received(actor, marked.order_id, marked.version, Correction('mistaken_click', True))
    with pytest.raises(Conflict):
        directory.orders_page(actor, **query, offset=1, revision=next_revision)


@pytest.mark.parametrize('role', ['admin', 'assistant_admin'])
def test_listing_page_http_auth_and_compatibility(auth_env, role):
    engine, g, _, _, password, _, runtime = auth_env
    with engine.begin() as connection:
        sql(connection, "UPDATE users SET role_code=:role WHERE id=:id", role=role, id=g['actor'])
    with client(runtime) as c:
        assert c.get('/api/orders/page').status_code == 401
        login_http(c, password)
        page = c.get('/api/orders/page?limit=1')
        assert page.status_code == 200 and len(page.json()['revision']) == 64
        assert c.get('/api/orders?limit=1').status_code == 200
        assert c.get('/api/orders/page?offset=1').status_code == 422
        assert c.get('/api/orders/page?offset=1&revision=invalid').status_code == 422
        assert c.get('/api/orders/page?offset=1&revision=' + '0' * 64).status_code == 409


def test_pending_first_across_pages_and_current_date_overview(concurrent_env):
    engine, g, orders, actor = concurrent_env
    directory = BusinessService(sessionmaker(bind=engine))
    created = [orders.create_pending(actor, request(g)) for _ in range(25)]
    marked = [orders.mark_received(actor, order.order_id, order.version) for order in created[:8]]
    pages = [directory.orders(actor, start=g["day"], end=g["day"], pending_first=True, limit=10, offset=offset)
             for offset in (0, 10, 20)]
    rows = sum(pages, [])
    assert len(rows) == 25 and len({row["order_id"] for row in rows}) == 25
    assert [row["is_received"] for row in rows] == [False] * 17 + [True] * 8
    assert directory.order_overview(actor, g["day"]) == {"pending": 17, "received": 8, "total": 25, "recognized_sales": Decimal("1960")}
    orders.reverse_received(actor, marked[0].order_id, marked[0].version, Correction("mistaken_click", True))
    assert directory.order_overview(actor, g["day"]) == {"pending": 18, "received": 7, "total": 25, "recognized_sales": Decimal("1715")}


def test_overview_and_visitors_are_protected_and_distinguish_names(auth_env):
    _, g, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        assert c.get(f'/api/orders/overview?day={g["day"]}').status_code == 401
        h = headers(login_http(c, password).json()["csrf_token"])
        overview = c.get(f'/api/orders/overview?day={g["day"]}')
        assert overview.status_code == 200 and overview.json()["total"] == 0
        first = c.post('/api/visitors', headers=h, json={"display_name": "Synthetic Same"}).json()
        second = c.post('/api/visitors', headers=h, json={"display_name": "Synthetic Same"}).json()
        assert first['id'] != second['id']
        assert [row['id'] for row in c.get('/api/visitors?q=Synthetic%20Same').json()] == [first['id'], second['id']]


@pytest.mark.parametrize("role", ["admin", "assistant_admin"])
def test_edit_delete_dishes_and_visitors_preserve_references_and_audit(auth_env, role):
    engine, g, orders, _, password, _, runtime = auth_env
    with engine.begin() as connection:
        sql(connection, "UPDATE users SET role_code=:role WHERE id=:id", role=role, id=g["actor"])
    with client(runtime) as c:
        h = headers(login_http(c, password).json()["csrf_token"])
        visitor = c.post('/api/visitors', headers=h, json={"display_name": "Synthetic Temporary"}).json()
        visitor_url = f'/api/visitors/{visitor["id"]}'
        assert c.patch(visitor_url, headers=h, json={"expected_name": "Synthetic Temporary", "display_name": "Synthetic Updated"}).status_code == 200
        assert c.request('DELETE', visitor_url, headers=h, json={"expected_name": "Synthetic Temporary"}).status_code == 409
        assert c.request('DELETE', visitor_url, headers=h, json={"expected_name": "Synthetic Updated"}).status_code == 204
        dish = c.post('/api/dishes', headers=h, json={"name": "Synthetic Mistake", "category_code": "vegetable"}).json()
        dish_url = f'/api/dishes/{dish["id"]}'
        assert c.patch(dish_url, headers=h, json={"expected_name": dish["name"], "expected_category": "vegetable", "name": "Synthetic Fixed", "category_code": "non_vegetable"}).status_code == 200
        assert c.request('DELETE', dish_url, headers=h, json={"expected_name": "Synthetic Fixed", "expected_category": "non_vegetable"}).status_code == 204
        existing_url = f'/api/dishes/{g["dishes"][0]}'
        assert c.patch(existing_url, headers=h, json={"expected_name": "Synthetic vegetable", "expected_category": "vegetable", "name": "Synthetic Changed", "category_code": "non_vegetable"}).status_code == 200
        saved = c.get(f'/api/menus/{g["menu"]}').json()["items"][0]
        assert saved["item_name"] == "Synthetic vegetable" and saved["category_code"] == "vegetable" and saved["unit_price"] == "50.00"
        assert c.request('DELETE', existing_url, headers=h, json={"expected_name": "Synthetic Changed", "expected_category": "non_vegetable"}).status_code == 204
        assert not any(item["id"] == g["dishes"][0] for item in c.get('/api/dishes?active=true').json())
        assert c.get(f'/api/menus/{g["menu"]}').json()["items"][0] == saved
        order = orders.create_pending(ActorContext(g["actor"]), request(g, employee_number=None, visitor_id=g["visitor"], allocations=(Allocation("finance", Decimal("245")),)))
        original_visitor = f'/api/visitors/{g["visitor"]}'
        assert c.request('DELETE', original_visitor, headers=h, json={"expected_name": "Synthetic Visitor"}).status_code == 409
        assert c.patch(original_visitor, headers=h, json={"expected_name": "Synthetic Visitor", "display_name": "Synthetic Renamed"}).status_code == 200
        assert c.get(f'/api/orders/{order.order_id}').json()["customer_name"] == "Synthetic Visitor"
    with engine.connect() as connection:
        actions = set(sql(connection, "SELECT action FROM audit_events WHERE actor_user_id=:id", id=g["actor"]).scalars())
        assert {"visitor_updated", "visitor_deleted", "dish_updated", "dish_deleted", "dish_deactivated"} <= actions


def test_menu_save_applies_catalog_changes_and_assignment_atomically(auth_env):
    engine, g, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        h = headers(login_http(c, password).json()["csrf_token"])
        before = c.get(f'/api/menus/{g["menu"]}').json()
        original = c.get('/api/dishes?active=true').json()
        target = next(d for d in original if d['id'] == g['dishes'][0])
        body = {"dish_ids": [g['dishes'][1]], "include_default_rice": True,
                "assignments": [{"service_date": g['day'].isoformat(), "expected_menu_id": g['menu']}],
                "dish_changes": [{"id": target['id'], "expected_name": target['name'],
                                  "expected_category": target['category_code'], "delete": True}]}
        stale = {**body, "assignments": [{"service_date": g['day'].isoformat(), "expected_menu_id": None}]}
        assert c.post('/api/menus', headers=h, json=stale).status_code == 409
        assert any(d['id'] == target['id'] for d in c.get('/api/dishes?active=true').json())
        invalid = {**body, "dish_ids": [9223372036854775807]}
        assert c.post('/api/menus', headers=h, json=invalid).status_code == 404
        assert any(d['id'] == target['id'] for d in c.get('/api/dishes?active=true').json())
        response = c.post('/api/menus', headers=h, json=body)
        assert response.status_code == 201
        assert all(item['dish_id'] != target['id'] for item in response.json()['items'])
        assert c.get(f'/api/menus/by-date/{g["day"]}').json()['id'] == response.json()['id']
        assert c.get(f'/api/menus/{g["menu"]}').json() == before
        assert not any(d['id'] == target['id'] for d in c.get('/api/dishes?active=true').json())
    with engine.connect() as connection:
        actions = set(sql(connection, "SELECT action FROM audit_events WHERE actor_user_id=:id", id=g['actor']).scalars())
        assert {'dish_deactivated', 'menu_created', 'menu_date_assigned'} <= actions


def test_menu_save_applies_dish_edit_to_new_menu_only(auth_env):
    _, g, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        h = headers(login_http(c, password).json()["csrf_token"])
        old = c.get(f'/api/menus/{g["menu"]}').json()
        dish = next(d for d in c.get('/api/dishes?active=true').json() if d['id'] == g['dishes'][0])
        body = {"dish_ids": [dish['id']], "include_default_rice": True,
                "assignments": [{"service_date": g['day'].isoformat(), "expected_menu_id": g['menu']}],
                "dish_changes": [{"id": dish['id'], "expected_name": dish['name'],
                                  "expected_category": dish['category_code'], "name": "Synthetic Updated", "category_code": "non_vegetable"}]}
        response = c.post('/api/menus', headers=h, json=body)
        assert response.status_code == 201
        assert any(i['item_name'] == 'Synthetic Updated' and i['category_code'] == 'non_vegetable' for i in response.json()['items'])
        assert c.get(f'/api/menus/{g["menu"]}').json() == old


def test_menu_can_be_replaced_with_only_default_rice(auth_env):
    _, g, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        h = headers(login_http(c, password).json()["csrf_token"])
        old = c.get(f'/api/menus/{g["menu"]}').json()
        body = {"dish_ids": [], "include_default_rice": True,
                "assignments": [{"service_date": g['day'].isoformat(), "expected_menu_id": g['menu']}]}
        response = c.post('/api/menus', headers=h, json=body)
        assert response.status_code == 201
        assert [item['category_code'] for item in response.json()['items']] == ['extra_rice']
        assert c.get(f'/api/menus/by-date/{g["day"]}').json()['id'] == response.json()['id']
        assert c.get(f'/api/menus/{g["menu"]}').json() == old
        assert c.post('/api/menus', headers=h, json={"dish_ids": []}).status_code == 422


def test_received_automatically_balances_existing_visitor_finance(concurrent_env):
    engine, g, orders, actor = concurrent_env
    order = orders.create_pending(actor, request(g, employee_number=None, visitor_id=g['visitor'], allocations=()))
    received = orders.mark_received(actor, order.order_id, order.version)
    assert received.total == Decimal('245')
    with engine.connect() as connection:
        result = sql(connection, "SELECT payment_category_code, amount FROM payment_allocations WHERE order_id=:id", id=order.order_id).one()
        assert result == ('finance', Decimal('245'))
        audit = sql(connection, "SELECT before_values, after_values FROM audit_events WHERE entity_key=:id AND action='received_marked'", id=str(order.order_id)).one()
        assert audit[0]['allocations'] == []
        assert audit[1]['allocations'][0]['amount'] == '245.00'
