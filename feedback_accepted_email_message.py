import email.headerregistry
import email.message

BODY_CONTENT = """\
<html>
  <head></head>
  <body style="user-select: none;">
    <p>感谢您的投稿，您的投稿已通过评审，进入发布流程。正常情况下，投稿会在 10 个工作日内发布。</p>
    <p>成功发布后，若您在投稿邮件中写明了学号和姓名，稿酬将会自动发放；若未写明，请在发布后联系我们（thuasta@163.com）领取稿酬。</p>
    <p>请勿回复此邮件，如有疑问请联系我们（thuasta@163.com）。</p>
  </body>
</html>
"""


class FeedbackAcceptedEmailMessage(email.message.EmailMessage):
    """Feedback accepted email message."""

    def __init__(
        self,
        to_email_address: str,
        system_email_name: str,
        system_email_address: str,
    ) -> None:
        super().__init__()

        self["From"] = f"{system_email_name} <{system_email_address}>"
        self["To"] = to_email_address
        self["Subject"] = "科协投稿评审通知"

        self.set_content(BODY_CONTENT, subtype="html")
