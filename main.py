import asyncio
import imaplib
import os
from dataclasses import dataclass

import dotenv


@dataclass
class Config:
    email_address: str
    email_password: str
    email_imap_host: str
    email_smtp_host: str


async def main():
    dotenv.load_dotenv()

    config = Config(
        email_address=os.getenv("PUBLIC_EMAIL_ADDRESS") or "",
        email_password=os.getenv("PUBLIC_EMAIL_PASSWORD") or "",
        email_imap_host=os.getenv("PUBLIC_EMAIL_IMAP_HOST") or "",
        email_smtp_host=os.getenv("PUBLIC_EMAIL_SMTP_HOST") or "",
    )

    imap_client = imaplib.IMAP4_SSL(config.email_imap_host)
    resp_code, resp_data = imap_client.login(
        config.email_address, config.email_password
    )
    print(resp_code, resp_data)

    resp_code, resp_data = imap_client.list()
    print(resp_code, resp_data)

    resp_code, resp_data = imap_client.select("Sent")
    print(resp_code, resp_data)

    resp_code, resp_data = imap_client.logout()
    print(resp_code, resp_data)


if __name__ == "__main__":
    asyncio.run(main())
