"""Verify one app email/password login from your own private terminal."""
import argparse
import getpass
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pluxee_mobile_auth import login, MobileLoginError, MobileUnavailable


def main():
    argparse.ArgumentParser(description='Verify a Pluxee app email/password login without saving credentials.').parse_args()
    if not sys.stdin.isatty():
        print('Run this in your own interactive terminal; never pipe credentials.')
        return 1
    email = input('Pluxee app email: ').strip()
    password = getpass.getpass('Pluxee password (hidden): ')
    account = None
    try:
        account = login(email, password)
        password = None
        account.fetch_snapshot()
        print('App credential login, card discovery and live balance/movements: VERIFIED')
        print('No credentials, tokens or financial data were displayed or saved.')
        return 0
    except (MobileLoginError, MobileUnavailable) as error:
        print(str(error))
        return 1
    finally:
        password = None
        if account:
            account.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\nLogin check cancelled.')
        raise SystemExit(1)
