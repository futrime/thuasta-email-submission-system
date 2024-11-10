import email
import email.generator
import email.headerregistry
import email.message
import email.parser
import email.policy
import imaplib
import logging
import re
import smtplib
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Set, TypeAlias

import html2text

from email_message_utils import (
    calc_message_id_from_submission_id,
    calc_submission_id_from_message_id,
    extract_body_content,
    extract_first_from_address,
    extract_submission_id_from_subject,
)
from feedback_accepted_email_message import FeedbackAcceptedEmailMessage
from feedback_rejected_email_message import FeedbackRejectedEmailMessage
from publication_request_email_message import PublicationRequestEmailMessage
from review_request_email_message import ReviewRequestEmailMessage


class ReviewSystem:
    """Review system."""

    @dataclass
    class Options:
        """Configuration."""

        email_name: str
        email_address: str
        email_password: str
        imap_host: str
        smtp_host: str
        reviewer_email_addresses: List[str]
        min_reviewers: int

    class EmailCategory(Enum):
        """Email category."""

        REVIEW = "REVIEW"
        SUBMISSION = "SUBMISSION"

    class ReviewAction(Enum):
        """Review action."""

        ACCEPT = "ACCEPT"
        REJECT = "REJECT"

    MessageSet: TypeAlias = bytes

    def __init__(self, config: Options) -> None:
        """Initialize the review system.

        Args:
            config: Configuration.
        """

        self._config = config

        self._logger = logging.getLogger(self.__class__.__name__)

        self._imap_conn: Optional[imaplib.IMAP4_SSL] = None
        self._smtp_conn: Optional[smtplib.SMTP_SSL] = None
        self._email_parser = email.parser.BytesParser(policy=email.policy.default)

    def run(self) -> None:
        """Run the review system."""

        self._logger.debug("run()")

        self._connect()

        assert self._imap_conn is not None
        assert self._smtp_conn is not None

        # Search for unseen messages.
        _, resp = self._imap_conn.search(None, "(UNSEEN)")
        message_sets = resp[0].split()

        self._logger.info("Found %d unseen messages", len(message_sets))

        for message_set in message_sets:
            email_message = self._fetch_email_message(message_set)
            self._on_receive(email_message)

        self._disconnect()

        self._logger.info("Review system run completed")

    def _connect(self) -> None:
        self._logger.debug("_connect()")

        self._imap_conn = imaplib.IMAP4_SSL(self._config.imap_host)
        self._imap_conn.login(self._config.email_address, self._config.email_password)

        # To bypass the IMAP ID extension check
        imaplib.Commands["ID"] = ("AUTH",)
        getattr(self._imap_conn, "_simple_command")(
            "ID",
            '("name" "thuasta-email-submission-system" "version" "0.0.0" "vendor" "thuasta")',
        )
        self._imap_conn.select("INBOX")

        self._smtp_conn = smtplib.SMTP_SSL(self._config.smtp_host)
        self._smtp_conn.login(self._config.email_address, self._config.email_password)

    def _disconnect(self) -> None:
        self._logger.debug("_disconnect()")

        if self._imap_conn is not None:
            self._imap_conn.close()
            self._imap_conn.logout()
            self._imap_conn = None

        if self._smtp_conn is not None:
            self._smtp_conn.quit()
            self._smtp_conn = None

    def _on_receive(self, message: email.message.EmailMessage) -> None:
        self._logger.debug("_on_receive(message)")

        email_category = self._analyze_email_category(message)

        match email_category:
            case ReviewSystem.EmailCategory.REVIEW:
                self._on_receive_review(message)

            case ReviewSystem.EmailCategory.SUBMISSION:
                self._on_receive_submission(message)

            case _:
                return

    def _on_receive_review(self, review_message: email.message.EmailMessage) -> None:
        self._logger.debug("_on_receive_review(review_message)")

        if self._imap_conn is None:
            raise RuntimeError("_imap_conn is None")

        if self._smtp_conn is None:
            raise RuntimeError("_smtp_conn is None")

        submission_id = extract_submission_id_from_subject(review_message)
        if submission_id is None:
            return

        submission_message_id = calc_message_id_from_submission_id(submission_id)

        submission_message = self._fetch_email_message_by_message_id(
            submission_message_id
        )
        if submission_message is None:
            return

        submission_from_email_address = extract_first_from_address(submission_message)
        if submission_from_email_address is None:
            return

        seen_reviews = self._fetch_legal_seen_reviews(submission_id)
        self._logger.info(
            "Found %d legal seen reviews for submission #%s# (required: %d)",
            len(seen_reviews),
            submission_id,
            self._config.min_reviewers,
        )

        if len(seen_reviews) != self._config.min_reviewers:
            return

        reject_feedbacks: List[str] = []

        for review in seen_reviews:
            review_action = self._analyze_review_action(review)
            if review_action == ReviewSystem.ReviewAction.REJECT:
                review_body_content = extract_body_content(review)
                if review_body_content is None:
                    continue

                review_text = html2text.html2text(review_body_content)

                # Extract only content before "/reject"
                reject_feedback_match = re.search(r"^(.*?)\/reject", review_text)
                if reject_feedback_match is None:
                    continue

                reject_feedbacks.append(reject_feedback_match.group(1))

        if len(reject_feedbacks) > 0:
            feedback_rejected_message = FeedbackRejectedEmailMessage(
                to_email_address=submission_from_email_address,
                submission_message=submission_message,
                system_email_name=self._config.email_name,
                system_email_address=self._config.email_address,
                review_feedbacks=reject_feedbacks,
            )

            self._smtp_conn.send_message(feedback_rejected_message)

            self._logger.info(
                "Feedback (reject) sent successfully for submission #%s#", submission_id
            )

        else:
            feedback_accepted_message = FeedbackAcceptedEmailMessage(
                to_email_address=submission_from_email_address,
                system_email_name=self._config.email_name,
                system_email_address=self._config.email_address,
            )

            self._smtp_conn.send_message(feedback_accepted_message)

            self._logger.info(
                "Feedback (accept) sent successfully for submission #%s#",
                submission_id,
            )

            publication_request_message = PublicationRequestEmailMessage(
                submission_id=submission_id,
                submission_message=submission_message,
                system_email_name=self._config.email_name,
                system_email_address=self._config.email_address,
                reviewer_email_addresses=self._config.reviewer_email_addresses,
            )

            self._smtp_conn.send_message(publication_request_message)

            self._logger.info(
                "Publication request sent successfully for submission #%s#",
                submission_id,
            )

    def _on_receive_submission(self, message: email.message.EmailMessage) -> None:
        self._logger.debug("_on_receive_submission(message)")

        if self._smtp_conn is None:
            raise RuntimeError("_smtp_conn is None")

        submission_id = calc_submission_id_from_message_id(
            str(message["Message-ID"]).strip()
        )

        review_request_message = ReviewRequestEmailMessage(
            submission_id=submission_id,
            submission_message=message,
            system_email_name=self._config.email_name,
            system_email_address=self._config.email_address,
            reviewer_email_addresses=self._config.reviewer_email_addresses,
        )

        self._smtp_conn.send_message(review_request_message)

        self._logger.info(
            "Review request sent successfully for submission #%s#", submission_id
        )

    def _fetch_legal_seen_reviews(
        self, submission_id: str
    ) -> List[email.message.EmailMessage]:
        if self._imap_conn is None:
            raise RuntimeError("_imap_conn is None")

        # Search for seen reviews.
        _, resp = self._imap_conn.search(None, f'(SEEN SUBJECT "#{submission_id}#")')
        message_sets: List[bytes] = resp[0].split()

        reviews: List[email.message.EmailMessage] = []
        from_addresses: Set[str] = set()
        for message_set in message_sets:
            email_message = self._fetch_email_message(message_set)

            # Check if the message is a review
            if (
                self._analyze_email_category(email_message)
                != ReviewSystem.EmailCategory.REVIEW
            ):
                continue

            review_action = self._analyze_review_action(email_message)
            if review_action is None:
                continue

            from_address = extract_first_from_address(email_message)
            if from_address is None:
                continue

            # Deduplicate
            if from_address in from_addresses:
                continue

            from_addresses.add(from_address)
            reviews.append(email_message)

        return reviews

    def _fetch_email_message(
        self, message_set: MessageSet
    ) -> email.message.EmailMessage:
        """Fetch an email message from a message set.

        Args:
            message_set: Message set.

        Returns:
            Email message.
        """

        if self._imap_conn is None:
            raise RuntimeError("_imap_client is None")

        _, resp_fetch = self._imap_conn.fetch(message_set, "(BODY[])")  # type: ignore

        # The message will be marked as seen after fetching implicitly.

        email_body: bytes = resp_fetch[0][1]  # type: ignore
        message: email.message.EmailMessage = self._email_parser.parsebytes(
            email_body
        )  # type: ignore
        assert isinstance(message, email.message.EmailMessage)

        return message

    def _fetch_email_message_by_message_id(
        self, message_id: str
    ) -> Optional[email.message.EmailMessage]:
        if self._imap_conn is None:
            raise RuntimeError("_imap_conn is None")

        _, resp = self._imap_conn.search(None, f'(HEADER Message-ID "{message_id}")')
        message_sets = resp[0].split()

        if len(message_sets) == 0:
            return None

        return self._fetch_email_message(message_sets[0])

    def _analyze_email_category(
        self, message: email.message.EmailMessage
    ) -> Optional["ReviewSystem.EmailCategory"]:
        """Parse the email category.

        Args:
            message: Email message.

        Returns:
            Email category.
        """

        email_from = extract_first_from_address(message)
        if email_from is None:
            return None

        # Do not process self-sent emails
        if email_from == self._config.email_address:
            return None

        if email_from not in self._config.reviewer_email_addresses:
            return ReviewSystem.EmailCategory.SUBMISSION

        if email_from in self._config.reviewer_email_addresses:
            return ReviewSystem.EmailCategory.REVIEW

        return None

    def _analyze_review_action(
        self, message: email.message.EmailMessage
    ) -> Optional["ReviewSystem.ReviewAction"]:
        """Parse the review action.

        Args:
            message: Email message.

        Returns:
            Review action.
        """

        body_content = extract_body_content(message)

        if body_content is None:
            return None

        accept_command_matcher = re.compile(r"\/accept")
        do_accept = accept_command_matcher.search(body_content) is not None

        reject_command_matcher = re.compile(r"\/reject")
        do_reject = reject_command_matcher.search(body_content) is not None

        if do_accept and do_reject:
            return None

        if do_accept:
            return ReviewSystem.ReviewAction.ACCEPT

        if do_reject:
            return ReviewSystem.ReviewAction.REJECT

        return None
