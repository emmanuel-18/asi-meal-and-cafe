"""Explicit local operations only; never called by startup or migrations."""

import argparse
import getpass
import os
import sys
import warnings

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from asi_meal_api.auth import AuthService, ProvisioningRejected
from asi_meal_api.db import models as m
from asi_meal_api.user_management import event, revoke
from datetime import datetime, timedelta, timezone


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid operation or arguments; credentials are entered interactively only.\n")


def main(argv=None) -> int:
    parser = SafeParser(description="Authorized local authentication maintenance")
    parser.add_argument("operation", choices=("bootstrap-admin", "create-super-admin", "cleanup-sessions", "promote-admin1", "recover-super-admin"))
    args = parser.parse_args(argv)
    engine = None
    try:
        url = os.environ.get("ASI_DATABASE_URL", "")
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError
        if args.operation in {"bootstrap-admin", "create-super-admin", "promote-admin1", "recover-super-admin"} and not sys.stdin.isatty():
            print("Interactive terminal required; provisioning refused.", file=sys.stderr)
            return 1
        engine = create_engine(url, hide_parameters=True)
        service = AuthService(sessionmaker(bind=engine))
        if args.operation == "bootstrap-admin":
            login = input("Individual login name: ")
            display = input("Display name: ")
            with warnings.catch_warnings():
                # Refuse getpass's visible-input fallback if no hidden terminal
                # is available; do not let a password echo onto the console.
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("Password: ")
                confirmation = getpass.getpass("Confirm password: ")
            if password != confirmation:
                print("Passwords do not match; provisioning refused.", file=sys.stderr)
                return 1
            service.provision_first_admin(login, display, password)
            print("Initial Admin provisioned.")
        elif args.operation == "create-super-admin":
            login, display, role = "superadmin", "master_emman", "super_admin"
            with engine.connect() as connection:
                identity = connection.execute(text("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()")).one()
                existing = connection.execute(text("SELECT id FROM users WHERE lower(btrim(login_name)) = lower(:login)"), {"login": login}).scalar_one_or_none()
            print(f"Database: {identity[0]}; database user: {identity[1]}; server: {identity[2]}:{identity[3]}")
            print(f"New account: login {login}, display name {display}, role {role}")
            if existing is not None:
                raise ProvisioningRejected("That login already exists; no account was changed")
            operator = input("Local operator identifier (self-attested): ").strip()
            reason = input("Creation reason: ").strip()
            if not operator or not reason or len(operator) > 255 or len(reason) > 1000:
                raise ProvisioningRejected("Operator and reason are required")
            if input("Verify database and type CREATE superadmin to confirm: ") != "CREATE superadmin":
                raise ProvisioningRejected("Creation not confirmed")
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("Password: ")
                confirmation = getpass.getpass("Confirm password: ")
            if password != confirmation:
                raise ProvisioningRejected("Passwords do not match")
            encoded = service.passwords.hash(password)
            try:
                with service.session_factory() as session, session.begin():
                    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(b"ASISUPER", "big")})
                    current_identity = session.execute(text("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()")).one()
                    if current_identity != identity:
                        raise ProvisioningRejected("Database identity changed; creation refused")
                    if session.scalar(select(m.User.id).where(func.lower(func.btrim(m.User.login_name)) == func.lower(func.btrim(login)))) is not None:
                        raise ProvisioningRejected("That login already exists; no account was changed")
                    user = m.User(login_name=login, display_name=display, role_code=role,
                                  password_hash=encoded, is_enabled=True, password_change_required=True)
                    session.add(user)
                    session.flush()
                    event(session, user.id, user.id, "super_admin_created", None,
                          {"login_name": login, "display_name": display, "role": role,
                           "is_enabled": True, "password_change_required": True,
                           "operator": operator, "attribution": "local_self_attested"}, reason)
            except IntegrityError:
                raise ProvisioningRejected("That login already exists; no account was changed") from None
            print("Super Admin account created; password change is required at first login.")
        elif args.operation == "promote-admin1":
            with engine.connect() as connection:
                identity = connection.execute(text("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()")).one()
                target = connection.execute(text("SELECT id, display_name, role_code, is_enabled FROM users WHERE login_name = 'admin1'")).one_or_none()
            print(f"Database: {identity[0]}; database user: {identity[1]}; server: {identity[2]}:{identity[3]}")
            if target is None or not target.is_enabled or target.role_code not in {"admin", "super_admin"}:
                raise ProvisioningRejected("Active admin1 Admin account not found")
            print(f"Target: admin1, user ID {target.id}, display name {target.display_name}, role {target.role_code}, enabled")
            operator = input("Local operator identifier (self-attested): ").strip()
            reason = input("Promotion reason: ").strip()
            if not operator or not reason or len(operator) > 255 or len(reason) > 1000:
                raise ProvisioningRejected("Operator and reason are required")
            if input("Verify database and type PROMOTE admin1 to confirm: ") != "PROMOTE admin1":
                raise ProvisioningRejected("Promotion not confirmed")
            with service.session_factory() as session, session.begin():
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(b"ASISUPER", "big")})
                current_identity = session.execute(text("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()")).one()
                if current_identity != identity:
                    raise ProvisioningRejected("Database identity changed; promotion refused")
                user = session.scalar(select(m.User).where(m.User.login_name == "admin1").with_for_update())
                if user is None or user.id != target.id or user.display_name != target.display_name or not user.is_enabled or user.role_code != target.role_code:
                    raise ProvisioningRejected("Target account changed; promotion refused")
                if user.role_code == "admin":
                    now = max(datetime.now(timezone.utc), user.updated_at + timedelta(microseconds=1))
                    user.role_code = "super_admin"
                    user.updated_at = now
                    revoke(session, user.id, now)
                    event(session, user.id, user.id, "super_admin_promoted", {"role": "admin"},
                          {"role": "super_admin", "operator": operator, "attribution": "local_self_attested"}, reason)
                    message = "Promotion recorded; existing sessions revoked. Operator identity is self-attested."
                else:
                    message = "Account is already Super Admin; no change made."
            print(message)
        elif args.operation == "recover-super-admin":
            login = input("Super Admin login name: ").strip()
            if not login or len(login) > 255:
                raise ProvisioningRejected("Invalid target")
            with engine.connect() as connection:
                identity = connection.execute(text("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()")).one()
                target = connection.execute(text("SELECT id, display_name, role_code, is_enabled, updated_at FROM users WHERE login_name = :login"), {"login": login}).one_or_none()
            print(f"Database: {identity[0]}; database user: {identity[1]}; server: {identity[2]}:{identity[3]}")
            if target is None or not target.is_enabled or target.role_code != "super_admin":
                raise ProvisioningRejected("Active Super Admin account not found")
            print(f"Target: {login}, user ID {target.id}, display name {target.display_name}, role super_admin, enabled")
            operator = input("Local operator identifier (self-attested): ").strip()
            reason = input("Nonsecret recovery reason: ").strip()
            if not operator or len(operator) > 255 or len(reason) < 10 or len(reason) > 1000:
                raise ProvisioningRejected("Operator and meaningful reason are required")
            if input(f"Verify database and type RECOVER {target.id} to confirm: ") != f"RECOVER {target.id}":
                raise ProvisioningRejected("Recovery not confirmed")
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("New temporary password: ")
                confirmation = getpass.getpass("Confirm temporary password: ")
            if password != confirmation:
                raise ProvisioningRejected("Passwords do not match")
            encoded = service.passwords.hash(password)
            with service.session_factory() as session, session.begin():
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(b"ASISUPER", "big")})
                current_identity = session.execute(text("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()")).one()
                if current_identity != identity:
                    raise ProvisioningRejected("Database identity changed; recovery refused")
                user = session.scalar(select(m.User).where(m.User.id == target.id).with_for_update())
                if user is None or user.login_name != login or user.display_name != target.display_name or user.updated_at != target.updated_at or not user.is_enabled or user.role_code != "super_admin":
                    raise ProvisioningRejected("Target account changed; recovery refused")
                now = max(datetime.now(timezone.utc), user.updated_at + timedelta(microseconds=1))
                previous_required = user.password_change_required
                user.password_hash = encoded
                user.password_change_required = True
                user.updated_at = now
                revoke(session, user.id, now)
                event(session, user.id, user.id, "super_admin_recovered", {"password_change_required": previous_required},
                      {"password_change_required": True, "operator": operator, "attribution": "local_self_attested"}, reason)
            print("Recovery recorded; sessions revoked and password change required. Operator identity is self-attested.")
        else:
            print(f"Removed {service.cleanup()} expired/revoked sessions.")
        return 0
    except ProvisioningRejected as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("Operation failed; check authorized local configuration.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
