import email.headerregistry
import email.message
import re
from typing import Optional


def calc_submission_id_from_message_id(message_id: str) -> str:
    """Calculate submission ID from a message.

    Args:
        message: Message to calculate submission ID from.

    Returns:
        Submission ID.
    """

    return message_id


def calc_message_id_from_submission_id(submission_id: str) -> str:
    """Calculate message ID from a submission ID.

    Args:
        submission_id: Submission ID to calculate message ID from.

    Returns:
        Message ID.
    """

    return submission_id


def extract_body_content(message: email.message.EmailMessage) -> Optional[str]:
    """Extract body content from a message.

    Args:
        message: Message to extract body content from.

    Returns:
        Body content.
    """

    submission_body = message.get_body(preferencelist=("html", "plain"))
    submission_body_content = (
        str(submission_body.get_content()) if submission_body is not None else None
    )
    return submission_body_content


def extract_first_from_address(message: email.message.EmailMessage) -> Optional[str]:
    """Extract the first from address from a message.

    Args:
        message: Message to extract from address from.

    Returns:
        From address.
    """

    address_header = message["From"]
    if not isinstance(address_header, email.headerregistry.AddressHeader):
        return None

    addresses = address_header.addresses
    return addresses[0].addr_spec if len(addresses) > 0 else None


def extract_submission_id_from_subject(
    message: email.message.EmailMessage,
) -> Optional[str]:
    """Extract submission ID from a subject.

    Args:
        subject: Subject to extract submission ID from.

    Returns:
        Submission ID.
    """

    subject = str(message["Subject"])

    submission_matcher = re.compile(r"#(.+)#")
    submission_match = submission_matcher.search(subject)
    return submission_match.group(1) if submission_match is not None else None
