from email.message import EmailMessage
from unittest import TestCase

from app.services.email_import import _normalized_search_criterion, extract_importable_attachments


def build_message_with_attachments() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "rechnung@example.test"
    message["To"] = "fb-rechnung@example.test"
    message["Subject"] = "Rechnung"
    message.set_content("Bitte die Rechnung im Anhang beachten.")
    message.add_attachment(
        b"%PDF-1.7",
        maintype="application",
        subtype="pdf",
        filename="Rechnung_100.pdf",
    )
    message.add_attachment(
        b"<Invoice />",
        maintype="application",
        subtype="xml",
        filename="xrechnung.xml",
    )
    message.add_attachment(
        b"bad",
        maintype="application",
        subtype="octet-stream",
        filename="rechnung.exe",
    )
    message.add_attachment(
        b"image",
        maintype="image",
        subtype="jpeg",
        filename='..\\Förch/Rechnung.jpg',
    )
    return message


class EmailImportTests(TestCase):
    def test_normalizes_supported_search_criteria(self):
        self.assertEqual(_normalized_search_criterion("ALL"), "ALL")
        self.assertEqual(_normalized_search_criterion(" unseen "), "UNSEEN")
        self.assertEqual(_normalized_search_criterion("DELETED"), "UNSEEN")

    def test_extract_importable_invoice_attachments(self):
        attachments = extract_importable_attachments(build_message_with_attachments())

        self.assertEqual([attachment.filename for attachment in attachments], ["Rechnung_100.pdf", "xrechnung.xml", ".. Förch Rechnung.jpg"])
        self.assertEqual([attachment.content_type for attachment in attachments], ["application/pdf", "application/xml", "image/jpeg"])

    def test_ignores_plain_message_without_attachments(self):
        message = EmailMessage()
        message.set_content("Keine Rechnung.")

        self.assertEqual(extract_importable_attachments(message), [])

    def test_ignores_inline_images_and_nameless_parts(self):
        message = EmailMessage()
        message.set_content("Rechnung mit Signatur.")
        message.add_related(
            b"logo",
            maintype="image",
            subtype="png",
            cid="logo",
            filename="logo.png",
        )
        message.add_attachment(
            b"%PDF-1.7",
            maintype="application",
            subtype="pdf",
            filename=None,
        )

        self.assertEqual(extract_importable_attachments(message), [])
