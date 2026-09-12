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


def notify_new_images(cfg: Config, image_paths: list[Path]) -> bool:
    """Email every candidate from one run in a single message. Never raises.

    A run can open several active slots at once and generate a candidate for
    each, so the images are batched rather than sent one message per image.
    """
    image_paths = [p for p in image_paths if p.exists()]
    if not image_paths:
        return False
    if not cfg.notify_email:
        return False
    if not (cfg.smtp_user and cfg.smtp_password):
        log.info("SMTP_USER/SMTP_PASSWORD not set; skipping email for %d candidate(s)",
                 len(image_paths))
        return False
    try:
        entries = []
        for path in image_paths:
            meta_path = path.with_suffix(".json")
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                except json.JSONDecodeError:
                    log.warning("Corrupt metadata for %s; emailing without it",
                                path.name)
            entries.append((path, meta, path.read_bytes()))

        count = len(entries)
        msg = EmailMessage()
        msg["Subject"] = (f"New thumbnail candidate: {entries[0][0].name}"
                          if count == 1
                          else f"{count} new thumbnail candidates")
        msg["From"] = cfg.smtp_user
        msg["To"] = cfg.notify_email
        msg.set_content(_body(entries))

        for path, _meta, image in entries:
            subtype = detect_format(image)[0].lstrip(".").replace("jpg", "jpeg")
            msg.add_attachment(image, maintype="image", subtype=subtype,
                               filename=path.name)

        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(msg)
        log.info("Emailed %d candidate(s) to %s: %s", count, cfg.notify_email,
                 ", ".join(p.name for p, _, _ in entries))
        return True
    except Exception as exc:
        # Notification is never worth failing a run over.
        log.warning("Could not email %d candidate(s): %s: %s",
                    len(image_paths), type(exc).__name__, exc)
        return False


def _body(entries: list[tuple[Path, dict, bytes]]) -> str:
    count = len(entries)
    lines = [] if count == 1 else [f"{count} candidates generated this run:", ""]
    for index, (path, meta, _image) in enumerate(entries):
        if count > 1:
            lines.append(f"--- {index + 1} of {count}: {path.name} ---")
        lines.extend(_entry_lines(path.name, meta))
        if index < count - 1:
            lines.append("")
    return "\n".join(lines) + "\n"


def _entry_lines(filename: str, meta: dict) -> list[str]:
    rows = [
        ("File", filename),
        ("Generated", meta.get("generated_at", "")),
        ("Model", meta.get("model", "")),
        ("Provider", meta.get("provider", "")),
        ("Source thumbnail", meta.get("source_thumbnail_id", "")),
    ]
    lines = [f"{label}: {value}" for label, value in rows if value not in ("", None)]
    seed = meta.get("source_description") or meta.get("description")
    if seed:
        lines += ["", "Source description:", seed]
    if meta.get("prompt"):
        lines += ["", "Prompt:", meta["prompt"]]
    return lines
