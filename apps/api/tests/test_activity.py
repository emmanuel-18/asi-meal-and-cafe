"""Synthetic HTTP checks for protected, privacy-safe activity views."""
from datetime import datetime, timezone
import json
from test_auth import auth_env, client, login_http, passwords
from test_orders import concurrent_env
from test_database import sql


def test_activity_permissions_filters_cursor_and_redaction(auth_env):
    engine, g, _, service, password, _, runtime = auth_env
    with engine.begin() as c:
        sql(c, "UPDATE users SET role_code='super_admin' WHERE id=:id", id=g['actor'])
        for action, entity, key, before, after in [
            ('user_role_changed','users','123', {'role':'admin','password':'secret-before'}, {'role':'assistant_admin','password_hash':'secret-after'}),
            ('dish_updated','dishes','88', {'category_code':'vegetable','secret':'secret-before'}, {'category_code':'non_vegetable','token':'secret-after'}),
            ('legacy_action','employees','secret-employee', {'secret':'secret-before'}, {'secret':'secret-after'}),
        ]:
            sql(c, "INSERT INTO audit_events(actor_user_id,occurred_at,action,entity_type,entity_key,before_values,after_values) VALUES (:actor,:time,:action,:entity,:key,CAST(:before AS jsonb),CAST(:after AS jsonb))", actor=g['actor'], time=datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc), action=action, entity=entity, key=key, before=json.dumps(before), after=json.dumps(after))
    with client(runtime) as c:
        assert c.get('/api/activity').status_code == 401
        assert login_http(c, password).status_code == 200
        response = c.get('/api/activity', params={'start':'2026-01-01','end':'2026-01-01','limit':2})
        assert response.status_code == 200
        first = response.json(); assert len(first['items']) == 2 and first['next_cursor']
        assert first['items'][0]['id'] > first['items'][1]['id']
        assert first['items'][0]['action'] == 'unknown' and first['items'][0]['reference'] is None
        assert 'secret-' not in response.text
        next_page = c.get('/api/activity', params={'start':'2026-01-01','end':'2026-01-01','limit':2,'cursor':first['next_cursor']}).json()
        assert len(next_page['items']) == 1 and next_page['items'][0]['action'] == 'user_role_changed'
        assert next_page['items'][0]['before'] == {'role':'admin'}
        assert 'secret-' not in str(next_page)
        event_id = next_page['items'][0]['id']
        assert c.get(f'/api/activity/{event_id}').json() == next_page['items'][0]
        assert c.get('/api/activity', params={'actor_id':g['actor'],'action':'dish_updated','entity':'dishes','reference':'88'}).json()['items'][0]['action'] == 'dish_updated'
        assert c.get('/api/activity', params={'start':'2026-02-01','end':'2026-01-01'}).status_code == 422
        assert c.get('/api/activity', params={'limit':3,'cursor':first['next_cursor']}).status_code == 422
        assert c.delete(f'/api/activity/{event_id}').status_code == 405
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET role_code='admin' WHERE id=:id", id=g['actor'])
        assert c.get('/api/activity').status_code == 403
        assert c.get(f'/api/activity/{event_id}').status_code == 403
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET role_code='assistant_admin' WHERE id=:id", id=g['actor'])
        assert c.get('/api/activity').status_code == 403
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET role_code='super_admin',password_change_required=true WHERE id=:id", id=g['actor'])
        assert c.get('/api/activity').status_code == 403
