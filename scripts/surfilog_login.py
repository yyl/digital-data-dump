#!/usr/bin/env python3
"""Test Surfilog password login and authenticated access to session wave counts.

Run: uv run python scripts/surfilog_login.py

Credentials are prompted for, or read from SURFILOG_EMAIL and SURFILOG_PASSWORD
environment variables. Password entry is hidden. Cookies stay in memory and are
never printed or saved. This script uses only the Python standard library.
"""

import argparse
import getpass
import math
import os
from pathlib import Path
import sys
import warnings
from datetime import datetime, timezone

# Keep this standalone probe runnable without installing the package or loading .env.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.surfilog.api_client import SurfilogAPIClient, SurfilogAPIError

LoginCheckError = SurfilogAPIError


def check_login(email, password, timeout=30):
    client = SurfilogAPIClient(email, password, timeout)
    client.login()
    sessions = client.get_sessions()
    if any(type(session.get("wave_count")) is not int or session["wave_count"] < 0
           for session in sessions):
        raise LoginCheckError("Session data did not contain valid wave counts.")
    print("Login successful; authenticated identity and session access verified.")
    print(f"Available: {len(sessions)} session(s), "
          f"{sum(session['wave_count'] for session in sessions)} wave(s).")
    if client.token_expires is not None:
        expires = datetime.fromtimestamp(client.token_expires, timezone.utc)
        print(f"Token cookie expires: {expires:%Y-%m-%d %H:%M:%S} UTC.")
    else:
        print("Token cookie has no explicit cookie expiry.")
    print("Credentials and cookies were not saved.")


def positive_timeout(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive finite number")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="Surfilog email (otherwise env var or prompt)")
    parser.add_argument("--timeout", type=positive_timeout, default=30, metavar="SECONDS")
    args = parser.parse_args(argv)
    try:
        email = (args.email or os.environ.get("SURFILOG_EMAIL") or input("Surfilog email: ")).strip()
        password = os.environ.get("SURFILOG_PASSWORD")
        if password is None:
            # Do not fall back to echoing a password when hidden input is unavailable.
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("Surfilog password (not your Google password): ")
        if not email or not password:
            raise LoginCheckError("Email and password are required.")
        check_login(email, password, args.timeout)
    except getpass.GetPassWarning:
        print("Hidden password input unavailable; run in an interactive terminal.", file=sys.stderr)
        return 1
    except EOFError:
        print("Credentials unavailable; run in an interactive terminal or set the environment variables.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except LoginCheckError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
