import logging
import os
import time

import dotenv

from review_system import ReviewSystem, ReviewSystemConfig


def main() -> None:
    dotenv.load_dotenv()

    keep_alive = os.getenv("KEEP_ALIVE", "false").lower() == "true"
    logging_level = os.getenv("LOGGING_LEVEL", "INFO")

    logging.basicConfig(level=logging_level)

    config = ReviewSystemConfig(
        email_address=os.getenv("PUBLIC_EMAIL_ADDRESS", ""),
        email_password=os.getenv("PUBLIC_EMAIL_PASSWORD", ""),
        email_imap_host=os.getenv("PUBLIC_EMAIL_IMAP_HOST", ""),
        email_smtp_host=os.getenv("PUBLIC_EMAIL_SMTP_HOST", ""),
        reviewer_email_address_list=os.getenv("REVIEWER_EMAIL_ADDRESS_LIST", "").split(
            ","
        ),
        min_review_count=int(os.getenv("MIN_REVIEW_COUNT", "3")),
    )

    review_system = ReviewSystem(config)

    while True:
        review_system.run()
        if not keep_alive:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
