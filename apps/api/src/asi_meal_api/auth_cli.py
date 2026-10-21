"""Explicit local operations only; never called by startup or migrations."""

import argparse
import getpass
import os
import sys
import warnings

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from asi_meal_api.auth import AuthService, ProvisioningRejected


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid operation or arguments; credentials are entered interactively only.\n")


def main(argv=None) -> int:
    parser = SafeParser(description="Authorized local authentication maintenance")
    parser.add_argument("operation", choices=("bootstrap-admin", "cleanup-sessions"))
    args = parser.parse_args(argv)
    engine = None
    try:
        url = os.environ.get("ASI_DATABASE_URL", "")
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError
        if args.operation == "bootstrap-admin" and not sys.stdin.isatty():
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
