import smtplib
import random

def send_otp_email(to_email, otp):
    from_email = "youremail@gmail.com"
    password = "your_app_password"  # Use App Password, not Gmail main password
    subject = "Your OTP for Conference Registration"
    body = f"Your OTP is: {otp}"

    message = f"Subject: {subject}\n\n{body}"

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(from_email, password)
    server.sendmail(from_email, to_email, message)
    server.quit()
