import email.headerregistry
import email.message
import html
from typing import List

from email_message_utils import extract_body_content

BODY_CONTENT_TEMPLATE = """\
<html>
  <head></head>
  <body style="user-select: none;">
    <p>感谢您的投稿，您的投稿暂未通过评审，请根据以下评审意见修改后重新投稿。</p>
    <ul>
      {review_feedback}
    </ul>
    <p>请勿回复此邮件，如有疑问请联系我们（thuasta@163.com）。</p>
    <h3>投稿内容：</h3>
    <p>主题：{submission_subject}</p>
    <p>发件人：{submission_from}</p>
    <p>日期：{submission_date}</p>
    <p>{submission_content}</p>
  </body>
</html>
"""

REVIEW_FEEDBACK_TEMPLATE = """\
<li>{content}</li>
"""


class FeedbackRejectedEmailMessage(email.message.EmailMessage):
    """Feedback rejected email message."""

    def __init__(
        self,
        to_email_address: str,
        submission_message: email.message.EmailMessage,
        system_email_name: str,
        system_email_address: str,
        review_feedbacks: List[str],
    ) -> None:
        super().__init__()

        body_part = email.message.MIMEPart()
        body_part.make_related()

        body_part.add_related(
            BODY_CONTENT_TEMPLATE.format(
                review_feedback="\n".join(
                    [
                        REVIEW_FEEDBACK_TEMPLATE.format(content=html.escape(content))
                        for content in review_feedbacks
                    ]
                ),
                submission_subject=html.escape(submission_message["Subject"]),
                submission_from=html.escape(submission_message["From"]),
                submission_date=html.escape(submission_message["Date"]),
                submission_content=extract_body_content(submission_message) or "",
            ),
            subtype="html",
        )

        for part in submission_message.walk():
            if (
                not part.is_attachment()
                and part.get_content_maintype() != "multipart"
                and part.get_content_maintype() != "text"
            ):
                body_part.attach(part)

        self["From"] = f"{system_email_name} <{system_email_address}>"
        self["To"] = to_email_address
        self["In-Reply-To"] = submission_message["Message-ID"]
        self["Subject"] = "科协投稿评审通知"

        self.make_mixed()

        self.attach(body_part)

        for attachment_part in submission_message.iter_attachments():
            self.attach(attachment_part)
