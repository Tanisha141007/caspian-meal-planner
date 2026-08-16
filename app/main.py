import logging

from app.db import init_db
from app.messaging.handler import connect_channel, connect_email_channel, get_client, register_handler
from app.scheduler.jobs import start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

logger = logging.getLogger("main")


def main():
    init_db()
    connect_channel()

    # The family's email inbox, alongside the cook's channel. Non-fatal if it
    # fails: the cook's daily messages are the critical path and shouldn't be
    # blocked by an email connection that isn't provisioned yet - the weekly
    # job will surface the same error again on Monday.
    try:
        connection = connect_email_channel()
        logger.info("Email channel ready: %s", connection.get("address") or connection.get("id"))
    except Exception:
        logger.exception("Could not connect the email channel - weekly family emails will fail")

    register_handler()
    start_scheduler()

    client = get_client()
    client.listen()  # blocks forever, dispatching every inbound message to the handler


if __name__ == "__main__":
    main()
