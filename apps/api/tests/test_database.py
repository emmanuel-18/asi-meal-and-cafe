"""Synthetic schema tests, not authenticated application workflows."""

from datetime import date
from decimal import Decimal
import hashlib
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from asi_meal_api.db import Base, models
from conftest import alembic_config


def sql(connection, statement, **values):
    return connection.execute(text(statement), values)


def flush_constraints(connection):
    connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
    connection.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED")


def reject(connection, statement, **values):
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            sql(connection, statement, **values)
            flush_constraints(connection)


def graph(connection):
    """Insert a small, explicitly synthetic relationship graph inside a test transaction."""
    token = uuid4().hex
    actor = sql(connection, "INSERT INTO users (login_name,display_name,password_hash,role_code) "
                "VALUES (:login,'Synthetic Admin',:hash,'admin') RETURNING id",
                login=f"synthetic_{token}", hash=hashlib.sha256(token.encode()).hexdigest()).scalar_one()
    job = sql(connection, "INSERT INTO employee_imports "
              "(uploaded_by,source_sha256,encoding,delimiter) VALUES (:actor,:hash,'utf-8',',') RETURNING id",
              actor=actor, hash="0" * 64).scalar_one()
    employee = f"SYN{token}"
    sql(connection, "INSERT INTO employees (employee_number,full_name,last_import_id) "
        "VALUES (:number,'Synthetic Employee',:job)", number=employee, job=job)
    visitor = sql(connection, "INSERT INTO visitors (display_name,created_by) "
                  "VALUES ('Synthetic Visitor',:actor) RETURNING id", actor=actor).scalar_one()
    menu = sql(connection, "INSERT INTO menus (label,created_by) VALUES ('Synthetic Menu',:actor) RETURNING id",
               actor=actor).scalar_one()
    other = sql(connection, "INSERT INTO menus (label,created_by) VALUES ('Other Test Menu',:actor) RETURNING id",
                actor=actor).scalar_one()
    service_date = date(2040, 1, 2)
    sql(connection, "INSERT INTO menu_dates (service_date,menu_id) VALUES (:day,:menu)", day=service_date, menu=menu)
    offerings = []
    dishes = []
    for code, price in [("vegetable", Decimal("50")), ("non_vegetable", Decimal("75")), ("extra_rice", Decimal("15"))]:
        dish = sql(connection, "INSERT INTO dishes (name,category_code) VALUES (:name,:code) RETURNING id",
                   name=f"Synthetic {code}", code=code).scalar_one()
        item = sql(connection, "INSERT INTO menu_items (menu_id,dish_id,item_name,category_code,unit_price) "
                   "VALUES (:menu,:dish,:name,:code,:price) RETURNING id",
                   menu=menu, dish=dish, name=f"Synthetic {code}", code=code, price=price).scalar_one()
        offerings.append(item)
        dishes.append(dish)
    return dict(actor=actor, job=job, employee=employee, visitor=visitor, menu=menu,
                other=other, day=service_date, offerings=offerings, dishes=dishes)


@pytest.fixture
def synthetic(db):
    return graph(db)


def order(connection, g, *, visitor=False, allocations=None):
    order_id = sql(connection, "INSERT INTO orders (request_key,service_date,menu_id,created_by,"
                   "employee_number,visitor_id,customer_name_snapshot) "
                   "VALUES (:key,:day,:menu,:actor,:employee,:visitor,'Synthetic Customer') RETURNING id",
                   key=uuid4(), day=g["day"], menu=g["menu"], actor=g["actor"],
                   employee=None if visitor else g["employee"], visitor=g["visitor"] if visitor else None).scalar_one()
    for line, (source, quantity) in enumerate(zip(g["offerings"], [1, 2, 3]), 1):
        sql(connection, "INSERT INTO order_items (order_id,line_number,source_menu_item_id,item_name,"
            "category_code_snapshot,unit_price,quantity) "
            "SELECT :order,:line,id,item_name,category_code,unit_price,:quantity FROM menu_items WHERE id=:source",
            order=order_id, line=line, source=source, quantity=quantity)
    if allocations is None:
        allocations = [("finance" if visitor else "cash", Decimal("245"))]
    for code, amount in allocations:
        sql(connection, "INSERT INTO payment_allocations (order_id,payment_category_code,amount,created_by,updated_by) "
            "VALUES (:order,:code,:amount,:actor,:actor)", order=order_id, code=code, amount=amount, actor=g["actor"])
    flush_constraints(connection)
    return order_id


