"""Email delivery service using stdlib smtplib + email.mime.

Configuration is read from environment variables:
    SMTP_HOST      — SMTP server hostname (default: smtp.gmail.com)
    SMTP_PORT      — SMTP port (default: 587)
    SMTP_USER      — login username / sender address
    SMTP_PASSWORD  — login password / app password
    SMTP_FROM      — From address (default: SMTP_USER)
    SMTP_TLS       — enable STARTTLS (default: true)
    APP_URL        — base URL for links in emails (default: http://localhost:3000)

If SMTP_HOST is not set the service logs a warning and silently skips all sends.
"""

import asyncio
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailService:
    """Async-friendly email service wrapping blocking smtplib calls."""

    def __init__(self) -> None:
        self._host = os.getenv("SMTP_HOST", "")
        self._port = int(os.getenv("SMTP_PORT", "587"))
        self._user = os.getenv("SMTP_USER", "")
        self._password = os.getenv("SMTP_PASSWORD", "")
        self._from = os.getenv("SMTP_FROM", "") or self._user
        self._tls = os.getenv("SMTP_TLS", "true").lower() not in ("false", "0", "no")
        self._app_url = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")

        if not self._host:
            logger.warning(
                "SMTP_HOST is not set — email sending is disabled. "
                "Set SMTP_HOST, SMTP_USER, and SMTP_PASSWORD to enable email."
            )

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def send_password_reset(
        self, to_email: str, reset_token: str, username: str
    ) -> None:
        """Send a password-reset link email."""
        reset_url = f"{self._app_url}/auth/reset-password?token={reset_token}"
        subject = "Reset your Nexus password"
        html = _render_password_reset(username=username, reset_url=reset_url)
        plain = (
            f"Hi {username},\n\n"
            f"You requested a password reset for your Nexus account.\n"
            f"Click the link below to reset your password (expires in 1 hour):\n\n"
            f"{reset_url}\n\n"
            f"If you did not request this, please ignore this email.\n\n"
            f"— The Nexus Team"
        )
        await self._send(to_email=to_email, subject=subject, html=html, plain=plain)

    async def send_invite(
        self,
        to_email: str,
        invite_token: str,
        invited_by: str,
        org_name: str,
    ) -> None:
        """Send a workspace-invite email."""
        invite_url = f"{self._app_url}/auth/register?invite={invite_token}"
        subject = f"You've been invited to {org_name} on Nexus"
        html = _render_invite(
            to_email=to_email,
            invited_by=invited_by,
            org_name=org_name,
            invite_url=invite_url,
        )
        plain = (
            f"Hi,\n\n"
            f"{invited_by} has invited you to join {org_name} on Nexus.\n"
            f"Click the link below to accept the invitation (expires in 7 days):\n\n"
            f"{invite_url}\n\n"
            f"— The Nexus Team"
        )
        await self._send(to_email=to_email, subject=subject, html=html, plain=plain)

    async def send_welcome(self, to_email: str, username: str) -> None:
        """Send a welcome email after a user accepts an invite."""
        subject = "Welcome to Nexus!"
        html = _render_welcome(username=username, app_url=self._app_url)
        plain = (
            f"Hi {username},\n\n"
            f"Welcome to Nexus! Your account is now active.\n"
            f"Get started at: {self._app_url}\n\n"
            f"— The Nexus Team"
        )
        await self._send(to_email=to_email, subject=subject, html=html, plain=plain)

    async def send_event_reminder(
        self,
        to_email: str,
        event_title: str,
        event_time: str,
        event_link: str,
    ) -> None:
        """Send a calendar-event reminder email."""
        subject = f"Reminder: {event_title}"
        html = _render_event_reminder(
            event_title=event_title, event_time=event_time, event_link=event_link
        )
        plain = (
            f"This is a reminder for your upcoming event:\n\n"
            f"  {event_title}\n"
            f"  {event_time}\n\n"
            f"Join here: {event_link}\n\n"
            f"— The Nexus Team"
        )
        await self._send(to_email=to_email, subject=subject, html=html, plain=plain)

    async def send_verification_email(self, to_email: str, username: str, verify_token: str) -> None:
        """Send email verification link."""
        verify_url = f"{self._app_url}/verify-email?token={verify_token}"
        subject = "Verify your SecuredDocs email"
        html = _render_verify_email(username=username, verify_url=verify_url)
        plain = (
            f"Hi {username},\n\n"
            f"Please verify your email address by clicking the link below:\n\n"
            f"{verify_url}\n\n"
            f"This link expires in 24 hours.\n\n"
            f"— The SecuredDocs Team"
        )
        await self._send(to_email=to_email, subject=subject, html=html, plain=plain)

    async def send_license_welcome(
        self, to_email: str, username: str, organization: str, plan: str, verify_token: str
    ) -> None:
        """Send license activation welcome email with verification link."""
        verify_url = f"{self._app_url}/verify-email?token={verify_token}"
        app_url = self._app_url
        subject = f"Welcome to SecuredDocs — {organization} is ready"
        html = _render_license_welcome(
            username=username,
            organization=organization,
            plan=plan.title(),
            verify_url=verify_url,
            app_url=app_url,
        )
        plain = (
            f"Hi {username},\n\n"
            f"Your SecuredDocs {plan.title()} plan has been activated for {organization}.\n\n"
            f"Please verify your email: {verify_url}\n\n"
            f"Then log in at: {app_url}/login\n\n"
            f"— The SecuredDocs Team"
        )
        await self._send(to_email=to_email, subject=subject, html=html, plain=plain)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send_sync(self, to_email: str, subject: str, html: str, plain: str) -> None:
        """Blocking send — called via asyncio.to_thread."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from
        msg["To"] = to_email

        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(self._host, self._port) as server:
            server.ehlo()
            if self._tls:
                server.starttls()
                server.ehlo()
            if self._user and self._password:
                server.login(self._user, self._password)
            server.sendmail(self._from, [to_email], msg.as_string())

    async def _send(
        self, to_email: str, subject: str, html: str, plain: str
    ) -> None:
        """Async wrapper — skips silently when SMTP is not configured."""
        if not self._host:
            logger.debug("Email skipped (SMTP not configured): subject=%r to=%r", subject, to_email)
            return
        try:
            await asyncio.to_thread(self._send_sync, to_email, subject, html, plain)
            logger.info("Email sent: subject=%r to=%r", subject, to_email)
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to send email to %r: %s", to_email, exc, exc_info=True)


# ---------------------------------------------------------------------------
# HTML template helpers
# ---------------------------------------------------------------------------

_STYLE = """
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f4f4f5; margin: 0; padding: 0; }
  .wrapper { max-width: 580px; margin: 40px auto; background: #ffffff;
             border-radius: 8px; overflow: hidden;
             box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
  .header  { background: #1a1a2e; padding: 32px 40px; }
  .header h1 { color: #ffffff; margin: 0; font-size: 24px; letter-spacing: -0.5px; }
  .header span { color: #6366f1; }
  .body    { padding: 36px 40px; color: #374151; line-height: 1.6; }
  .body h2 { margin-top: 0; color: #111827; font-size: 20px; }
  .btn     { display: inline-block; margin: 24px 0; padding: 14px 28px;
             background: #6366f1; color: #ffffff; text-decoration: none;
             border-radius: 6px; font-weight: 600; font-size: 15px; }
  .footer  { background: #f9fafb; padding: 20px 40px; border-top: 1px solid #e5e7eb;
             font-size: 12px; color: #9ca3af; }
"""


def _base_template(header_text: str, body_content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>{_STYLE}</style></head>
<body>
<div class="wrapper">
  <div class="header"><h1>Nex<span>us</span></h1><p style="color:#a5b4fc;margin:4px 0 0">{header_text}</p></div>
  <div class="body">{body_content}</div>
  <div class="footer">
    You received this email because an action was taken on your Nexus account.<br>
    If you did not initiate this, you can safely ignore it.
  </div>
</div>
</body></html>"""


def _render_password_reset(username: str, reset_url: str) -> str:
    body = f"""
    <h2>Reset your password</h2>
    <p>Hi <strong>{username}</strong>,</p>
    <p>We received a request to reset the password for your Nexus account. Click the button below
       to choose a new password. This link expires in <strong>1 hour</strong>.</p>
    <a href="{reset_url}" class="btn">Reset Password</a>
    <p style="color:#6b7280;font-size:13px">
      Or copy this URL into your browser:<br>
      <a href="{reset_url}" style="color:#6366f1;word-break:break-all">{reset_url}</a>
    </p>
    <p>If you did not request a password reset, no action is needed — your password remains unchanged.</p>
    """
    return _base_template("Password Reset Request", body)


def _render_invite(to_email: str, invited_by: str, org_name: str, invite_url: str) -> str:
    body = f"""
    <h2>You're invited to join {org_name}</h2>
    <p><strong>{invited_by}</strong> has invited you to collaborate on <strong>{org_name}</strong>
       in Nexus — the enterprise knowledge and retrieval platform.</p>
    <p>Accept the invitation to create your account. This invite expires in <strong>7 days</strong>.</p>
    <a href="{invite_url}" class="btn">Accept Invitation</a>
    <p style="color:#6b7280;font-size:13px">
      Invited address: {to_email}<br>
      Or copy this URL: <a href="{invite_url}" style="color:#6366f1;word-break:break-all">{invite_url}</a>
    </p>
    """
    return _base_template(f"Invitation to {org_name}", body)


def _render_welcome(username: str, app_url: str) -> str:
    body = f"""
    <h2>Welcome to Nexus, {username}!</h2>
    <p>Your account is all set. You now have access to your organization's knowledge base,
       document search, and AI-powered Q&amp;A.</p>
    <a href="{app_url}" class="btn">Open Nexus</a>
    <p>Here are a few things to get started:</p>
    <ul>
      <li>Browse the document library to find relevant resources.</li>
      <li>Ask questions using the AI search to get instant answers.</li>
      <li>Explore team workspaces your admin has added you to.</li>
    </ul>
    """
    return _base_template("Welcome aboard!", body)


def _render_event_reminder(event_title: str, event_time: str, event_link: str) -> str:
    body = f"""
    <h2>Upcoming event reminder</h2>
    <p>This is a friendly reminder that you have an event coming up soon.</p>
    <table style="width:100%;border-collapse:collapse;margin:20px 0">
      <tr>
        <td style="padding:10px 0;color:#6b7280;width:120px">Event</td>
        <td style="padding:10px 0;font-weight:600;color:#111827">{event_title}</td>
      </tr>
      <tr>
        <td style="padding:10px 0;color:#6b7280">Time</td>
        <td style="padding:10px 0;color:#111827">{event_time}</td>
      </tr>
    </table>
    <a href="{event_link}" class="btn">Join Event</a>
    """
    return _base_template("Event Reminder", body)


def _render_verify_email(username: str, verify_url: str) -> str:
    body = f"""
    <h2>Verify your email address</h2>
    <p>Hi <strong>{username}</strong>,</p>
    <p>Click the button below to verify your email address. This link expires in <strong>24 hours</strong>.</p>
    <a href="{verify_url}" class="btn">Verify Email</a>
    <p style="color:#6b7280;font-size:13px">
      Or copy this URL:<br>
      <a href="{verify_url}" style="color:#6366f1;word-break:break-all">{verify_url}</a>
    </p>
    <p>If you did not create a SecuredDocs account, please ignore this email.</p>
    """
    return _base_template("Email Verification", body)


def _render_license_welcome(
    username: str, organization: str, plan: str, verify_url: str, app_url: str
) -> str:
    body = f"""
    <h2>Welcome to SecuredDocs, {username}!</h2>
    <p>Your <strong>{plan}</strong> plan has been activated for <strong>{organization}</strong>.</p>
    <p>As the workspace admin, you can invite your team, upload documents, and configure compliance rules.</p>
    <p style="margin-bottom:8px"><strong>Step 1:</strong> Verify your email address</p>
    <a href="{verify_url}" class="btn">Verify Email</a>
    <p style="margin-top:24px"><strong>Step 2:</strong> Log in to your workspace</p>
    <a href="{app_url}/login" style="display:inline-block;padding:12px 24px;border:1px solid #6366f1;color:#6366f1;text-decoration:none;border-radius:6px;font-weight:600;">Open SecuredDocs</a>
    <p style="margin-top:24px;color:#6b7280;font-size:13px">
      Plan: {plan} · Admin: {username}<br>
      Your data stays on your servers. Always.
    </p>
    """
    return _base_template(f"{organization} — SecuredDocs activated", body)
