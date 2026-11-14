"""Provision local portal accounts from the deployment host."""
import argparse
import getpass
import secrets

from .accounts import provision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("role", choices=("client", "admin"))
    parser.add_argument("--buyer", choices=("hotel", "hospital"))
    parser.add_argument("--generate", action="store_true", help="Generate a password and print it once.")
    args = parser.parse_args()
    password = secrets.token_urlsafe(22) if args.generate else getpass.getpass("New password: ")
    try:
        provision(args.username, args.role, args.buyer, password)
    except ValueError as exc:
        parser.error(str(exc))
    if args.generate:
        print(password)
    else:
        print(f"Saved {args.role} account {args.username}.")


if __name__ == "__main__":
    main()
