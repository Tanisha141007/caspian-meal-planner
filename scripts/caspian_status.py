"""Check what this deployment's Caspian account can actually do, and provision
the channels the app needs.

Run this first on any machine that can reach api.trycaspianai.com - it verifies
CASPIAN_API_KEY, prints the connections/capabilities/balance the app depends on,
and (with --connect-email / --connect-cook) creates them.

    python scripts/caspian_status.py                  # read-only report
    python scripts/caspian_status.py --connect-email  # provision the family inbox
    python scripts/caspian_status.py --connect-cook   # provision the cook's channel
    python scripts/caspian_status.py --login          # paid-channel developer sign-in

Every send path in the app depends on facts this prints:
  - the email connection's `address` is the From the family will see
  - `initiate` in a connection's capabilities is what lets us cold-start
    (the family by email yes, the cook on Telegram no - see handler.py)
  - a zero balance fails paid channels (SMS/WhatsApp) at send time, not here
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caspian_sdk import AccountRequiredError, CommError  # noqa: E402

from app.config import CASPIAN_EMAIL_DOMAIN, CASPIAN_EMAIL_USERNAME  # noqa: E402
from app.messaging.handler import (  # noqa: E402
    connect_channel,
    connect_email_channel,
    describe_comm_error,
    get_client,
)


def _print_connection(conn: dict) -> None:
    caps = conn.get("capabilities") or []
    print(f"  - {conn.get('channel'):10} id={conn.get('id')}  status={conn.get('status')}")
    if conn.get("address"):
        print(f"    address: {conn['address']}")
    print(f"    capabilities: {', '.join(caps) if caps else '(none reported)'}")
    if "initiate" not in caps:
        print("    note: cannot cold-start - the other side must message us first")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connect-email", action="store_true", help="provision the family email inbox")
    parser.add_argument("--connect-cook", action="store_true", help="provision the cook's channel (CASPIAN_CHANNEL)")
    parser.add_argument("--login", action="store_true", help="run the developer sign-in paid channels require")
    args = parser.parse_args()

    if not os.environ.get("CASPIAN_API_KEY"):
        print("CASPIAN_API_KEY is not set - put it in .env (see .env.example).")
        return 1

    client = get_client()

    if args.login:
        print("Starting Caspian device sign-in...")
        print(client.login())
        return 0

    try:
        print(f"Balance: {client.balance_cents()}c")
        print("\nChannels available to this account:")
        for ch in client.channels():
            name = ch.get("channel") or ch.get("name")
            status = ch.get("status") or ("paid" if ch.get("paid") else "free")
            print(f"  - {name} ({status})")

        print("\nExisting connections:")
        connections = client.list_connections()
        if not connections:
            print("  (none yet - use --connect-email / --connect-cook)")
        for conn in connections:
            _print_connection(conn)

        if args.connect_email:
            target = f"{CASPIAN_EMAIL_USERNAME}@{CASPIAN_EMAIL_DOMAIN or 'the default Caspian domain'}"
            print(f"\nProvisioning the family email inbox ({target})...")
            _print_connection(connect_email_channel())

        if args.connect_cook:
            channel = os.environ.get("CASPIAN_CHANNEL", "telegram")
            print(f"\nProvisioning the cook's channel ({channel})...")
            _print_connection(connect_channel())

    except AccountRequiredError as e:
        # 409 on connect_email means the mailbox name is taken; the SDK returns
        # free alternatives in `suggestions` rather than picking one for you.
        print(f"\n{describe_comm_error(e)}")
        print("Re-run with --login to complete the sign-in.")
        return 1
    except CommError as e:
        print(f"\n{describe_comm_error(e)}")
        if e.status_code == 409:
            print("That mailbox name is taken - set CASPIAN_EMAIL_USERNAME to one of the suggestions above.")
        return 1
    except Exception as e:
        # Transport-level failures (DNS, TLS, a corporate/egress proxy refusing
        # the host) never reach the gateway, so they aren't CommErrors - this
        # script exists to diagnose setup, so it must say that plainly instead
        # of printing an httpx traceback.
        print(f"\nCouldn't reach Caspian at {os.environ.get('CASPIAN_BASE_URL', 'api.trycaspianai.com')}:")
        print(f"  {type(e).__name__}: {e}")
        print("\nThe request never got to Caspian, so this says nothing about whether the key is valid.")
        print("Check network egress to api.trycaspianai.com (proxy allowlist, VPN, firewall) and retry.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
