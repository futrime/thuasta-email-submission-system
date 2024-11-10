import email.headerregistry
import email.message
import html
from typing import List

from email_message_utils import extract_body_content

BODY_CONTENT_TEMPLATE = """\
<html>
  <head></head>
  <body style="user-select: none;">
    <p>请发布以下投稿：</p>
    <h3>投稿内容：</h3>
    <p>主题：{submission_subject}</p>
    <p>发件人：{submission_from}</p>
    <p>日期：{submission_date}</p>
    <p>{submission_content}</p>
  </body>
</html>
"""


class PublicationRequestEmailMessage(email.message.EmailMessage):
    """Review request email message."""

    def __init__(
        self,
        submission_id: str,
        submission_message: email.message.EmailMessage,
        system_email_name: str,
        system_email_address: str,
        reviewer_email_addresses: List[str],
    ) -> None:
        super().__init__()

        body_part = email.message.MIMEPart()
        body_part.make_related()

        body_part.add_related(
            BODY_CONTENT_TEMPLATE.format(
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
        self["To"] = ", ".join(reviewer_email_addresses)
        self["Subject"] = f"科协投稿发布请求 #{submission_id}#"

        self.make_mixed()

        self.attach(body_part)

        for attachment_part in submission_message.iter_attachments():
            self.attach(attachment_part)
