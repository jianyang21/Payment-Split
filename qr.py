import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from urllib.parse import quote

import qrcode
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError

load_dotenv()


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            "Copy .env.example to .env and fill in your own values."
        )
    return value


PAYEE_VPA = _require_env("PAYEE_VPA")
PAYEE_NAME = _require_env("PAYEE_NAME")
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

# Sanity ceiling on a single request. Without this, a huge input (accidental
# or malicious) would try to create tens of thousands of QR codes and
# database writes in one go.
MAX_TOTAL_AMOUNT = Decimal("200000")

# ponytail: links expire after this long regardless of payment status, since
# there's no UPI webhook to know which ones were actually paid (a real PSP
# integration like Razorpay/Cashfree would be the upgrade path for that).
LINK_EXPIRY_SECONDS = 7 * 24 * 60 * 60  # 7 days

try:
    links_collection.create_index("payment_id", unique=True)
    try:
        # Auto-delete old links so an unused/ignored QR doesn't sit in Mongo
        # forever. Doesn't distinguish paid vs. unpaid (see status note above).
        links_collection.create_index("created_at", expireAfterSeconds=LINK_EXPIRY_SECONDS)
    except OperationFailure as exc:
        if exc.code != 85:  # not IndexOptionsConflict
            raise
        # TTL index exists with a different expiry than LINK_EXPIRY_SECONDS
        # (someone changed the constant) — update it in place instead of
        # dropping/recreating.
        db.command(
            "collMod",
            links_collection.name,
            index={"keyPattern": {"created_at": 1}, "expireAfterSeconds": LINK_EXPIRY_SECONDS},
        )
except PyMongoError as exc:
    print(f"Warning: could not ensure indexes (Mongo unreachable?): {exc}")


class AmountError(ValueError):
    """Raised when a user supplied payment amount is not usable."""


def parse_amount(raw) -> Decimal:
    """Parse and validate a user supplied amount. Raises AmountError on bad input."""
    try:
        value = Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise AmountError("Enter a valid amount, like 25 or 199.50.")

    if value <= 0:
        raise AmountError("Amount must be greater than zero.")
    if value > MAX_TOTAL_AMOUNT:
        raise AmountError(f"Amount must be {MAX_TOTAL_AMOUNT:,.0f} rupees or less.")
    return value


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
        "created_at": datetime.now(timezone.utc),
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


def generate_payment_qr(amount: Decimal):
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
