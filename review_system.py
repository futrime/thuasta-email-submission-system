import base64
import email
import email.generator
import email.message
import email.parser
import email.policy
import imaplib
import logging
import re
import smtplib
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class EmailCategory(Enum):
    SUBMISSION = "SUBMISSION"
    SUBMISSION_NOTIFICATION = "SUBMISSION_NOTIFICATION"
    SUBMISSION_FEEDBACK_ACCEPT = "SUBMISSION_FEEDBACK_ACCEPT"
    SUBMISSION_FEEDBACK_REJECT = "SUBMISSION_FEEDBACK_REJECT"
    REVIEW_REQUEST = "REVIEW_REQUEST"
    REVIEW = "REVIEW"
    PUBLICATION_NOTIFICATION = "PUBLICATION_NOTIFICATION"


@dataclass
class ReviewSystemConfig:
    email_address: str
    email_password: str
    email_imap_host: str
    email_smtp_host: str
    reviewer_email_address_list: List[str]
    min_review_count: int


class ReviewSystem:
    def __init__(self, config: ReviewSystemConfig) -> None:
        self.config = config
        self.imap_client: Optional[imaplib.IMAP4_SSL] = None
        self.smtp_client = smtplib.SMTP_SSL(self.config.email_smtp_host)
        self.logger = logging.getLogger(__name__)

    def run(self) -> None:
        self._connect()

        assert self.imap_client is not None
        assert self.smtp_client is not None

        self.imap_client.select("INBOX")
        _, resp = self.imap_client.search(None, "(UNSEEN)")
        message_sets: List[bytes] = resp[0].split()
        self.logger.info("Found %d unseen messages", len(message_sets))

        email_parser = email.parser.BytesParser(policy=email.policy.default)

        for message_set in message_sets:
            try:
                _, resp_fetch = self.imap_client.fetch(message_set, "(BODY[])")  # type: ignore
                email_body: bytes = resp_fetch[0][1]  # type: ignore
                email_message: email.message.EmailMessage = email_parser.parsebytes(
                    email_body
                )  # type: ignore

                self._on_receive(email_message)

            except Exception as e:  # pylint: disable=broad-exception-caught
                self.logger.error("Error processing message %s: %s", message_set, e)
                continue

        self._logout()
        self.logger.info("ReviewSystem run completed")

    def _connect(self) -> None:
        self.logger.info("Connecting to email servers...")
        self.imap_client = imaplib.IMAP4_SSL(self.config.email_imap_host)
        self.smtp_client = smtplib.SMTP_SSL(self.config.email_smtp_host)

        self.imap_client.login(self.config.email_address, self.config.email_password)
        self.smtp_client.login(self.config.email_address, self.config.email_password)
        self.logger.info("Successfully connected to email servers")

    def _logout(self) -> None:
        self.logger.info("Logging out from email servers...")
        if self.imap_client is not None:
            self.imap_client.logout()

        if self.smtp_client is not None:
            self.smtp_client.close()
        self.logger.info("Successfully logged out from email servers")

    def _on_receive(self, message: email.message.EmailMessage) -> None:
        email_category = self._get_email_category(message)
        self.logger.info("Processing message with category: %s", email_category)

        match email_category:
            case EmailCategory.SUBMISSION:
                self._on_receive_submission(message)
            case EmailCategory.REVIEW:
                self._on_receive_review(message)
            case None:
                self.logger.warning("Received message with unknown category")
                return

    def _on_receive_submission(
        self, submission_message: email.message.EmailMessage
    ) -> None:
        self.logger.info("Processing new submission")

        self._send_review_request(submission_message)
        self._send_submission_notification(submission_message)

    def _on_receive_review(self, review_message: email.message.EmailMessage) -> None:
        self.logger.info("Processing new review")
        submission_matcher = re.compile(r"#([A-Za-z0-9+\/=]+)#")
        submission_match = submission_matcher.search(review_message["Subject"])
        if submission_match is None:
            self.logger.error("Could not find submission ID in review subject")
            return

        submission_id = submission_match.group(1)
        seen_reviews = self._get_seen_reviews(
            submission_id
        )  # Include the current review
        self.logger.info(
            "Found %d existing reviews for submission %s",
            len(seen_reviews),
            submission_id,
        )

        # If less, wait for more reviews
        # If more, ignore
        if len(seen_reviews) < self.config.min_review_count:
            self.logger.info(
                "Waiting for more reviews (current: %d, required: %d)",
                len(seen_reviews),
                self.config.min_review_count,
            )
            return
        elif len(seen_reviews) > self.config.min_review_count:
            self.logger.info(
                "Received more reviews than required, may be a duplicate (current: %d, required: %d)",
                len(seen_reviews),
                self.config.min_review_count,
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

        if accept_review_count >= self.config.min_review_count:
            self.logger.info(
                "Submission %s accepted with %d/%d accept votes",
                submission_id,
                accept_review_count,
                self.config.min_review_count,
            )
            self._send_publication_notification(submission_id, seen_reviews)
            self._send_submission_feedback_accept(submission_id)
        else:
            self.logger.info(
                "Submission %s rejected with only %d/%d accept votes",
                submission_id,
                accept_review_count,
                self.config.min_review_count,
            )
            self._send_submission_feedback_reject(submission_id, seen_reviews)

    def _send_publication_notification(
        self, submission_id: str, reviews: List[email.message.EmailMessage]
    ) -> None:
        try:
            self.logger.info(
                "Sending publication notification for submission %s", submission_id
            )
            submission_message = self._get_submission_message(submission_id)
            if submission_message is None:
                self.logger.error(
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
                f"自动化系学生科协 <{self.config.email_address}>"
            )
            publication_notification_message["To"] = ", ".join(
                self.config.reviewer_email_address_list
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

            self.smtp_client.send_message(publication_notification_message)
            self.logger.info("Publication notification sent successfully")

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error("Error sending publication notification: %s", e)

    def _send_review_request(
        self, submission_message: email.message.EmailMessage
    ) -> None:
        try:
            self.logger.info("Sending review request")
            submission_id = base64.b64encode(
                submission_message["Message-ID"].encode()
            ).decode()
            submission_body = submission_message.get_body(
                preferencelist=("html", "plain")
            )
            submission_body_text = (
                submission_body.get_content() if submission_body is not None else ""
            )

            review_request_message = email.message.EmailMessage()
            review_request_message["From"] = (
                f"自动化系学生科协 <{self.config.email_address}>"
            )
            review_request_message["To"] = ", ".join(
                self.config.reviewer_email_address_list
            )
            review_request_message["Subject"] = f"科协周报审核请求 #{submission_id}#"

            review_request_body = f"""<p>请审阅以下投稿并回复：</p>
<ul>
    <li>输入 /&zwnj;accept 表示通过；</li>
    <li>否则，拒绝。请将拒绝理由包裹在两个`&zwnj;``之间。</li>
</ul>
<p>请勿删除主题中的两个"#"号和其间的内容。您的所有回复都不要在本提示中复制内容，否则系统可能无法处理。</p>
<hr>
<p><b>From:</b> {submission_message["From"]}<br>
<b>Sent:</b> {submission_message["Date"]}<br>
<b>To:</b> {submission_message["To"]}<br>
<b>Subject:</b> {submission_message["Subject"]}</p>

{submission_body_text}
"""

            review_request_message.set_content(review_request_body, subtype="html")

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
            self.logger.info("Review request sent successfully")

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error("Error sending review request: %s", e)

    def _send_submission_feedback_accept(self, submission_id: str) -> None:
        try:
            self.logger.info(
                "Sending acceptance feedback for submission %s", submission_id
            )
            submission_message = self._get_submission_message(submission_id)
            if submission_message is None:
                self.logger.error(
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
                f"自动化系学生科协 <{self.config.email_address}>"
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

            self.smtp_client.send_message(submission_feedback_accept_message)
            self.logger.info("Acceptance feedback sent successfully")

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error("Error sending acceptance feedback: %s", e)

    def _send_submission_feedback_reject(
        self, submission_id: str, reviews: List[email.message.EmailMessage]
    ) -> None:
        try:
            self.logger.info(
                "Sending rejection feedback for submission %s", submission_id
            )
            submission_message = self._get_submission_message(submission_id)
            if submission_message is None:
                self.logger.error(
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
                f"自动化系学生科协 <{self.config.email_address}>"
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

            self.smtp_client.send_message(submission_feedback_reject_message)
            self.logger.info("Rejection feedback sent successfully")

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error("Error sending rejection feedback: %s", e)

    def _send_submission_notification(
        self, submission_message: email.message.EmailMessage
    ) -> None:
        try:
            self.logger.info("Sending submission notification")
            submission_body = submission_message.get_body(
                preferencelist=("html", "plain")
            )
            submission_body_text = (
                submission_body.get_content() if submission_body is not None else ""
            )

            submission_notification_message = email.message.EmailMessage()
            submission_notification_message["From"] = (
                f"自动化系学生科协 <{self.config.email_address}>"
            )
            submission_notification_message["To"] = submission_message["From"]
            submission_notification_message["Subject"] = "科协周报投稿已收到"
            submission_notification_message["In-Reply-To"] = submission_message[
                "Message-ID"
            ]

            submission_notification_body_text = f"""<p>感谢您的投稿，我们将进行审核，并尽快通知结果。</p>
<p>请勿回复此邮件，否则将被视为新的投稿。</p>
<hr>
<p><b>From:</b> {submission_message["From"]}<br>
<b>Sent:</b> {submission_message["Date"]}<br>
<b>To:</b> {submission_message["To"]}<br>
<b>Subject:</b> {submission_message["Subject"]}</p>

{submission_body_text}
"""

            submission_notification_message.set_content(
                submission_notification_body_text, subtype="html"
            )

            self.smtp_client.send_message(submission_notification_message)
            self.logger.info("Submission notification sent successfully")

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error("Error sending submission notification: %s", e)

    def _get_email_category(
        self, message: email.message.Message
    ) -> Optional[EmailCategory]:
        email_from = ReviewSystem._extract_email_address(message["From"])
        if email_from is None:
            self.logger.warning("Could not extract email address from From field")
            return None

        if email_from == self.config.email_address:
            self.logger.debug("Skipping own email")
            return None  # Do not process own emails

        if email_from in self.config.reviewer_email_address_list:
            return EmailCategory.REVIEW

        return EmailCategory.SUBMISSION

    def _get_seen_reviews(self, submission_id: str) -> List[email.message.EmailMessage]:
        if self.imap_client is None:
            self.logger.error("IMAP client not initialized")
            return []

        self.imap_client.select("INBOX")
        _, resp = self.imap_client.search(None, f'(SEEN SUBJECT "#{submission_id}#")')
        message_sets: List[bytes] = resp[0].split()

        email_parser = email.parser.BytesParser(policy=email.policy.default)

        reviews: List[email.message.EmailMessage] = []
        for message_number in message_sets:
            _, resp_fetch = self.imap_client.fetch(message_number, "(BODY.PEEK[])")  # type: ignore
            email_body: bytes = resp_fetch[0][1]  # type: ignore
            email_message: email.message.EmailMessage = email_parser.parsebytes(
                email_body
            )  # type: ignore

            # Check if the message is a review
            if self._get_email_category(email_message) != EmailCategory.REVIEW:
                continue

            reviews.append(email_message)

        return reviews

    def _get_submission_message(
        self, submission_id: str
    ) -> Optional[email.message.EmailMessage]:
        if self.imap_client is None:
            self.logger.error("IMAP client not initialized")
            return None

        submission_message_id = base64.b64decode(submission_id).decode()

        self.imap_client.select("INBOX")
        _, resp = self.imap_client.search(
            None, f'(HEADER Message-ID "{submission_message_id}")'
        )

        if len(resp[0]) == 0:
            self.logger.warning("No message found with ID %s", submission_message_id)
            return None

        email_parser = email.parser.BytesParser(policy=email.policy.default)

        _, resp_fetch = self.imap_client.fetch(resp[0], "(BODY.PEEK[])")  # type: ignore
        email_body: bytes = resp_fetch[0][1]  # type: ignore
        return email_parser.parsebytes(email_body)  # type: ignore

    @staticmethod
    def _extract_email_address(text: str) -> Optional[str]:
        match = re.search(r"[\w\.+-]+@([\w-]+\.)+[\w-]+", text)
        return match.group(0) if match is not None else None
