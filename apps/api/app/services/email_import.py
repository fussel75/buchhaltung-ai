from asyncio import to_thread
from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from imaplib import IMAP4, IMAP4_SSL
from io import BytesIO
from pathlib import Path
from re import search, sub
from typing import Any

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.config import get_settings
from app.services.database import create_document_record
from app.services.storage import (
    ALLOWED_UPLOAD_CONTENT_TYPES,
    ALLOWED_UPLOAD_SUFFIXES,
    UploadRejectedError,
    delete_stored_document,
    store_original_document,
)


class EmailImportConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportableEmailAttachment:
    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class FetchedEmailMessage:
    uid: str
    raw_message: bytes


def email_import_is_configured() -> bool:
    settings = get_settings()
    return bool(settings.email_import_host and settings.email_import_username and settings.email_import_password)


def _safe_attachment_filename(filename: str | None) -> str:
    fallback = "rechnung.pdf"
    if not filename:
        return fallback
    safe_name = sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", filename)
    safe_name = sub(r"\s+", " ", safe_name).strip().rstrip(".")
    return safe_name[:180] or fallback


def _is_importable_attachment(filename: str, content_type: str) -> bool:
    suffix = Path(filename).suffix.lower()
    clean_content_type = content_type.split(";", 1)[0].strip().lower() or "application/octet-stream"
    return suffix in ALLOWED_UPLOAD_SUFFIXES and clean_content_type in ALLOWED_UPLOAD_CONTENT_TYPES


def extract_importable_attachments(message: Message) -> list[ImportableEmailAttachment]:
    attachments: list[ImportableEmailAttachment] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        raw_filename = part.get_filename()
        if not raw_filename:
            continue
        filename = _safe_attachment_filename(raw_filename)
        content_type = part.get_content_type().lower()
        disposition = part.get_content_disposition()
        if disposition != "attachment":
            continue
        if content_type.startswith("image/") and part.get("Content-ID"):
            continue
        if not _is_importable_attachment(filename, content_type):
            continue
        content = part.get_payload(decode=True) or b""
        if not content:
            continue
        attachments.append(
            ImportableEmailAttachment(
                filename=filename,
                content_type=content_type,
                content=content,
            )
        )
    return attachments


