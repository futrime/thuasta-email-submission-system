import base64
import email
import email.generator
import email.message
import email.parser
import email.policy
import imaplib
import re
import smtplib
from dataclasses import dataclass
from enum import Enum
from typing import List, Literal, Optional, Tuple


class EmailCategory(Enum):
    SUBMISSION = "SUBMISSION"
    SUBMISSION_NOTIFICATION = "SUBMISSION_NOTIFICATION"
    SUBMISSION_FEEDBACK = "SUBMISSION_FEEDBACK"
    REVIEW_REQUEST = "REVIEW_REQUEST"
    REVIEW = "REVIEW"
    REVIEW_FEEDBACK = "REVIEW_FEEDBACK"


@dataclass
class ReviewSystemConfig:
    email_address: str
    email_password: str
    email_imap_host: str
    email_smtp_host: str
    reviewer_email_address_list: List[str]


class ReviewSystem:
    def __init__(self, config: ReviewSystemConfig) -> None:
        self.config = config
        self.imap_client: Optional[imaplib.IMAP4_SSL] = None
        self.smtp_client = smtplib.SMTP_SSL(self.config.email_smtp_host)

    def run(self) -> None:
        self._connect()

        assert self.imap_client is not None
        assert self.smtp_client is not None

        self.imap_client.select("INBOX")
        _, resp = self.imap_client.search(None, "UNSEEN")
        message_sets: List[bytes] = resp[0].split()

        email_parser = email.parser.BytesParser(policy=email.policy.default)

        for message_set in message_sets:
            _, resp_fetch = self.imap_client.fetch(message_set, "(BODY.PEEK[])")  # type: ignore
            email_body: bytes = resp_fetch[0][1]  # type: ignore
            email_message: email.message.EmailMessage = email_parser.parsebytes(
                email_body
            )  # type: ignore
            self._on_receive(email_message)

        self._logout()

    def _connect(self) -> None:
        self.imap_client = imaplib.IMAP4_SSL(self.config.email_imap_host)
        self.smtp_client = smtplib.SMTP_SSL(self.config.email_smtp_host)

        self.imap_client.login(self.config.email_address, self.config.email_password)
        self.smtp_client.login(self.config.email_address, self.config.email_password)

    def _logout(self) -> None:
        if self.imap_client is not None:
            self.imap_client.logout()

        if self.smtp_client is not None:
            self.smtp_client.close()

    def _on_receive(self, message: email.message.EmailMessage) -> None:
        email_category = self._get_email_category(message)

        match email_category:
            case EmailCategory.SUBMISSION:
                self._on_receive_submission(message)
            case EmailCategory.REVIEW:
                self._on_receive_review(message)
            case None:
                return

    def _on_receive_submission(
        self, submission_message: email.message.EmailMessage
    ) -> None:
        # self._send_review_request(submission_message)
        self._send_submission_notification(submission_message)

    def _on_receive_review(self, message: email.message.EmailMessage) -> None:
        pass

    def _send_review_request(
        self, submission_message: email.message.EmailMessage
    ) -> None:
        submission_id = base64.b64encode(submission_message["Message-ID"]).decode()
        submission_body = submission_message.get_body(("plain"))
        submission_body_text = (
            submission_body.get_payload() if submission_body is not None else ""
        )

        review_request_message = email.message.EmailMessage()
        review_request_message["From"] = (
            f"ASTA Weekly Review System <{self.config.email_address}>"
        )
        review_request_message["To"] = ", ".join(
            self.config.reviewer_email_address_list
        )
        review_request_message["Subject"] = (
            f"ASTA Weekly Submission Review Request (#{submission_id}#)"
        )

        review_request_body = f"""
Please review the following submission and respond with:
- /accept to approve
- Any other response to reject
DO NOT REMOVE "#{submission_id}#" IN THE SUBJECT.
--------------------------------------------------------------------------------
{submission_body_text}
"""

        review_request_message.set_content(review_request_body)

        # Forward all attachments
        for attachment in submission_message.iter_attachments():
            filename = attachment.get_filename()
            review_request_message.add_attachment(
                attachment.get_payload(decode=True),
                filename=filename,
                maintype=attachment.get_content_maintype(),
                subtype=attachment.get_content_subtype(),
            )

        self.smtp_client.send_message(review_request_message)

    def _send_submission_notification(
        self, submission_message: email.message.EmailMessage
    ) -> None:
        submission_from = ReviewSystem._extract_email_address(
            submission_message["From"]
        )
        if submission_from is None:
            return

        submission_notification_message = email.message.EmailMessage()
        submission_notification_message["From"] = (
            f"ASTA Weekly Review System <{self.config.email_address}>"
        )
        submission_notification_message["To"] = submission_from
        submission_notification_message["Subject"] = (
            "Submission is received and will be reviewed."
        )
        # submission_notification_message["Reply-To"] = self.config.email_address
        submission_notification_message["In-Reply-To"] = submission_message[
            "Message-ID"
        ]

        submission_notification_body_text = """
Thank you for your submission. It is received and will be reviewed.
DO NOT REPLY TO THIS EMAIL. OTHERWISE IT WILL BE TREATED AS A NEWSUBMISSION.
"""

        submission_notification_message.set_content(submission_notification_body_text)

        self.smtp_client.send_message(submission_notification_message)

    def _get_email_category(
        self, message: email.message.Message
    ) -> Optional[EmailCategory]:
        email_from = ReviewSystem._extract_email_address(message["From"])
        if email_from is None:
            return None

        if email_from in self.config.reviewer_email_address_list:
            return EmailCategory.REVIEW

        return EmailCategory.SUBMISSION

    @staticmethod
    def _extract_email_address(text: str) -> Optional[str]:
        match = re.search(r"[\w\.+-]+@([\w-]+\.)+[\w-]+", text)
        return match.group(0) if match is not None else None
