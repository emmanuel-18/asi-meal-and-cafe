-- Candidate only: never run on development without separate owner approval.
-- Provision asi_meal_runtime NOLOGIN and a separate LOGIN first. No passwords.
-- Reapply/review explicitly after migrations; no broad future-object grants.
BEGIN;
DO $$
BEGIN
  IF current_database() <> 'asi_meal_dev'
     AND current_database() !~ '^restore_[0-9a-f]{32}$' THEN
    RAISE EXCEPTION 'Not the approved development or disposable restore database';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='asi_meal_runtime'
      AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
      AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls) THEN
    RAISE EXCEPTION 'Expected unprivileged NOLOGIN runtime group';
  END IF;
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO asi_meal_runtime', current_database());
END $$;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO asi_meal_runtime;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, asi_meal_runtime;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, asi_meal_runtime;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, asi_meal_runtime;

-- Revision read is also used by the existing backup snapshot manifest.
GRANT SELECT ON alembic_version, roles, users, auth_sessions, employees, employee_imports,
  employee_import_rows, visitors, item_categories, dishes, menus, menu_dates,
  menu_items, payment_categories, orders, order_items, payment_allocations,
  audit_events, receipt_events TO asi_meal_runtime;
GRANT INSERT ON users, auth_sessions, employees, employee_imports,
  employee_import_rows, visitors, dishes, menus, menu_dates, menu_items, orders,
  order_items, payment_allocations, audit_events, receipt_events TO asi_meal_runtime;
GRANT DELETE ON auth_sessions, visitors, dishes, order_items, payment_allocations TO asi_meal_runtime;

GRANT UPDATE (login_name, display_name, password_hash, role_code, is_enabled,
  password_change_required, updated_at) ON users TO asi_meal_runtime;
GRANT UPDATE (last_seen_at, revoked_at) ON auth_sessions TO asi_meal_runtime;
GRANT UPDATE (full_name, position, campaign, line_of_business, last_import_id,
  updated_at) ON employees TO asi_meal_runtime;
GRANT UPDATE (status, completed_at, total_rows, inserted_rows, updated_rows,
  unchanged_rows, rejected_rows, file_error_code) ON employee_imports TO asi_meal_runtime;
GRANT UPDATE (display_name, updated_at) ON visitors TO asi_meal_runtime;
GRANT UPDATE (name, category_code, is_active, updated_at) ON dishes TO asi_meal_runtime;
GRANT UPDATE (menu_id) ON menu_dates TO asi_meal_runtime;
GRANT UPDATE (is_received, receipt_changed_by, receipt_changed_at, version) ON orders TO asi_meal_runtime;
GRANT UPDATE (quantity) ON order_items TO asi_meal_runtime;
GRANT UPDATE (amount, updated_by, updated_at) ON payment_allocations TO asi_meal_runtime;

-- SELECT FOR UPDATE/SHARE needs UPDATE on at least one column, even for reads.
-- No category-price or offering-price UPDATE is granted.
GRANT UPDATE (display_name) ON item_categories TO asi_meal_runtime;
GRANT UPDATE (updated_at) ON menus TO asi_meal_runtime;
GRANT UPDATE (id) ON menu_items TO asi_meal_runtime;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO asi_meal_runtime;
COMMIT;