async def import_email_attachments(tenant_id: str, limit: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not email_import_is_configured():
        raise EmailImportConfigurationError(
            "E-Mail-Import ist noch nicht konfiguriert. Bitte IMAP-Host, Benutzer und Passwort setzen."
        )

    max_messages = max(1, min(limit or settings.email_import_limit, 100))
    imported: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    skipped_attachments = 0
    seen_uids: list[str] = []

    fetched_messages, fetch_failures = await to_thread(_fetch_unseen_messages, max_messages)
    failed.extend(fetch_failures)

    for fetched_message in fetched_messages:
        message_failed = False
        message = BytesParser(policy=policy.default).parsebytes(fetched_message.raw_message)
        attachments = extract_importable_attachments(message)
        skipped_for_message = max(0, _count_named_attachments(message) - len(attachments))
        skipped_attachments += skipped_for_message

        for attachment in attachments:
            try:
                upload = UploadFile(
                    file=BytesIO(attachment.content),
                    filename=attachment.filename,
                    headers=Headers({"content-type": attachment.content_type}),
                )
                stored = None
                stored = await store_original_document(file=upload, tenant_id=tenant_id)
                try:
                    document, is_duplicate = create_document_record(tenant_id=tenant_id, stored=stored)
                except Exception:
                    delete_stored_document(stored)
                    raise
                item = {
                    "filename": attachment.filename,
                    "document_id": document["id"],
                    "is_duplicate": is_duplicate,
                }
                if is_duplicate:
                    delete_stored_document(stored)
                    duplicates.append(item)
                else:
                    imported.append(item)
            except UploadRejectedError as error:
                message_failed = True
                failed.append({"filename": attachment.filename, "error": str(error)})
            except Exception as error:
                message_failed = True
                failed.append({"filename": attachment.filename, "error": f"Import fehlgeschlagen: {error.__class__.__name__}"})

        if settings.email_import_mark_seen and attachments and not skipped_for_message and not message_failed:
            seen_uids.append(fetched_message.uid)

    if seen_uids:
        await to_thread(_mark_messages_seen, seen_uids)

    return {
        "scanned_messages": len(fetched_messages) + len(fetch_failures),
        "imported": imported,
        "duplicates": duplicates,
        "failed": failed,
        "skipped_attachments": skipped_attachments,
    }


def _fetch_unseen_messages(max_messages: int) -> tuple[list[FetchedEmailMessage], list[dict[str, str]]]:
    settings = get_settings()
    fetched_messages: list[FetchedEmailMessage] = []
    failed: list[dict[str, str]] = []
    client = _connect_imap()
    try:
        status, _ = client.select(settings.email_import_mailbox)
        if status != "OK":
            raise EmailImportConfigurationError(f"Postfach konnte nicht geöffnet werden: {settings.email_import_mailbox}")

        status, payload = client.uid("search", None, "UNSEEN")
        if status != "OK":
            raise EmailImportConfigurationError("Postfach konnte nicht durchsucht werden.")

        message_uids = (payload[0] or b"").split()
        for uid in message_uids[-max_messages:]:
            uid_text = uid.decode("ascii", errors="ignore")
            message_size = _fetch_message_size(client, uid)
            if message_size and message_size > settings.email_import_max_message_bytes:
                failed.append(
                    {
                        "message_uid": uid_text,
                        "error": f"Nachricht ist größer als das Import-Limit von {settings.email_import_max_message_bytes} Bytes.",
                    }
                )
                continue
            status, data = client.uid("fetch", uid, "(RFC822)")
            if status != "OK":
                failed.append({"message_uid": uid_text, "error": "Nachricht konnte nicht gelesen werden."})
                continue

            raw_message = next((item[1] for item in data if isinstance(item, tuple) and item[1]), None)
            if not raw_message:
                failed.append({"message_uid": uid_text, "error": "Nachricht war leer."})
                continue
            fetched_messages.append(FetchedEmailMessage(uid=uid_text, raw_message=raw_message))
    finally:
        _close_imap(client)
    return fetched_messages, failed


def _fetch_message_size(client: IMAP4, uid: bytes) -> int | None:
    status, data = client.uid("fetch", uid, "(RFC822.SIZE)")
    if status != "OK":
        return None
    payload = b" ".join(item[0] if isinstance(item, tuple) else item for item in data if item)
    match = search(rb"RFC822\.SIZE\s+(\d+)", payload)
    return int(match.group(1)) if match else None


def _mark_messages_seen(uids: list[str]) -> None:
    if not uids:
        return
    settings = get_settings()
    client = _connect_imap()
    try:
        status, _ = client.select(settings.email_import_mailbox)
        if status != "OK":
            raise EmailImportConfigurationError(f"Postfach konnte nicht geöffnet werden: {settings.email_import_mailbox}")
        for uid in uids:
            client.uid("store", uid, "+FLAGS", "(\\Seen)")
    finally:
        _close_imap(client)


def _connect_imap() -> IMAP4:
    settings = get_settings()
    client_class = IMAP4_SSL if settings.email_import_use_ssl else IMAP4
    client = client_class(settings.email_import_host, settings.email_import_port)
    client.login(settings.email_import_username, settings.email_import_password)
    return client


def _close_imap(client: IMAP4) -> None:
    try:
        client.close()
    except Exception:
        pass
    client.logout()


def _count_named_attachments(message: Message) -> int:
    count = 0
    for part in message.walk():
        if part.is_multipart():
            continue
        if part.get_filename() and part.get_content_disposition() == "attachment":
            count += 1
    return count
