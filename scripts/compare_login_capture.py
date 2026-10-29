"""Compare a successful HTTP Toolkit capture locally. Makes NO network requests.

Usage: python scripts/compare_login_capture.py path/to/login.json-or.har
The file stays local. Credentials are prompted, never printed, saved or decrypted
from the capture. Only comparison results are displayed.
"""
import argparse
import base64
import getpass
import hmac
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pluxee_crypto import encrypt


def extract_capture(document):
    if isinstance(document, dict) and isinstance(document.get('Email'), str) and isinstance(document.get('Password'), str):
        return document
    entries = document.get('log', {}).get('entries', []) if isinstance(document, dict) else []
    for entry in reversed(entries):
        request = entry.get('request', {})
        url = urlsplit(request.get('url', ''))
        if url.hostname != 'api.mobile.clients.pluxee.pt' or url.path != '/api/user/login' or entry.get('response', {}).get('status') != 200:
            continue
        try:
            data = json.loads(request.get('postData', {}).get('text', ''))
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get('Email'), str) and isinstance(data.get('Password'), str):
            return data
    raise ValueError('No successful mobile login found. Export its request JSON body or a HAR containing that HTTP 200 login.')


def compare_field(plain, captured):
    if not isinstance(captured, str) or len(captured) < 40:
        raise ValueError('Captured field is incomplete.')
    iv = captured[-16:]
    ciphertext = base64.b64decode(captured[:-16], validate=True)
    if not ciphertext or len(ciphertext) % 16 or not iv.isascii() or not iv.isalnum():
        raise ValueError('Captured field does not match the app format.')
    # Recreate ciphertext from the user-entered value. Never decrypt the captured password.
    return hmac.compare_digest(encrypt(plain, iv), captured)


def compare_credentials(email, password, capture):
    return {'email_matches': compare_field(email.strip(), capture['Email']),
            'password_matches': compare_field(password, capture['Password'])}


def main():
    parser = argparse.ArgumentParser(description='Offline comparison with a successful Pluxee app login. No API calls.')
    parser.add_argument('capture', type=Path, help='Local request-body JSON or HTTP Toolkit HAR file')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit('Run this in your own terminal. Never pipe passwords.')
    if args.capture.stat().st_size > 50 * 1024 * 1024:
        raise SystemExit('Export only the successful login to keep the capture under 50 MB.')
    capture = extract_capture(json.loads(args.capture.read_text(encoding='utf-8-sig')))
    email = input('Same email entered in the dashboard: ').strip()
    password = getpass.getpass('Same password (hidden; not saved): ')
    result = compare_credentials(email, password, capture)
    password = None
    print('Email matches successful app capture:', 'YES' if result['email_matches'] else 'NO')
    print('Password matches successful app capture:', 'YES' if result['password_matches'] else 'NO')
    print('No login attempt was made. No credentials were displayed or saved.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError):
        raise SystemExit('Capture could not be read or validated. No login attempt was made.')
    except (KeyboardInterrupt, EOFError):
        raise SystemExit('Comparison cancelled. No login attempt was made.')
