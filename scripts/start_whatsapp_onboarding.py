"""Placeholder for Caspian's future hosted WhatsApp onboarding flow.

Caspian's live /v1/channels response does not currently include WhatsApp.
The integration guide says not to try to connect non-live gateway channels,
even if SDK methods are present locally. Use SMS for now; bring this script
back once WhatsApp appears in /v1/channels.

    python scripts/start_whatsapp_onboarding.py
"""


def main():
    raise SystemExit(
        "WhatsApp is coming soon on this Caspian gateway. "
        "Use CASPIAN_CHANNEL=sms until /v1/channels lists WhatsApp."
    )


if __name__ == "__main__":
    main()
