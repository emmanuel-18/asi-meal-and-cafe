"""Explicit local operations only; never called by startup or migrations."""

import argparse
import getpass
import os
import sys
import warnings

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from asi_meal_api.auth import AuthService, ProvisioningRejected
from asi_meal_api.db import models as m
from asi_meal_api.user_management import event, revoke
from datetime import datetime, timezone


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid operation or arguments; credentials are entered interactively only.\n")


def main(argv=None) -> int:
    parser = SafeParser(description="Authorized local authentication maintenance")
    parser.add_argument("operation", choices=("bootstrap-admin", "cleanup-sessions", "promote-admin1"))
    args = parser.parse_args(argv)
    engine = None
    try:
        url = os.environ.get("ASI_DATABASE_URL", "")
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError
        if args.operation in {"bootstrap-admin", "promote-admin1"} and not sys.stdin.isatty():
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
        elif args.operation == "promote-admin1":
            with engine.connect() as connection:
                identity = connection.execute(text("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()")).one()
            print(f"Database: {identity[0]}; database user: {identity[1]}; server: {identity[2]}:{identity[3]}")
            operator = input("Local operator identifier (self-attested): ").strip()
            reason = input("Promotion reason: ").strip()
            if not operator or not reason or len(operator) > 255 or len(reason) > 1000:
                raise ProvisioningRejected("Operator and reason are required")
            if input("Verify database and type PROMOTE admin1 to confirm: ") != "PROMOTE admin1":
                raise ProvisioningRejected("Promotion not confirmed")
            with service.session_factory() as session, session.begin():
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(b"ASISUPER", "big")})
                user = session.scalar(select(m.User).where(m.User.login_name == "admin1").with_for_update())
                if user is None or not user.is_enabled or user.role_code not in {"admin", "super_admin"}:
                    raise ProvisioningRejected("Active admin1 Admin account not found")
                if user.role_code == "admin":
                    now = datetime.now(timezone.utc)
                    user.role_code = "super_admin"
                    user.updated_at = now
                    revoke(session, user.id, now)
                    event(session, user.id, user.id, "super_admin_promoted", {"role": "admin"},
                          {"role": "super_admin", "operator": operator, "attribution": "local_self_attested"}, reason)
                    message = "Promotion recorded; existing sessions revoked. Operator identity is self-attested."
                else:
                    message = "Account is already Super Admin; no change made."
            print(message)
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
