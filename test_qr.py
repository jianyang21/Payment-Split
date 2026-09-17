"""Self-check for the pure logic in qr.py. Run: python test_qr.py"""
from decimal import Decimal

from qr import AmountError, parse_amount, split_amount


def test_split_amount():
    assert split_amount(1999) == [Decimal("1999.00")]
    assert split_amount(2000) == [Decimal("1999.00"), Decimal("1.00")]
    assert split_amount(4000) == [Decimal("1999.00"), Decimal("1999.00"), Decimal("2.00")]
    assert sum(split_amount(4000)) == Decimal("4000.00")


def test_parse_amount():
    assert parse_amount("25") == Decimal("25.00")
    assert parse_amount("199.505") == Decimal("199.51")  # ROUND_HALF_UP
    for bad in ("0", "-5", "abc", ""):
        try:
            parse_amount(bad)
            assert False, f"expected AmountError for {bad!r}"
        except AmountError:
            pass


if __name__ == "__main__":
    test_split_amount()
    test_parse_amount()
    print("ok")