def mark(connection, g, order_id, received):
    # Low-level test fixture only: later use cases must derive and authorize actors.
    old = sql(connection, "SELECT is_received FROM orders WHERE id=:id", id=order_id).scalar_one()
    sql(connection, "UPDATE orders SET is_received=:received,receipt_changed_by=:actor,"
        "receipt_changed_at=now(),version=version+1 WHERE id=:id",
        received=received, actor=g["actor"], id=order_id)
    event = sql(connection, "INSERT INTO audit_events (actor_user_id,action,entity_type,entity_key,before_values,after_values) "
                "VALUES (:actor,'receipt_transition','orders',:key,jsonb_build_object('is_received',CAST(:old AS boolean)),"
                "jsonb_build_object('is_received',CAST(:new AS boolean))) RETURNING id",
                actor=g["actor"], key=str(order_id), old=old, new=received).scalar_one()
    sql(connection, "INSERT INTO receipt_events (audit_event_id,order_id,from_received,to_received,"
        "reason_code,reason_label_snapshot) VALUES (:event,:order,:old,:new,:reason,:label)",
        event=event, order=order_id, old=old, new=received,
        reason="mistaken_click" if old else None, label="Mistaken click" if old else None)
    flush_constraints(connection)


def test_schema_objects_and_no_model_migration_drift(db):
    assert set(inspect(db).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    context = MigrationContext.configure(db, opts={"compare_type": True, "compare_server_default": True})
    assert compare_metadata(context, Base.metadata) == []
    triggers = db.exec_driver_sql("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal").scalars().all()
    assert len(triggers) == 10
    assert all(t.startswith("asi_") for t in triggers)


def test_reference_data_is_exact_and_has_no_accounts(db):
    assert dict(db.exec_driver_sql("SELECT code,display_name FROM roles").all()) == {"admin": "Admin", "assistant_admin": "Assistant Admin"}
    assert dict(db.exec_driver_sql("SELECT code,default_unit_price FROM item_categories").all()) == {
        "vegetable": Decimal("50"), "non_vegetable": Decimal("75"), "extra_rice": Decimal("15")}
    assert set(db.exec_driver_sql("SELECT code FROM payment_categories").scalars()) == {"cash", "gcash", "sd", "incentive", "finance"}
    for table in ["users", "employees", "visitors", "orders", "employee_imports"]:
        assert db.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one() == 0


def test_upgrade_downgrade_reupgrade_and_reference_price_survives_head(postgres):
    with postgres.engine.begin() as c:
        # No test business rows are committed by normal tests.
        c.exec_driver_sql("UPDATE item_categories SET default_unit_price=51 WHERE code='vegetable'")
        command.upgrade(alembic_config(c), "head")
        assert c.exec_driver_sql("SELECT default_unit_price FROM item_categories WHERE code='vegetable'").scalar_one() == Decimal("51")
        command.downgrade(alembic_config(c), "base")
        assert set(inspect(c).get_table_names()) == {"alembic_version"}
        assert c.exec_driver_sql("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON p.pronamespace=n.oid "
                                 "WHERE n.nspname='public' AND left(p.proname,4) = 'asi_'").scalar_one() == 0
        command.upgrade(alembic_config(c), "head")
        assert c.exec_driver_sql("SELECT default_unit_price FROM item_categories WHERE code='vegetable'").scalar_one() == Decimal("50")


def test_relationships_and_restrictive_parent_deletion(db, synthetic):
    oid = order(db, synthetic)
    with Session(bind=db, join_transaction_mode="create_savepoint") as session:
        obj = session.get(models.Order, oid)
        assert obj.employee.employee_number == synthetic["employee"]
        assert obj.menu.id == obj.menu_date.menu_id
        assert [i.quantity for i in sorted(obj.items, key=lambda i: i.line_number)] == [1, 2, 3]
        assert sum(i.line_total for i in obj.items) == Decimal("245")
        assert obj.allocations[0].category.code == "cash"
        assert obj.creator.role.code == "admin"
    reject(db, "DELETE FROM employees WHERE employee_number=:number", number=synthetic["employee"])
    reject(db, "DELETE FROM menus WHERE id=:id", id=synthetic["menu"])


@pytest.mark.parametrize("statement", [
    "INSERT INTO roles VALUES ('superuser','Invalid')",
    "INSERT INTO payment_categories VALUES ('for_deposit','Invalid')",
    "UPDATE item_categories SET default_unit_price=-1 WHERE code='vegetable'",
    "UPDATE item_categories SET default_unit_price='NaN'::numeric WHERE code='vegetable'",
])
def test_vocabulary_and_money_constraints(db, statement):
    reject(db, statement)


def test_identity_exclusivity_uniqueness_and_receipt_metadata(db, synthetic):
    oid = order(db, synthetic)
    # Identity edits are blocked even while Pending; creating an invalid XOR also fails.
    reject(db, "UPDATE orders SET visitor_id=:visitor WHERE id=:id", visitor=synthetic["visitor"], id=oid)
    reject(db, "INSERT INTO orders (request_key,service_date,menu_id,created_by,customer_name_snapshot) "
           "VALUES (:key,:day,:menu,:actor,'Synthetic')",
           key=uuid4(), day=synthetic["day"], menu=synthetic["menu"], actor=synthetic["actor"])
    reject(db, "UPDATE orders SET is_received=true WHERE id=:id", id=oid)
    reject(db, "UPDATE orders SET version=0 WHERE id=:id", id=oid)
    reject(db, "INSERT INTO users (login_name,display_name,password_hash,role_code) "
           "SELECT upper(login_name),'Synthetic','fixture-hash','admin' FROM users WHERE id=:id", id=synthetic["actor"])
    reject(db, "INSERT INTO employees (employee_number,full_name,last_import_id) "
           "VALUES (:number,'Duplicate Synthetic',:job)", number=synthetic["employee"], job=synthetic["job"])


def test_nonempty_quantity_and_allocation_constraints(db, synthetic):
    oid = order(db, synthetic)
    reject(db, "DELETE FROM order_items WHERE order_id=:id", id=oid)
    reject(db, "UPDATE order_items SET quantity=0 WHERE order_id=:id", id=oid)
    reject(db, "UPDATE payment_allocations SET amount=0 WHERE order_id=:id", id=oid)
    reject(db, "UPDATE payment_allocations SET amount='NaN'::numeric WHERE order_id=:id", id=oid)
    reject(db, "INSERT INTO payment_allocations (order_id,payment_category_code,amount,created_by,updated_by) "
           "VALUES (:id,'cash',1,:actor,:actor)", id=oid, actor=synthetic["actor"])


def test_visitor_finance_only_and_names_not_unique(db, synthetic):
    order(db, synthetic, visitor=True)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            order(db, synthetic, visitor=True, allocations=[("cash", Decimal("245"))])
    sql(db, "INSERT INTO visitors (display_name,created_by) VALUES ('Synthetic Visitor',:actor)", actor=synthetic["actor"])


def test_received_balance_snapshot_guards_and_current_state(db, synthetic):
    oid = order(db, synthetic, allocations=[("gcash", Decimal("200")), ("cash", Decimal("45"))])
    assert sql(db, "SELECT sum(line_total) FROM order_items WHERE order_id=:id", id=oid).scalar_one() == Decimal("245")
    mark(db, synthetic, oid, True)
    reject(db, "UPDATE order_items SET quantity=2 WHERE order_id=:id", id=oid)
    reject(db, "DELETE FROM payment_allocations WHERE order_id=:id", id=oid)
    mark(db, synthetic, oid, False)
    assert not sql(db, "SELECT is_received FROM orders WHERE id=:id", id=oid).scalar_one()
    reject(db, "UPDATE order_items SET unit_price=1 WHERE order_id=:id", id=oid)
    sql(db, "UPDATE payment_allocations SET amount=40 WHERE order_id=:id AND payment_category_code='cash'", id=oid)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            mark(db, synthetic, oid, True)
    sql(db, "UPDATE payment_allocations SET amount=45 WHERE order_id=:id AND payment_category_code='cash'", id=oid)
    mark(db, synthetic, oid, True)
    assert sql(db, "SELECT count(*) FROM receipt_events WHERE order_id=:id", id=oid).scalar_one() == 3
    assert dict(sql(db, "SELECT payment_category_code,amount FROM payment_allocations WHERE order_id=:id", id=oid).all()) == {
        "cash": Decimal("45"), "gcash": Decimal("200")}


def test_menu_provenance_and_retained_categories(db, synthetic):
    oid = order(db, synthetic)
    reject(db, "UPDATE orders SET menu_id=:other WHERE id=:id", other=synthetic["other"], id=oid)
    reject(db, "UPDATE orders SET service_date='2040-01-03' WHERE id=:id", id=oid)
    reject(db, "UPDATE menu_items SET menu_id=:other WHERE id=:id", other=synthetic["other"], id=synthetic["offerings"][0])
    sql(db, "UPDATE dishes SET category_code='non_vegetable' WHERE id=:id", id=synthetic["dishes"][0])
    assert sql(db, "SELECT category_code FROM menu_items WHERE id=:id", id=synthetic["offerings"][0]).scalar_one() == "vegetable"
    sql(db, "UPDATE menu_items SET category_code='non_vegetable',unit_price=75 WHERE id=:id", id=synthetic["offerings"][0])
    sql(db, "UPDATE menu_dates SET menu_id=:menu WHERE service_date=:day", menu=synthetic["other"], day=synthetic["day"])
    sql(db, "UPDATE employees SET full_name='Renamed Synthetic' WHERE employee_number=:number", number=synthetic["employee"])
    assert sql(db, "SELECT menu_id,customer_name_snapshot FROM orders WHERE id=:id", id=oid).one() == (synthetic["menu"], "Synthetic Customer")
    assert sql(db, "SELECT category_code_snapshot,unit_price FROM order_items WHERE order_id=:id AND line_number=1", id=oid).one() == ("vegetable", Decimal("50"))
    # New orders must follow today's assignment, not a stale UI selection.
    reject(db, "INSERT INTO orders (request_key,service_date,menu_id,created_by,employee_number,customer_name_snapshot) "
           "VALUES (:key,:day,:old,:actor,:number,'Synthetic')", key=uuid4(), day=synthetic["day"],
           old=synthetic["menu"], actor=synthetic["actor"], number=synthetic["employee"])


def test_wrong_menu_item_and_category_are_rejected(db, synthetic):
    oid = order(db, synthetic)
    other_dish = sql(db, "INSERT INTO dishes (name,category_code) VALUES ('Synthetic Other','vegetable') RETURNING id").scalar_one()
    reject(db, "INSERT INTO menu_items (menu_id,dish_id,item_name,category_code,unit_price) "
           "VALUES (:menu,:dish,'Synthetic','non_vegetable',75)", menu=synthetic["other"], dish=other_dish)
    other_item = sql(db, "INSERT INTO menu_items (menu_id,dish_id,item_name,category_code,unit_price) "
                     "VALUES (:menu,:dish,'Synthetic Other','vegetable',50) RETURNING id",
                     menu=synthetic["other"], dish=other_dish).scalar_one()
    reject(db, "INSERT INTO order_items (order_id,line_number,source_menu_item_id,item_name,category_code_snapshot,unit_price,quantity) "
           "VALUES (:order,4,:source,'Synthetic Other','vegetable',50,1)", order=oid, source=other_item)


def test_import_results_are_structured_and_validated(db, synthetic):
    job = synthetic["job"]
    sql(db, "INSERT INTO employee_import_rows (import_id,row_number,employee_number,outcome) VALUES (:job,1,:number,'inserted')",
        job=job, number=synthetic["employee"])
    sql(db, "INSERT INTO employee_import_rows (import_id,row_number,outcome,issues) "
        "VALUES (:job,2,'rejected','[{\"field\":\"employee_number\",\"code\":\"missing\"}]'::jsonb)", job=job)
    reject(db, "INSERT INTO employee_import_rows (import_id,row_number,outcome) VALUES (:job,2,'rejected')", job=job)
    reject(db, "INSERT INTO employee_import_rows (import_id,row_number,outcome) VALUES (:job,3,'eligible')", job=job)
    reject(db, "UPDATE employee_imports SET status='completed',completed_at=now(),total_rows=2 WHERE id=:id", id=job)
    sql(db, "UPDATE employee_imports SET status='completed',completed_at=now(),total_rows=2,inserted_rows=1,rejected_rows=1 WHERE id=:id", id=job)


def test_audit_atomicity_reasons_and_immutable_history(db, synthetic):
    oid = order(db, synthetic)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            sql(db, "UPDATE orders SET is_received=true,receipt_changed_by=:actor,receipt_changed_at=now() WHERE id=:id", actor=synthetic["actor"], id=oid)
            sql(db, "INSERT INTO audit_events (actor_user_id,action,entity_type,entity_key) VALUES (-1,'invalid','orders',:key)", key=str(oid))
    assert not sql(db, "SELECT is_received FROM orders WHERE id=:id", id=oid).scalar_one()
    mark(db, synthetic, oid, True)
    mark(db, synthetic, oid, False)
    reject(db, "UPDATE audit_events SET action='rewritten'")
    reject(db, "DELETE FROM receipt_events WHERE order_id=:id", id=oid)
    event = sql(db, "INSERT INTO audit_events (actor_user_id,action,entity_type,entity_key) "
                "VALUES (:actor,'receipt_correction','orders',:key) RETURNING id", actor=synthetic["actor"], key=str(oid)).scalar_one()
    reject(db, "INSERT INTO receipt_events (audit_event_id,order_id,from_received,to_received,reason_code,reason_label_snapshot,reason_explanation) "
           "VALUES (:event,:order,true,false,'other','Other reason',E' \\t\\n')", event=event, order=oid)
    sql(db, "INSERT INTO receipt_events (audit_event_id,order_id,from_received,to_received,reason_code,reason_label_snapshot,reason_explanation) "
        "VALUES (:event,:order,true,false,'retired_demo_reason','Historical label','Synthetic explanation')", event=event, order=oid)
    assert sql(db, "SELECT reason_label_snapshot FROM receipt_events WHERE audit_event_id=:id", id=event).scalar_one() == "Historical label"


def cleanup_graph(connection, g, oid):
    for table in ["payment_allocations", "order_items"]:
        sql(connection, f"DELETE FROM {table} WHERE order_id=:id", id=oid)
    sql(connection, "DELETE FROM orders WHERE id=:id", id=oid)
    sql(connection, "DELETE FROM employees WHERE employee_number=:number", number=g["employee"])
    sql(connection, "DELETE FROM visitors WHERE id=:id", id=g["visitor"])
    sql(connection, "DELETE FROM menu_dates WHERE service_date=:day", day=g["day"])
    for menu in [g["menu"], g["other"]]:
        sql(connection, "DELETE FROM menu_items WHERE menu_id=:id", id=menu)
        sql(connection, "DELETE FROM menus WHERE id=:id", id=menu)
    for dish in g["dishes"]:
        sql(connection, "DELETE FROM dishes WHERE id=:id", id=dish)
    sql(connection, "DELETE FROM employee_imports WHERE id=:id", id=g["job"])
    sql(connection, "DELETE FROM users WHERE id=:id", id=g["actor"])


def test_concurrent_order_lock_and_date_assignment_isolation(postgres):
    # Committed synthetic graph permits genuinely separate PostgreSQL sessions.
    with postgres.engine.begin() as c:
        g = graph(c)
        oid = order(c, g)
    try:
        with postgres.engine.connect() as first, postgres.engine.connect() as second:
            t1 = first.begin()
            try:
                sql(first, "UPDATE orders SET is_received=true,receipt_changed_by=:actor,receipt_changed_at=now() WHERE id=:id", actor=g["actor"], id=oid)
                with pytest.raises(OperationalError) as error:
                    with second.begin():
                        second.exec_driver_sql("SET LOCAL lock_timeout='250ms'")
                        sql(second, "UPDATE payment_allocations SET amount=200 WHERE order_id=:id", id=oid)
                assert error.value.orig.sqlstate == "55P03"
            finally:
                t1.rollback()
            t2 = first.begin()
            try:
                # INSERT guard itself holds the assignment lock; no app workflow used.
                order(first, g)
                with pytest.raises(OperationalError) as error:
                    with second.begin():
                        second.exec_driver_sql("SET LOCAL lock_timeout='250ms'")
                        sql(second, "UPDATE menu_dates SET menu_id=:other WHERE service_date=:day", other=g["other"], day=g["day"])
                assert error.value.orig.sqlstate == "55P03"
            finally:
                t2.rollback()
    finally:
        with postgres.engine.begin() as c:
            cleanup_graph(c, g, oid)
