import logging

from app.db import init_db
from app.messaging.handler import connect_channel, get_client, register_handler
from app.scheduler.jobs import start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    init_db()
    connect_channel()
    register_handler()
    start_scheduler()

    client = get_client()
    client.listen()  # blocks forever, dispatching every inbound message to the handler


if __name__ == "__main__":
    main()
