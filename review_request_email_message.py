import email.headerregistry
import email.message
import html
from typing import List

from email_message_utils import extract_body_content

BODY_CONTENT_TEMPLATE = """\
<html>
  <head></head>
  <body style="user-select: none;">
    <p>请评审投稿并按照以下要求回复：</p>
    <ul>
      <li>输入 /&zwnj;accept 表示通过；</li>
      <li>输入 /&zwnj;reject 表示拒绝，/&zwnj;reject 前的所有内容会被视为拒绝理由并反馈给投稿人。</li>
      <li>如果既没有输入 /&zwnj;accept 也没有输入 /&zwnj;reject ，则评审无效。</li>
      <li>为了实现指令匹配，本要求的文本进行了特殊处理，请不要复制本要求的内容。</li>
    </ul>
    <h3>投稿内容：</h3>
    <p>主题：{submission_subject}</p>
    <p>发件人：{submission_from}</p>
    <p>日期：{submission_date}</p>
    <p>{submission_content}</p>
  </body>
</html>
"""


class ReviewRequestEmailMessage(email.message.EmailMessage):
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
        self["Subject"] = f"科协投稿评审请求 #{submission_id}#"

        self.make_mixed()

        self.attach(body_part)

        for attachment_part in submission_message.iter_attachments():
            self.attach(attachment_part)
