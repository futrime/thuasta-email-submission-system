"""Main module."""

import logging
import os
from dataclasses import dataclass
from typing import List

import dotenv

from review_system import ReviewSystem


@dataclass
class Env:
    """Environment variables."""

    email_name: str
    email_address: str
    email_password: str
    imap_host: str
    smtp_host: str
    reviewer_email_addresses: List[str]
    min_reviewers: int
    is_periodical: bool
    logging_level: str


def load_env() -> Env:
    """Load environment variables.

    Returns:
        Environment variables.
    """

    dotenv.load_dotenv(override=True)

    return Env(
        email_name=os.getenv("EMAIL_NAME", "自动化系学生科协"),
        email_address=os.getenv("EMAIL_ADDRESS", ""),
        email_password=os.getenv("EMAIL_PASSWORD", ""),
        imap_host=os.getenv("IMAP_HOST", ""),
        smtp_host=os.getenv("SMTP_HOST", ""),
        reviewer_email_addresses=list(
            map(str.strip, os.getenv("REVIEWER_EMAIL_ADDRESSES", "").splitlines())
        ),
        min_reviewers=int(os.getenv("MIN_REVIEWERS", "1")),
        is_periodical=os.getenv("IS_PERIODICAL", "false").lower() == "true",
        logging_level=os.getenv("LOGGING_LEVEL", "INFO"),
    )


def main() -> None:
    """Main function."""

    env = load_env()

    logging.basicConfig(level=env.logging_level)

    config = ReviewSystem.Options(
        email_name=env.email_name,
        email_address=env.email_address,
        email_password=env.email_password,
        imap_host=env.imap_host,
        smtp_host=env.smtp_host,
        reviewer_email_addresses=env.reviewer_email_addresses,
        min_reviewers=env.min_reviewers,
    )

    review_system = ReviewSystem(config)

    review_system.run()

    while env.is_periodical:
        review_system.run()


if __name__ == "__main__":
    main()
