import os
import uuid
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from urllib.parse import quote

import qrcode
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

PAYEE_VPA = os.environ["PAYEE_VPA"]
PAYEE_NAME = os.environ["PAYEE_NAME"]
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")

# 1. Connect to your MongoDB setup
db_client = MongoClient(MONGO_URI)
db = db_client["payments"]
links_collection = db["links"]

# UPI QR codes above this amount need extra verification on many apps, so any
# payment over this gets split across several QR codes, none exceeding it.
MAX_QR_AMOUNT = Decimal("1999")
SPLIT_THRESHOLD = Decimal("2000")


def _to_amount(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def split_amount(amount) -> list[Decimal]:
    """Split an amount into chunks that never exceed MAX_QR_AMOUNT.

    Amounts strictly below SPLIT_THRESHOLD stay as a single QR; amounts at
    or above it always get split, so no QR is ever generated for 2000 or more.

    e.g. 4000 -> [1999, 1999, 2]; 2000 -> [1999, 1]
    """
    total = _to_amount(amount)
    if total < SPLIT_THRESHOLD:
        return [total]

    chunks = []
    remaining = total
    while remaining > MAX_QR_AMOUNT:
        chunks.append(MAX_QR_AMOUNT)
        remaining -= MAX_QR_AMOUNT
    if remaining > 0:
        chunks.append(remaining)
    return chunks


def render_qr_png(data: str) -> bytes:
    """Render `data` as a QR code PNG, entirely in memory (no disk I/O)."""
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer)
    return buffer.getvalue()


def _create_single_qr(amount: Decimal, group_id: str, part: int, total_parts: int):
    payment_id = str(uuid.uuid4())

    # Build the UPI deep link so scanning opens a UPI app (GPay/PhonePe/etc.)
    # directly at a prefilled payment screen for PAYEE_VPA.
    upi_url = (
        "upi://pay"
        f"?pa={quote(PAYEE_VPA)}"
        f"&pn={quote(PAYEE_NAME)}"
        f"&am={amount:.2f}"
        "&cu=INR"
        f"&tn={quote(f'Payment {group_id[:8]} {part}/{total_parts}')}"
    )

    # Our own status page for this payment (not encoded in the QR).
    status_url = f"{BASE_URL}/pay/{payment_id}"

    payment_document = {
        "payment_id": payment_id,
        "group_id": group_id,
        "part": part,
        "total_parts": total_parts,
        "amount": float(amount),
        "status": "pending",
        "upi_url": upi_url,
        "status_url": status_url,
    }
    links_collection.insert_one(payment_document)
    print(f"Payment saved to database with ID: {payment_id} (part {part}/{total_parts}, amount {amount})")

    return {
        "payment_id": payment_id,
        "amount": float(amount),
        "upi_url": upi_url,
        "part": part,
        "total_parts": total_parts,
    }


def generate_payment_qr(amount: float):
    """Generate one or more payment QR codes for `amount`.

    Amounts over SPLIT_THRESHOLD are split into multiple QR codes, each
    capped at MAX_QR_AMOUNT, so no single QR code is used to collect more
    than that amount. Always returns a list of dicts (one entry per QR).
    QR images themselves are rendered on demand by the /qrcodes/<id>.png
    route (see render_qr_png) rather than saved to disk, so this works on
    read-only/ephemeral filesystems like Vercel's.
    """
    chunks = split_amount(amount)
    group_id = str(uuid.uuid4())
    total_parts = len(chunks)

    return [
        _create_single_qr(chunk, group_id, part, total_parts)
        for part, chunk in enumerate(chunks, start=1)
    ]


if __name__ == "__main__":
    for qr_info in generate_payment_qr(4000):
        print(qr_info)
