"""Email notifications for newly generated thumbnail candidates.

Sent over SMTP because the scheduled GitHub Action runs unattended: it needs
its own credentials rather than an interactive mail session. Configure with
the SMTP_USER / SMTP_PASSWORD secrets; without them notification is skipped
and the run continues normally.
"""

import json
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from .config import Config
from .imaging import detect_format

log = logging.getLogger(__name__)


def notify_new_image(cfg: Config, image_path: Path) -> bool:
    """Email the generated image and its details. Never raises."""
    if not cfg.notify_email:
        return False
    if not (cfg.smtp_user and cfg.smtp_password):
        log.info("SMTP_USER/SMTP_PASSWORD not set; skipping email for %s",
                 image_path.name)
        return False
    try:
        meta = {}
        meta_path = image_path.with_suffix(".json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
        image = image_path.read_bytes()

        msg = EmailMessage()
        msg["Subject"] = f"New thumbnail candidate: {image_path.name}"
        msg["From"] = cfg.smtp_user
        msg["To"] = cfg.notify_email
        msg.set_content(_body(image_path.name, meta))

        subtype = detect_format(image)[0].lstrip(".").replace("jpg", "jpeg")
        msg.add_attachment(image, maintype="image", subtype=subtype,
                           filename=image_path.name)

        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(msg)
        log.info("Emailed %s to %s", image_path.name, cfg.notify_email)
        return True
    except Exception as exc:
        # Notification is never worth failing a run over.
        log.warning("Could not email %s: %s: %s",
                    image_path.name, type(exc).__name__, exc)
        return False


def _body(filename: str, meta: dict) -> str:
    rows = [
        ("File", filename),
        ("Generated", meta.get("generated_at", "")),
        ("Model", meta.get("model", "")),
        ("Provider", meta.get("provider", "")),
        ("Source thumbnail", meta.get("source_thumbnail_id", "")),
        ("Prompt tokens", meta.get("prompt_tokens", "")),
        ("Output tokens", meta.get("output_tokens", "")),
        ("Total tokens", meta.get("total_tokens", "")),
        ("Estimated cost (USD)", meta.get("estimated_cost_usd", "")),
    ]
    lines = [f"{label}: {value}" for label, value in rows if value not in ("", None)]
    if meta.get("description"):
        lines += ["", "Source description:", meta["description"]]
    if meta.get("prompt"):
        lines += ["", "Prompt:", meta["prompt"]]
    return "\n".join(lines) + "\n"
