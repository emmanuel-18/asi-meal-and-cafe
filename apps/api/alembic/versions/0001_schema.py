"""Initial 17-table schema. Frozen independently of future ORM changes."""
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('item_categories',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('display_name', sa.Text(), nullable=False),
    sa.Column('default_unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.CheckConstraint("btrim(display_name) <> ''", name=op.f('ck_item_categories_display_name_nonblank')),
    sa.CheckConstraint("code IN ('vegetable','non_vegetable','extra_rice')", name=op.f('ck_item_categories_code_allowed')),
    sa.CheckConstraint("default_unit_price >= 0 AND default_unit_price <> 'NaN'::numeric", name=op.f('ck_item_categories_default_unit_price_valid')),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_item_categories'))
    )
    op.create_table('payment_categories',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('display_name', sa.Text(), nullable=False),
    sa.CheckConstraint("btrim(display_name) <> ''", name=op.f('ck_payment_categories_display_name_nonblank')),
    sa.CheckConstraint("code IN ('cash','gcash','sd','incentive','finance')", name=op.f('ck_payment_categories_code_allowed')),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_payment_categories'))
    )
    op.create_table('roles',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('display_name', sa.Text(), nullable=False),
    sa.CheckConstraint("btrim(display_name) <> ''", name=op.f('ck_roles_display_name_nonblank')),
    sa.CheckConstraint("code IN ('admin', 'assistant_admin')", name=op.f('ck_roles_code_allowed')),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_roles'))
    )
    op.create_table('dishes',
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('category_code', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(name) <> ''", name=op.f('ck_dishes_name_nonblank')),
    sa.ForeignKeyConstraint(['category_code'], ['item_categories.code'], name=op.f('fk_dishes_category_code_item_categories'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dishes'))
    )
    op.create_table('users',
    sa.Column('login_name', sa.Text(), nullable=False),
    sa.Column('display_name', sa.Text(), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('role_code', sa.Text(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(display_name) <> ''", name=op.f('ck_users_display_name_nonblank')),
    sa.CheckConstraint("btrim(login_name) <> ''", name=op.f('ck_users_login_name_nonblank')),
    sa.CheckConstraint("btrim(password_hash) <> ''", name=op.f('ck_users_password_hash_nonblank')),
    sa.ForeignKeyConstraint(['role_code'], ['roles.code'], name=op.f('fk_users_role_code_roles'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index('uq_users_login_normalized', 'users', [sa.literal_column('lower(btrim(login_name))')], unique=True)
    op.create_table('audit_events',
    sa.Column('actor_user_id', sa.BigInteger(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('entity_type', sa.Text(), nullable=False),
    sa.Column('entity_key', sa.Text(), nullable=False),
    sa.Column('before_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.CheckConstraint("btrim(action) <> ''", name=op.f('ck_audit_events_action_nonblank')),
    sa.CheckConstraint("btrim(entity_key) <> ''", name=op.f('ck_audit_events_entity_key_nonblank')),
    sa.CheckConstraint("btrim(entity_type) <> ''", name=op.f('ck_audit_events_entity_type_nonblank')),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_audit_events_actor_user_id_users'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index('ix_audit_events_entity_time', 'audit_events', ['entity_type', 'entity_key', 'occurred_at'], unique=False)
    op.create_table('employee_imports',
    sa.Column('uploaded_by', sa.BigInteger(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_sha256', sa.Text(), nullable=False),
    sa.Column('encoding', sa.Text(), nullable=False),
    sa.Column('delimiter', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='processing', nullable=False),
    sa.Column('total_rows', sa.Integer(), server_default='0', nullable=False),
    sa.Column('inserted_rows', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_rows', sa.Integer(), server_default='0', nullable=False),
    sa.Column('unchanged_rows', sa.Integer(), server_default='0', nullable=False),
    sa.Column('rejected_rows', sa.Integer(), server_default='0', nullable=False),
    sa.Column('file_error_code', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.CheckConstraint("(status = 'processing' AND completed_at IS NULL) OR (status IN ('completed', 'failed') AND completed_at IS NOT NULL)", name=op.f('ck_employee_imports_completion_metadata')),
    sa.CheckConstraint("btrim(encoding) <> ''", name=op.f('ck_employee_imports_encoding_nonblank')),
    sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_employee_imports_hash_format')),
    sa.CheckConstraint("status <> 'completed' OR total_rows = inserted_rows + updated_rows + unchanged_rows + rejected_rows", name=op.f('ck_employee_imports_completed_counts')),
    sa.CheckConstraint("status IN ('processing', 'completed', 'failed')", name=op.f('ck_employee_imports_status_allowed')),
    sa.CheckConstraint('length(delimiter) = 1', name=op.f('ck_employee_imports_delimiter_length')),
    sa.CheckConstraint('total_rows >= 0 AND inserted_rows >= 0 AND updated_rows >= 0 AND unchanged_rows >= 0 AND rejected_rows >= 0', name=op.f('ck_employee_imports_counts_nonnegative')),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_employee_imports_uploaded_by_users'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employee_imports'))
    )
    op.create_table('menus',
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_menus_created_by_users'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_menus'))
    )
    op.create_table('visitors',
    sa.Column('display_name', sa.Text(), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(display_name) <> ''", name=op.f('ck_visitors_display_name_nonblank')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_visitors_created_by_users'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_visitors'))
    )
    op.create_table('employees',
    sa.Column('employee_number', sa.Text(), nullable=False),
    sa.Column('full_name', sa.Text(), nullable=False),
    sa.Column('position', sa.Text(), nullable=True),
    sa.Column('campaign', sa.Text(), nullable=True),
    sa.Column('line_of_business', sa.Text(), nullable=True),
    sa.Column('last_import_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(employee_number) <> ''", name=op.f('ck_employees_employee_number_nonblank')),
    sa.CheckConstraint("btrim(full_name) <> ''", name=op.f('ck_employees_full_name_nonblank')),
    sa.ForeignKeyConstraint(['last_import_id'], ['employee_imports.id'], name=op.f('fk_employees_last_import_id_employee_imports'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('employee_number', name=op.f('pk_employees'))
    )
    op.create_table('menu_dates',
    sa.Column('service_date', sa.Date(), nullable=False),
    sa.Column('menu_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['menu_id'], ['menus.id'], name=op.f('fk_menu_dates_menu_id_menus'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('service_date', name=op.f('pk_menu_dates'))
    )
    op.create_index('ix_menu_dates_menu_id', 'menu_dates', ['menu_id'], unique=False)
    op.create_table('menu_items',
    sa.Column('menu_id', sa.BigInteger(), nullable=False),
    sa.Column('dish_id', sa.BigInteger(), nullable=False),
    sa.Column('item_name', sa.Text(), nullable=False),
    sa.Column('category_code', sa.Text(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.CheckConstraint("btrim(item_name) <> ''", name=op.f('ck_menu_items_item_name_nonblank')),
    sa.CheckConstraint("unit_price >= 0 AND unit_price <> 'NaN'::numeric", name=op.f('ck_menu_items_unit_price_valid')),
    sa.ForeignKeyConstraint(['category_code'], ['item_categories.code'], name=op.f('fk_menu_items_category_code_item_categories'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['dish_id'], ['dishes.id'], name=op.f('fk_menu_items_dish_id_dishes'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['menu_id'], ['menus.id'], name=op.f('fk_menu_items_menu_id_menus'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_menu_items')),
    sa.UniqueConstraint('menu_id', 'dish_id', name=op.f('uq_menu_items_menu_id'))
    )
    op.create_index('ix_menu_items_dish_id', 'menu_items', ['dish_id'], unique=False)
    op.create_table('employee_import_rows',
    sa.Column('import_id', sa.BigInteger(), nullable=False),
    sa.Column('row_number', sa.Integer(), nullable=False),
    sa.Column('employee_number', sa.Text(), nullable=True),
    sa.Column('outcome', sa.Text(), nullable=False),
    sa.Column('issues', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.CheckConstraint("outcome IN ('inserted','updated','unchanged','rejected')", name=op.f('ck_employee_import_rows_outcome_allowed')),
    sa.CheckConstraint('row_number > 0', name=op.f('ck_employee_import_rows_row_positive')),
    sa.ForeignKeyConstraint(['employee_number'], ['employees.employee_number'], name=op.f('fk_employee_import_rows_employee_number_employees'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['import_id'], ['employee_imports.id'], name=op.f('fk_employee_import_rows_import_id_employee_imports'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employee_import_rows')),
    sa.UniqueConstraint('import_id', 'row_number', name=op.f('uq_employee_import_rows_import_id'))
    )
    op.create_table('orders',
    sa.Column('request_key', sa.Uuid(), nullable=False),
    sa.Column('service_date', sa.Date(), nullable=False),
    sa.Column('menu_id', sa.BigInteger(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('employee_number', sa.Text(), nullable=True),
    sa.Column('visitor_id', sa.BigInteger(), nullable=True),
    sa.Column('customer_name_snapshot', sa.Text(), nullable=False),
    sa.Column('position_snapshot', sa.Text(), nullable=True),
    sa.Column('campaign_snapshot', sa.Text(), nullable=True),
    sa.Column('line_of_business_snapshot', sa.Text(), nullable=True),
    sa.Column('is_received', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('receipt_changed_by', sa.BigInteger(), nullable=True),
    sa.Column('receipt_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.CheckConstraint("btrim(customer_name_snapshot) <> ''", name=op.f('ck_orders_customer_name_snapshot_nonblank')),
    sa.CheckConstraint('(employee_number IS NOT NULL) <> (visitor_id IS NOT NULL)', name=op.f('ck_orders_customer_xor')),
    sa.CheckConstraint('(receipt_changed_by IS NULL) = (receipt_changed_at IS NULL) AND (NOT is_received OR receipt_changed_by IS NOT NULL)', name=op.f('ck_orders_receipt_metadata')),
    sa.CheckConstraint('version > 0', name=op.f('ck_orders_version_positive')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_orders_created_by_users'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['employee_number'], ['employees.employee_number'], name=op.f('fk_orders_employee_number_employees'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['menu_id'], ['menus.id'], name=op.f('fk_orders_menu_id_menus'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['receipt_changed_by'], ['users.id'], name=op.f('fk_orders_receipt_changed_by_users'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['service_date'], ['menu_dates.service_date'], name=op.f('fk_orders_service_date_menu_dates'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], name=op.f('fk_orders_visitor_id_visitors'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders')),
    sa.UniqueConstraint('request_key', name=op.f('uq_orders_request_key'))
    )
    op.create_index('ix_orders_employee_date', 'orders', ['employee_number', 'service_date'], unique=False, postgresql_where=sa.text('employee_number IS NOT NULL'))
    op.create_index('ix_orders_received_date', 'orders', ['service_date', 'id'], unique=False, postgresql_where=sa.text('is_received'))
    op.create_index('ix_orders_visitor_date', 'orders', ['visitor_id', 'service_date'], unique=False, postgresql_where=sa.text('visitor_id IS NOT NULL'))
    op.create_table('order_items',
    sa.Column('order_id', sa.BigInteger(), nullable=False),
    sa.Column('line_number', sa.Integer(), nullable=False),
    sa.Column('source_menu_item_id', sa.BigInteger(), nullable=False),
    sa.Column('item_name', sa.Text(), nullable=False),
    sa.Column('category_code_snapshot', sa.Text(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('line_total', sa.Numeric(precision=12, scale=2), sa.Computed('unit_price * quantity::numeric', persisted=True), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.CheckConstraint("btrim(item_name) <> ''", name=op.f('ck_order_items_item_name_nonblank')),
    sa.CheckConstraint("category_code_snapshot IN ('vegetable','non_vegetable','extra_rice')", name=op.f('ck_order_items_snapshot_category')),
    sa.CheckConstraint("unit_price >= 0 AND unit_price <> 'NaN'::numeric", name=op.f('ck_order_items_unit_price_valid')),
    sa.CheckConstraint('line_number > 0 AND quantity > 0', name=op.f('ck_order_items_positive_counts')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_items_order_id_orders'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_menu_item_id'], ['menu_items.id'], name=op.f('fk_order_items_source_menu_item_id_menu_items'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_items')),
    sa.UniqueConstraint('order_id', 'line_number', name=op.f('uq_order_items_order_id'))
    )
    op.create_table('payment_allocations',
    sa.Column('order_id', sa.BigInteger(), nullable=False),
    sa.Column('payment_category_code', sa.Text(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.CheckConstraint("amount > 0 AND amount <> 'NaN'::numeric", name=op.f('ck_payment_allocations_amount_positive')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_payment_allocations_created_by_users'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_payment_allocations_order_id_orders'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payment_category_code'], ['payment_categories.code'], name=op.f('fk_payment_allocations_payment_category_code_payment_categories'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_payment_allocations_updated_by_users'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payment_allocations')),
    sa.UniqueConstraint('order_id', 'payment_category_code', name=op.f('uq_payment_allocations_order_id'))
    )
    op.create_table('receipt_events',
    sa.Column('audit_event_id', sa.BigInteger(), nullable=False),
    sa.Column('order_id', sa.BigInteger(), nullable=False),
    sa.Column('from_received', sa.Boolean(), nullable=False),
    sa.Column('to_received', sa.Boolean(), nullable=False),
    sa.Column('reason_code', sa.Text(), nullable=True),
    sa.Column('reason_label_snapshot', sa.Text(), nullable=True),
    sa.Column('reason_explanation', sa.Text(), nullable=True),
    sa.CheckConstraint("(reason_code IS NULL AND reason_label_snapshot IS NULL AND reason_explanation IS NULL) OR (reason_code IS NOT NULL AND btrim(reason_code) <> '' AND reason_label_snapshot IS NOT NULL AND btrim(reason_label_snapshot) <> '')", name=op.f('ck_receipt_events_reason_metadata')),
    sa.CheckConstraint("reason_code IS DISTINCT FROM 'other' OR (reason_explanation IS NOT NULL AND reason_explanation ~ '[^[:space:]]')", name=op.f('ck_receipt_events_other_explanation')),
    sa.CheckConstraint('NOT from_received OR reason_code IS NOT NULL', name=op.f('ck_receipt_events_reversal_reason_required')),
    sa.CheckConstraint('from_received <> to_received', name=op.f('ck_receipt_events_state_changes')),
    sa.ForeignKeyConstraint(['audit_event_id'], ['audit_events.id'], name=op.f('fk_receipt_events_audit_event_id_audit_events'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_receipt_events_order_id_orders'), onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('audit_event_id', name=op.f('pk_receipt_events'))
    )
    op.create_index('ix_receipt_events_order_event', 'receipt_events', ['order_id', 'audit_event_id'], unique=False)
    op.execute(Path(__file__).with_name('0001_integrity.sql').read_text(encoding='utf-8'))

def downgrade():
    for table, trigger in [
        ('orders', 'asi_order_guard'), ('order_items', 'asi_item_guard'),
        ('payment_allocations', 'asi_allocation_guard'), ('orders', 'asi_order_totals'),
        ('order_items', 'asi_item_totals'), ('payment_allocations', 'asi_allocation_totals'),
        ('menu_items', 'asi_offering_guard'), ('audit_events', 'asi_audit_immutable'),
        ('receipt_events', 'asi_receipt_immutable'), ('receipt_events', 'asi_receipt_target_guard'),
    ]:
        op.execute(f'DROP TRIGGER {trigger} ON {table}')
    for function in [
        'asi_guard_order', 'asi_guard_order_child', 'asi_validate_order',
        'asi_guard_offering', 'asi_history_immutable', 'asi_receipt_target',
    ]:
        op.execute(f'DROP FUNCTION {function}()')
    op.drop_table('receipt_events')
    op.drop_table('payment_allocations')
    op.drop_table('order_items')
    op.drop_table('orders')
    op.drop_table('employee_import_rows')
    op.drop_table('menu_items')
    op.drop_table('menu_dates')
    op.drop_table('employees')
    op.drop_table('visitors')
    op.drop_table('menus')
    op.drop_table('employee_imports')
    op.drop_table('audit_events')
    op.drop_table('users')
    op.drop_table('dishes')
    op.drop_table('roles')
    op.drop_table('payment_categories')
    op.drop_table('item_categories')
