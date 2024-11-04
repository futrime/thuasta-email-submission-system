"""
Email submission review system that processes submissions and manages reviews.
"""

import asyncio
import email
import email.message
import imaplib
import logging
import os
import re
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Set, Tuple

import dotenv


@dataclass
class ReviewSystemConfig:
    """Configuration for email and reviewer settings."""

    email_address: str
    email_password: str
    email_imap_host: str
    email_smtp_host: str
    reviewer_email_address_list: List[str]


@dataclass
class Review:
    """Represents a review response."""

    reviewer_email: str
    content: str
    is_accepted: bool


class ReviewSystem:
    """Manages the submission and review process."""

    def __init__(self, config: ReviewSystemConfig) -> None:
        """Initialize the review system with configuration."""
        self.config = config
        self.reviews: Dict[str, List[Review]] = {}

    async def process_emails(self) -> None:
        """Main processing loop for handling emails."""

        imap_client = imaplib.IMAP4_SSL(self.config.email_imap_host)

        imap_client.login(self.config.email_address, self.config.email_password)

        imap_client.select("INBOX")

        _, resp_search = imap_client.search(None, "UNSEEN")
        message_numbers: List[bytes] = resp_search[0].split()

        for message_number in message_numbers:
            _, resp_fetch = imap_client.fetch(message_number, "(RFC822)")  # type: ignore
            email_body: bytes = resp_fetch[0][1]  # type: ignore
            message = email.message_from_bytes(email_body)

            await self._process_message(message)

            # Mark as read
            imap_client.store(message_number, "+FLAGS", "\\Seen")  # type: ignore

        imap_client.close()

        imap_client.logout()

    async def _process_message(self, message: email.message.Message) -> None:
        """Process individual email messages."""
        from_email = self._extract_email_address(message["From"])
        if from_email is None:
            return

        if self._is_review_response(message):
            await self._handle_review_response(message)

        elif from_email not in self.config.reviewer_email_address_list:
            await self._handle_submission(message)

    def _is_review_response(self, message: email.message.Message) -> bool:
        """Check if message is a review response."""
        subject = message["Subject"]
        return bool(subject and "Re: Review Request" in subject)

    def _extract_submission_id(self, content: str) -> Optional[str]:
        """Extract submission ID from message content."""
        match = re.search(r"Submission ID: ([a-f0-9-]+)", content)
        return match.group(1) if match else None

    async def _handle_submission(self, message: email.message.Message) -> None:
        """Process new submission and send review requests."""
        submission_id = str(uuid.uuid4())

        # Create review request content
        submission_content = self._get_message_content(message)
        review_request = self._create_review_request(
            message["Subject"], submission_content, submission_id
        )

        # Send review requests to all reviewers
        await self._send_review_requests(review_request)

    async def _handle_review_response(self, message: email.message.Message) -> None:
        """Process review response and take appropriate action."""
        content = self._get_message_content(message)
        submission_id = self._extract_submission_id(content)

        if not submission_id:
            return

        reviewer_email = self._extract_email_address(message["From"])
        is_accepted = "/accept" in content.lower()

        # Store the review
        if submission_id not in self.reviews:
            self.reviews[submission_id] = []

        self.reviews[submission_id].append(Review(reviewer_email, content, is_accepted))

        # Process reviews if we have exactly 3
        if len(self.reviews[submission_id]) == 3:
            await self._process_final_decision(submission_id)

    async def _process_final_decision(self, submission_id: str) -> None:
        """Process final decision based on reviews."""
        reviews = self.reviews[submission_id]
        accepted = all(review.is_accepted for review in reviews)

        response = self._create_decision_response(accepted, reviews)
        await self._send_email(
            self._extract_email_address(reviews[0].reviewer_email),
            "Submission Decision",
            response,
        )

    def _create_review_request(
        self, subject: str, content: str, submission_id: str
    ) -> str:
        """Create review request message."""
        return f"""
Review Request

Original Subject: {subject}
Submission ID: {submission_id}

Original Content:
{content}

Please review this submission and respond with:
- /accept to approve
- Any other response to reject

Please reply to this email with your decision.
"""

    def _create_decision_response(self, accepted: bool, reviews: List[Review]) -> str:
        """Create decision response message."""
        status = "accepted" if accepted else "rejected"
        response = f"Your submission has been {status}.\n\nReviews:\n"

        for i, review in enumerate(reviews, 1):
            response += f"\nReview {i}:\n{review.content}\n"

        return response

    async def _send_review_requests(self, content: str) -> None:
        """Send review requests to all reviewers."""
        for reviewer in self.config.reviewer_email_address_list:
            await self._send_email(reviewer, "Review Request", content)

    async def _send_email(self, to_email: str, subject: str, content: str) -> None:
        """Send email using SMTP."""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.config.email_address
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(content, "plain"))

            with smtplib.SMTP_SSL(self.config.email_smtp_host) as smtp:
                smtp.login(self.config.email_address, self.config.email_password)
                smtp.send_message(msg)

        except Exception as e:
            print(f"Error sending email: {str(e)}")

    def _get_message_content(self, message: email.message.Message) -> str:
        """Extract message content including attachments."""
        content = []

        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    content.append(part.get_payload())
        else:
            content.append(message.get_payload())

        return "\n".join(content)

    @staticmethod
    def _extract_email_address(address: str) -> Optional[str]:
        """Extract email address from a formatted string."""
        match = re.search(r"[\w-\.+]+@([\w-]+\.)+[\w-]+", address)
        return match.group(1) if match is not None else None


async def main() -> None:
    """Main entry point of the application."""
    dotenv.load_dotenv()

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
    )

    review_system = ReviewSystem(config)

    while True:
        await review_system.process_emails()
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
