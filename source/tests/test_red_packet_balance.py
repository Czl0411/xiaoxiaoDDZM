import app.database as database_module
from app.database import Database


def split_packet(total_amount, total_count):
    remaining_amount = total_amount
    remaining_count = total_count
    shares = []
    while remaining_count:
        amount = Database._balanced_red_packet_amount(
            remaining_amount,
            remaining_count,
            total_amount,
            total_count,
        )
        shares.append(amount)
        remaining_amount -= amount
        remaining_count -= 1
    return shares


def test_balanced_packet_cannot_be_drained_by_early_high_rolls(monkeypatch):
    monkeypatch.setattr(
        database_module.random,
        "triangular",
        lambda lower, upper, mode: upper,
    )

    shares = split_packet(100, 10)

    assert sum(shares) == 100
    assert min(shares) >= 6
    assert max(shares) <= 14
    assert shares[-1] != 1


def test_balanced_packet_cannot_leave_a_giant_last_share(monkeypatch):
    monkeypatch.setattr(
        database_module.random,
        "triangular",
        lambda lower, upper, mode: lower,
    )

    shares = split_packet(100, 10)

    assert sum(shares) == 100
    assert min(shares) >= 6
    assert max(shares) <= 14


def test_balanced_packet_handles_small_totals_without_losing_points():
    shares = split_packet(10, 3)

    assert len(shares) == 3
    assert sum(shares) == 10
    assert all(isinstance(amount, int) and amount >= 1 for amount in shares)


def test_one_point_shares_only_when_the_math_requires_them(monkeypatch):
    monkeypatch.setattr(
        database_module.random,
        "triangular",
        lambda lower, upper, mode: upper,
    )

    shares = split_packet(11, 10)

    assert sum(shares) == 11
    assert shares.count(1) == 9
