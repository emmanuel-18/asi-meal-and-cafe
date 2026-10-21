-- Frozen Stage 1 integrity functions. Human authorization/audit writes belong
-- to later authenticated use cases; these guards do not impersonate an actor.
CREATE FUNCTION asi_guard_order() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE assigned_menu bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT menu_id INTO assigned_menu FROM menu_dates
          WHERE service_date = NEW.service_date FOR UPDATE;
        IF NOT FOUND OR assigned_menu <> NEW.menu_id THEN
            RAISE EXCEPTION 'Order date/menu mismatch' USING ERRCODE = '23514';
        END IF;
        PERFORM id FROM menus WHERE id = NEW.menu_id FOR UPDATE;
        IF NEW.is_received THEN
            RAISE EXCEPTION 'Orders must be recorded Pending' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF ROW(NEW.employee_number, NEW.visitor_id, NEW.service_date, NEW.menu_id,
               NEW.customer_name_snapshot, NEW.position_snapshot,
               NEW.campaign_snapshot, NEW.line_of_business_snapshot,
               NEW.created_by, NEW.recorded_at, NEW.request_key, NEW.id)
           IS DISTINCT FROM
           ROW(OLD.employee_number, OLD.visitor_id, OLD.service_date, OLD.menu_id,
               OLD.customer_name_snapshot, OLD.position_snapshot,
               OLD.campaign_snapshot, OLD.line_of_business_snapshot,
               OLD.created_by, OLD.recorded_at, OLD.request_key, OLD.id) THEN
            RAISE EXCEPTION 'Recorded order identity and provenance are immutable'
              USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER asi_order_guard BEFORE INSERT OR UPDATE ON orders
FOR EACH ROW EXECUTE FUNCTION asi_guard_order();

CREATE FUNCTION asi_guard_order_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent orders%ROWTYPE; offering menu_items%ROWTYPE; parent_id bigint;
BEGIN
    IF TG_OP = 'UPDATE' AND (NEW.order_id <> OLD.order_id OR NEW.id <> OLD.id) THEN
        RAISE EXCEPTION 'Order children cannot be reparented' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN parent_id := OLD.order_id;
    ELSE parent_id := NEW.order_id;
    END IF;
    SELECT * INTO parent FROM orders WHERE id = parent_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Missing parent order' USING ERRCODE = '23503';
    END IF;
    IF parent.is_received THEN
        RAISE EXCEPTION 'Reverse Received before editing items or allocations'
          USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'order_items' THEN
        IF TG_OP = 'UPDATE' AND
            ROW(NEW.source_menu_item_id, NEW.item_name, NEW.category_code_snapshot, NEW.unit_price)
            IS DISTINCT FROM
            ROW(OLD.source_menu_item_id, OLD.item_name, OLD.category_code_snapshot, OLD.unit_price) THEN
            RAISE EXCEPTION 'Replace a Pending line; do not override its snapshots'
              USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' THEN
            PERFORM id FROM menus WHERE id = parent.menu_id FOR UPDATE;
            SELECT * INTO offering FROM menu_items WHERE id = NEW.source_menu_item_id FOR SHARE;
            IF NOT FOUND OR offering.menu_id <> parent.menu_id THEN
                RAISE EXCEPTION 'Offering is outside recorded menu' USING ERRCODE = '23514';
            END IF;
            IF ROW(NEW.item_name, NEW.category_code_snapshot, NEW.unit_price)
               IS DISTINCT FROM ROW(offering.item_name, offering.category_code, offering.unit_price) THEN
                RAISE EXCEPTION 'New line snapshots must match selected offering'
                  USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER asi_item_guard BEFORE INSERT OR UPDATE OR DELETE ON order_items
FOR EACH ROW EXECUTE FUNCTION asi_guard_order_child();
CREATE TRIGGER asi_allocation_guard BEFORE INSERT OR UPDATE OR DELETE ON payment_allocations
FOR EACH ROW EXECUTE FUNCTION asi_guard_order_child();

