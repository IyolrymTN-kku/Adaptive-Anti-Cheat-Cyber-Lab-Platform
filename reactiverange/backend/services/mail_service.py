import os
from flask_mail import Message


class MailService:
    def __init__(self, mail):
        self.mail = mail
        self.sender = os.environ.get("MAIL_USERNAME")

    def send_welcome_email(self, recipient, username):
        msg = Message(
            subject="Welcome to ReactiveRange",
            sender=self.sender,
            recipients=[recipient],
            body=(
                f"Hi {username},\n\n"
                "Welcome to ReactiveRange. Your cyber range account is ready.\n"
                "Use MFA on login to keep your account secure."
            ),
        )
        self.mail.send(msg)

    def send_otp_email(self, recipient, otp_code):
        msg = Message(
            subject="ReactiveRange MFA OTP",
            sender=self.sender,
            recipients=[recipient],
            body=(
                "Your ReactiveRange OTP is:\n\n"
                f"{otp_code}\n\n"
                "This code expires in 5 minutes."
            ),
        )
        self.mail.send(msg)
