"""Kicks off Caspian's hosted WhatsApp onboarding flow and prints the
launcher_url. Whoever owns the WhatsApp Business number opens that URL and
clicks through once; no Meta tokens are handled on your side.

This hits Caspian's real API (POST /v1/connections/whatsapp/onboarding-session).
The public docs still list WhatsApp as "coming soon", so this may return an
error if it isn't enabled for your account yet - that's expected, not a bug
in this script. If it works, poll get_connection() (or watch for a
connection.active webhook event) until status is "active", then set
CASPIAN_CHANNEL=whatsapp and rerun the app - no other code changes needed.

    python scripts/start_whatsapp_onboarding.py
"""

from app.messaging.handler import get_client


def main():
    client = get_client()
    result = client.start_whatsapp_onboarding()
    print("WhatsApp onboarding session:", result)
    launcher_url = result.get("launcher_url") if isinstance(result, dict) else None
    if launcher_url:
        print(f"\nSend this link to the WhatsApp Business account owner:\n{launcher_url}")


if __name__ == "__main__":
    main()