CREATE FUNCTION asi_validate_order() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_id bigint; parent orders%ROWTYPE; item_count bigint;
        allocation_count bigint; items_total numeric; allocated_total numeric;
BEGIN
    IF TG_TABLE_NAME = 'orders' THEN parent_id := NEW.id;
    ELSIF TG_OP = 'DELETE' THEN parent_id := OLD.order_id;
    ELSE parent_id := NEW.order_id;
    END IF;
    SELECT * INTO parent FROM orders WHERE id = parent_id FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT count(*), COALESCE(sum(line_total), 0) INTO item_count, items_total
      FROM order_items WHERE order_id = parent_id;
    IF item_count = 0 THEN
        RAISE EXCEPTION 'Committed orders require an item' USING ERRCODE = '23514';
    END IF;
    IF parent.visitor_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM payment_allocations
        WHERE order_id = parent_id AND payment_category_code <> 'finance'
    ) THEN
        RAISE EXCEPTION 'Visitor allocations must use Finance' USING ERRCODE = '23514';
    END IF;
    IF parent.is_received THEN
        SELECT count(*), COALESCE(sum(amount), 0) INTO allocation_count, allocated_total
          FROM payment_allocations WHERE order_id = parent_id;
        IF allocation_count = 0 OR allocated_total <> items_total THEN
            RAISE EXCEPTION 'Received allocations must equal item totals'
              USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER asi_order_totals AFTER INSERT OR UPDATE ON orders
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION asi_validate_order();
CREATE CONSTRAINT TRIGGER asi_item_totals AFTER INSERT OR UPDATE OR DELETE ON order_items
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION asi_validate_order();
CREATE CONSTRAINT TRIGGER asi_allocation_totals AFTER INSERT OR UPDATE OR DELETE ON payment_allocations
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION asi_validate_order();

CREATE FUNCTION asi_guard_offering() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE dish_category text;
BEGIN
    IF TG_OP = 'UPDATE' AND (NEW.menu_id <> OLD.menu_id OR NEW.dish_id <> OLD.dish_id)
       AND EXISTS (SELECT 1 FROM order_items WHERE source_menu_item_id = OLD.id) THEN
        RAISE EXCEPTION 'Referenced offering provenance cannot move'
          USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' OR
       ROW(NEW.category_code, NEW.dish_id) IS DISTINCT FROM ROW(OLD.category_code, OLD.dish_id) THEN
        SELECT category_code INTO dish_category FROM dishes WHERE id = NEW.dish_id FOR SHARE;
        IF NOT FOUND OR NEW.category_code <> dish_category THEN
            RAISE EXCEPTION 'Offering category must match dish on creation/reclassification'
              USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER asi_offering_guard BEFORE INSERT OR UPDATE ON menu_items
FOR EACH ROW EXECUTE FUNCTION asi_guard_offering();

CREATE FUNCTION asi_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Audit and receipt history is append-only' USING ERRCODE = '23514';
END $$;
CREATE TRIGGER asi_audit_immutable BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION asi_history_immutable();
CREATE TRIGGER asi_receipt_immutable BEFORE UPDATE OR DELETE ON receipt_events
FOR EACH ROW EXECUTE FUNCTION asi_history_immutable();

CREATE FUNCTION asi_receipt_target() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE audit audit_events%ROWTYPE;
BEGIN
    SELECT * INTO audit FROM audit_events WHERE id = NEW.audit_event_id;
    IF NOT FOUND OR audit.entity_type <> 'orders' OR audit.entity_key <> NEW.order_id::text THEN
        RAISE EXCEPTION 'Receipt audit must identify the same order' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER asi_receipt_target_guard BEFORE INSERT ON receipt_events
FOR EACH ROW EXECUTE FUNCTION asi_receipt_target();
