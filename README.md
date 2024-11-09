# thuasta-email-submission-system

An email-based submission and review system

## Install

Make sure you have Python 3.12 or later installed. Run the following command to install the dependencies:

```shell
pip install -r requirements.txt
```

## Usage

Create a `.env` file in the root directory like this:

```env
EMAIL_ADDRESS=your_email@example.com
EMAIL_PASSWORD=your_email_password
IMAP_HOST=imap.your_email_provider.com
SMTP_HOST=smtp.your_email_provider.com
REVIEWER_EMAIL_ADDRESSES="reviewer1@example.com
reviewer2@example.com"
MIN_REVIEWERS=1
LOGGING_LEVEL=INFO
IS_PERIODICAL=false
```

Run the following command to start the server:

```shell
python main.py
```

## Deploy on GitHub Actions

Create a repository secret `ENV` of the `.env` file content, then enable the GitHub Actions workflow `run.yml`.

## Contributing

PRs accepted.

## License

AGPL-3.0-or-later © Zijian Zhang
