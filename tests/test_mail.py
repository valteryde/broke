"""Tests for SMTP mail helper."""

from unittest.mock import patch
from ward import test


@test("send_email uses SMTP_SSL on port 465 and authenticates")
def _():
    from app.utils import mail

    settings = {
        "host": "smtp.example.com",
        "port": 465,
        "username": "user@example.com",
        "password": "secret",
        "from": "noreply@example.com",
        "use_tls": True,
    }
    with patch.object(mail, "_load_smtp_settings", return_value=settings):
        with patch("app.utils.mail.smtplib.SMTP_SSL") as ssl_cls:
            with patch("app.utils.mail.smtplib.SMTP") as smtp_cls:
                inst = ssl_cls.return_value
                mail.send_email("dest@example.com", "Subject", "<p>x</p>")
                ssl_cls.assert_called_once_with("smtp.example.com", 465)
                smtp_cls.assert_not_called()
                inst.login.assert_called_once_with("user@example.com", "secret")
                inst.sendmail.assert_called_once()
                inst.quit.assert_called_once()


@test("send_email uses STARTTLS on port 587 when use_tls is true")
def _():
    from app.utils import mail

    settings = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "user@example.com",
        "password": "secret",
        "from": "noreply@example.com",
        "use_tls": True,
    }
    with patch.object(mail, "_load_smtp_settings", return_value=settings):
        with patch("app.utils.mail.smtplib.SMTP_SSL"):
            with patch("app.utils.mail.smtplib.SMTP") as smtp_cls:
                inst = smtp_cls.return_value
                mail.send_email("dest@example.com", "Subject", "<p>x</p>")
                smtp_cls.assert_called_once_with("smtp.example.com", 587)
                inst.starttls.assert_called_once()
                inst.login.assert_called_once_with("user@example.com", "secret")


@test("send_email authenticates on localhost when credentials are set")
def _():
    from app.utils import mail

    settings = {
        "host": "localhost",
        "port": 1025,
        "username": "dev",
        "password": "devpass",
        "from": "from@local.test",
        "use_tls": True,
    }
    with patch.object(mail, "_load_smtp_settings", return_value=settings):
        with patch("app.utils.mail.smtplib.SMTP_SSL"):
            with patch("app.utils.mail.smtplib.SMTP") as smtp_cls:
                inst = smtp_cls.return_value
                mail.send_email("dest@example.com", "Subject", "<p>x</p>")
                inst.starttls.assert_not_called()
                inst.login.assert_called_once_with("dev", "devpass")


@test("send_email still authenticates when use_tls is false on non-local host")
def _():
    from app.utils import mail

    settings = {
        "host": "relay.internal",
        "port": 25,
        "username": "relayuser",
        "password": "relaypass",
        "from": "app@internal",
        "use_tls": False,
    }
    with patch.object(mail, "_load_smtp_settings", return_value=settings):
        with patch("app.utils.mail.smtplib.SMTP_SSL"):
            with patch("app.utils.mail.smtplib.SMTP") as smtp_cls:
                inst = smtp_cls.return_value
                mail.send_email("dest@example.com", "Subject", "<p>x</p>")
                inst.starttls.assert_not_called()
                inst.login.assert_called_once_with("relayuser", "relaypass")


@test("send_email does nothing when SMTP host is empty")
def _():
    from app.utils import mail

    settings = {
        "host": "",
        "port": 587,
        "username": "",
        "password": "",
        "from": "",
        "use_tls": True,
    }
    with patch.object(mail, "_load_smtp_settings", return_value=settings):
        with patch("app.utils.mail.smtplib.SMTP_SSL") as ssl_cls:
            with patch("app.utils.mail.smtplib.SMTP") as smtp_cls:
                mail.send_email("dest@example.com", "Subject", "<p>x</p>")
                smtp_cls.assert_not_called()
                ssl_cls.assert_not_called()
