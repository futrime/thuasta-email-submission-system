import base64
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
from typing import List, Optional, TypeAlias


class ReviewSystem:
    """Review system."""

    # Add support for IMAP4 ID extension (RFC 2971)
    imaplib.Commands["ID"] = ("AUTH",)

    @dataclass
    class Options:
        """Configuration."""

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

        message_sets = self._fetch_unseen_message_sets()

        self._logger.info("Found %d unseen messages", len(message_sets))

        for message_set in message_sets:
            try:
                email_message = self._fetch_email_message(message_set)
                self._on_receive(email_message)

            except Exception as e:
                self._logger.error("Failed to process message (message_set=%s): %s", message_set, e)
                continue

        self._disconnect()

        self._logger.info("Review system run completed")

    def _connect(self) -> None:
        self._logger.debug("_connect()")

        self._imap_conn = imaplib.IMAP4_SSL(self._config.imap_host)
        self._imap_conn.login(self._config.email_address, self._config.email_password)
        self._imap_conn._simple_command("ID", '("name" "thuasta-email-submission-system" "version" "0.0.0" "vendor" "thuasta")') # To bypass safe check of 126 mail
        self._imap_conn.select("INBOX")

        self._smtp_conn = smtplib.SMTP_SSL(self._config.smtp_host)
        self._smtp_conn.login(self._config.email_address, self._config.email_password)

    def _disconnect(self) -> None:
        self._logger.debug("_disconnect()")

        if self._imap_conn is not None:
            self._imap_conn.close()
            self._imap_conn.logout()

        if self._smtp_conn is not None:
            self._smtp_conn.quit()

    def _on_receive(self, message: email.message.EmailMessage) -> None:
        self._logger.debug("_on_receive(message)")

        email_category = self._parse_email_category(message)

        match email_category:
            case ReviewSystem.EmailCategory.REVIEW:
                self._on_receive_review(message)

            case ReviewSystem.EmailCategory.SUBMISSION:
                self._on_receive_submission(message)

            case _:
                return

    def _on_receive_review(self, review_message: email.message.EmailMessage) -> None:
        self._logger.info("_on_receive_review(review_message)")

        submission_matcher = re.compile(r"#([A-Za-z0-9+\/=]+)#")
        submission_match = submission_matcher.search(review_message["Subject"])
        if submission_match is None:
            self._logger.error("Could not find submission ID in review subject")
            return

        submission_id = submission_match.group(1)
        seen_reviews = self._get_seen_reviews(
            submission_id
        )  # Include the current review
        self._logger.info(
            "Found %d existing reviews for submission %s",
            len(seen_reviews),
            submission_id,
        )

        # If less, wait for more reviews
        # If more, ignore
        if len(seen_reviews) < self._config.min_reviewers:
            self._logger.info(
                "Waiting for more reviews (current: %d, required: %d)",
                len(seen_reviews),
                self._config.min_reviewers,
            )
            return
        elif len(seen_reviews) > self._config.min_reviewers:
            self._logger.info(
                "Received more reviews than required, may be a duplicate (current: %d, required: %d)",
                len(seen_reviews),
                self._config.min_reviewers,
            )
            return

        accept_review_count = 0
        accept_command_matcher = re.compile(r"\/accept")
        for review in seen_reviews:
            review_body = review.get_body(preferencelist=("html", "plain"))
            if review_body is None:
                continue

            review_body_text = review_body.get_content()
            if accept_command_matcher.search(review_body_text) is not None:
                accept_review_count += 1

        if accept_review_count >= self._config.min_reviewers:
            self._logger.info(
                "Submission %s accepted with %d/%d accept votes",
                submission_id,
                accept_review_count,
                self._config.min_reviewers,
            )
            self._send_publication_notification(submission_id, seen_reviews)
            self._send_submission_feedback_accept(submission_id)
        else:
            self._logger.info(
                "Submission %s rejected with only %d/%d accept votes",
                submission_id,
                accept_review_count,
                self._config.min_reviewers,
            )
            self._send_submission_feedback_reject(submission_id, seen_reviews)

    def _on_receive_submission(
        self, message: email.message.EmailMessage
    ) -> None:
        self._logger.debug("_on_receive_submission(message)")

        submission_id = base64.b64encode(
            message["Message-ID"].encode()
        ).decode()
        submission_body = message.get_body(
            preferencelist=("html", "plain")
        )
        submission_body_text = (
            submission_body.get_content() if submission_body is not None else ""
        )

        review_request_message = email.message.EmailMessage()
        review_request_message["From"] = (
            f"自动化系学生科协 <{self._config.email_address}>"
        )
        review_request_message["To"] = ", ".join(
            self._config.reviewer_email_addresses
        )
        review_request_message["Subject"] = f"科协周报审核请求 #{submission_id}#"

        review_request_body = f"""<p>请审阅以下投稿并回复：</p>
<ul>
<li>输入 /&zwnj;accept 表示通过；</li>
<li>否则，拒绝。请将拒绝理由包裹在两个`&zwnj;``之间（三连反引号，类似Markdown代码块）。</li>
</ul>
<p>请勿删除主题中的两个"#"号和其间的内容。您的所有回复都不要在本提示中复制内容，否则系统可能无法处理。</p>
<hr>
<p><b>From:</b> {message["From"]}<br>
<b>Sent:</b> {message["Date"]}<br>
<b>To:</b> {message["To"]}<br>
<b>Subject:</b> {message["Subject"]}</p>

{submission_body_text}
"""

        review_request_message.set_content(review_request_body, subtype="html")

        # Forward all attachments
        for attachment in message.iter_attachments():
            filename = attachment.get_filename()
            review_request_message.add_attachment(
                attachment.get_payload(decode=True),
                filename=filename,
                maintype=attachment.get_content_maintype(),
                subtype=attachment.get_content_subtype(),
            )

        self._smtp_conn.send_message(review_request_message)
        self._logger.info("Review request sent successfully")

    def _fetch_email_message(self, message_set: MessageSet) -> email.message.EmailMessage:
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
        message: email.message.EmailMessage = self._email_parser.parsebytes(email_body)  # type: ignore

        assert isinstance(message, email.message.EmailMessage)

        return message

    def _fetch_unseen_message_sets(self) -> List[MessageSet]:
        """Fetch unseen message sets.

        Returns:
            List of message sets.
        """

        self._logger.debug("_fetch_unseen_message_sets()")

        if self._imap_conn is None:
            raise RuntimeError("_imap_client is None")

        _, resp = self._imap_conn.search(None, "(UNSEEN)")
        message_sets = resp[0].split()

        return message_sets

    def _send_publication_notification(
        self, submission_id: str, reviews: List[email.message.EmailMessage]
    ) -> None:
        try:
            self._logger.info(
                "Sending publication notification for submission %s", submission_id
            )
            submission_message = self._get_submission_message(submission_id)
            if submission_message is None:
                self._logger.error(
                    "Could not find original submission message for ID %s",
                    submission_id,
                )
                return

            submission_body = submission_message.get_body(
                preferencelist=("html", "plain")
            )
            submission_body_text = (
                submission_body.get_content() if submission_body is not None else ""
            )

            publication_notification_message = email.message.EmailMessage()
            publication_notification_message["From"] = (
                f"自动化系学生科协 <{self._config.email_address}>"
            )
            publication_notification_message["To"] = ", ".join(
                self._config.reviewer_email_addresses
            )
            publication_notification_message["Subject"] = (
                f"科协周报投稿发布 #{submission_id}#"
            )

            reviewer_email_addresses: List[str] = []
            for review in reviews:
                reviewer_email_addresses.append(review["From"])

            publication_notification_body_text = f"""<p>投稿 #{submission_id[:10]}...# 已通过科协审核并发布，请完成发布流程。</p>
<p>审核人电子邮件地址列表：</p>
<ul>
    {"".join([f"<li>{reviewer_email_address}</li>" for reviewer_email_address in reviewer_email_addresses])}
</ul>
<hr>
<p><b>From:</b> {submission_message["From"]}<br>
<b>Sent:</b> {submission_message["Date"]}<br>
<b>To:</b> {submission_message["To"]}<br>
<b>Subject:</b> {submission_message["Subject"]}</p>

{submission_body_text}
"""

            publication_notification_message.set_content(
                publication_notification_body_text, subtype="html"
            )

            # Forward all attachments
            for attachment in submission_message.iter_attachments():
                filename = attachment.get_filename()
                publication_notification_message.add_attachment(
                    attachment.get_payload(decode=True),
                    filename=filename,
                    maintype=attachment.get_content_maintype(),
                    subtype=attachment.get_content_subtype(),
                )

            self._smtp_conn.send_message(publication_notification_message)
            self._logger.info("Publication notification sent successfully")

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Error sending publication notification: %s", e)

    def _send_submission_feedback_accept(self, submission_id: str) -> None:
        try:
            self._logger.info(
                "Sending acceptance feedback for submission %s", submission_id
            )
            submission_message = self._get_submission_message(submission_id)
            if submission_message is None:
                self._logger.error(
                    "Could not find original submission message for ID %s",
                    submission_id,
                )
                return

            submission_body = submission_message.get_body(
                preferencelist=("html", "plain")
            )
            submission_body_text = (
                submission_body.get_content() if submission_body is not None else ""
            )

            submission_feedback_accept_message = email.message.EmailMessage()
            submission_feedback_accept_message["From"] = (
                f"自动化系学生科协 <{self._config.email_address}>"
            )
            submission_feedback_accept_message["To"] = submission_message["From"]
            submission_feedback_accept_message["Subject"] = "科协周报投稿已通过"
            submission_feedback_accept_message["In-Reply-To"] = submission_message[
                "Message-ID"
            ]

            submission_feedback_accept_body_text = f"""<p>感谢您的投稿，您的投稿已通过科协审核并提交。请注意，这不意味着投稿一定会被发布。</p>
<p>请勿回复此邮件，否则将被视为新的投稿。</p>
<hr>
<p><b>From:</b> {submission_message["From"]}<br>
<b>Sent:</b> {submission_message["Date"]}<br>
<b>To:</b> {submission_message["To"]}<br>
<b>Subject:</b> {submission_message["Subject"]}</p>

{submission_body_text}
"""

            submission_feedback_accept_message.set_content(
                submission_feedback_accept_body_text, subtype="html"
            )

            self._smtp_conn.send_message(submission_feedback_accept_message)
            self._logger.info("Acceptance feedback sent successfully")

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Error sending acceptance feedback: %s", e)

    def _send_submission_feedback_reject(
        self, submission_id: str, reviews: List[email.message.EmailMessage]
    ) -> None:
        try:
            self._logger.info(
                "Sending rejection feedback for submission %s", submission_id
            )
            submission_message = self._get_submission_message(submission_id)
            if submission_message is None:
                self._logger.error(
                    "Could not find original submission message for ID %s",
                    submission_id,
                )
                return

            submission_body = submission_message.get_body(
                preferencelist=("html", "plain")
            )
            submission_body_text = (
                submission_body.get_content() if submission_body is not None else ""
            )

            submission_feedback_reject_message = email.message.EmailMessage()
            submission_feedback_reject_message["From"] = (
                f"自动化系学生科协 <{self._config.email_address}>"
            )
            submission_feedback_reject_message["To"] = submission_message["From"]
            submission_feedback_reject_message["Subject"] = "科协周报投稿未通过"
            submission_feedback_reject_message["In-Reply-To"] = submission_message[
                "Message-ID"
            ]

            review_texts: List[str] = []
            for review in reviews:
                review_body = review.get_body(preferencelist=("html", "plain"))
                review_body_text = (
                    review_body.get_content() if review_body is not None else ""
                )

                # Extract the content between two ```
                review_body_match = re.search(
                    r"```(.*)```", review_body_text, re.DOTALL
                )
                if review_body_match is None:
                    continue

                review_texts.append(review_body_match.group(1))

            review_summary = "\n".join(
                [f"<p>{review_text}</p>" for review_text in review_texts]
            )

            submission_feedback_reject_body_text = f"""<p>感谢您的投稿，您的投稿未通过科协审核。</p>
<p>请根据以下审核意见修改后重新投稿：</p>
{review_summary}
<hr>
<p><b>From:</b> {submission_message["From"]}<br>
<b>Sent:</b> {submission_message["Date"]}<br>
<b>To:</b> {submission_message["To"]}<br>
<b>Subject:</b> {submission_message["Subject"]}</p>

{submission_body_text}
"""

            submission_feedback_reject_message.set_content(
                submission_feedback_reject_body_text, subtype="html"
            )

            self._smtp_conn.send_message(submission_feedback_reject_message)
            self._logger.info("Rejection feedback sent successfully")

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Error sending rejection feedback: %s", e)

    def _get_seen_reviews(self, submission_id: str) -> List[email.message.EmailMessage]:
        if self._imap_conn is None:
            self._logger.error("IMAP client not initialized")
            return []

        self._imap_conn.select("INBOX")
        _, resp = self._imap_conn.search(None, f'(SEEN SUBJECT "#{submission_id}#")')
        message_sets: List[bytes] = resp[0].split()

        email_parser = email.parser.BytesParser(policy=email.policy.default)

        reviews: List[email.message.EmailMessage] = []
        for message_number in message_sets:
            _, resp_fetch = self._imap_conn.fetch(message_number, "(BODY.PEEK[])")  # type: ignore
            email_body: bytes = resp_fetch[0][1]  # type: ignore
            email_message: email.message.EmailMessage = email_parser.parsebytes(
                email_body
            )  # type: ignore

            # Check if the message is a review
            if self._parse_email_category(email_message) != ReviewSystem.EmailCategory.REVIEW:
                continue

            reviews.append(email_message)

        return reviews

    def _get_submission_message(
        self, submission_id: str
    ) -> Optional[email.message.EmailMessage]:
        if self._imap_conn is None:
            self._logger.error("IMAP client not initialized")
            return None

        submission_message_id = base64.b64decode(submission_id).decode()

        self._imap_conn.select("INBOX")
        _, resp = self._imap_conn.search(
            None, f'(HEADER Message-ID "{submission_message_id}")'
        )

        if len(resp[0]) == 0:
            self._logger.warning("No message found with ID %s", submission_message_id)
            return None

        email_parser = email.parser.BytesParser(policy=email.policy.default)

        _, resp_fetch = self._imap_conn.fetch(resp[0], "(BODY.PEEK[])")  # type: ignore
        email_body: bytes = resp_fetch[0][1]  # type: ignore
        return email_parser.parsebytes(email_body)  # type: ignore

    def _parse_email_category(
        self, message: email.message.Message
    ) -> Optional["ReviewSystem.EmailCategory"]:
        """Parse the email category.

        Args:
            message: Email message.

        Returns:
            Email category.
        """

        # Extract email address from From field
        address_header = message["From"]
        if not isinstance(address_header, email.headerregistry.AddressHeader):
            return None
        
        addresses = address_header.addresses
        if len(addresses) == 0:
            return None

        email_from = addresses[0].addr_spec

        # Do not process self-sent emails
        if email_from == self._config.email_address:
            return None

        if email_from in self._config.reviewer_email_addresses:
            return ReviewSystem.EmailCategory.REVIEW
        else:
            return ReviewSystem.EmailCategory.SUBMISSION
