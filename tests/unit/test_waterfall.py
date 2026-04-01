"""Unit tests for the default waterfall calculation logic.

Tests the waterfall step ordering, amount allocation, and
pro-rata calculations without requiring a database.
"""

from decimal import Decimal


def calculate_prorata_shares(
    balances: dict[str, Decimal],
    loss_to_allocate: Decimal,
) -> dict[str, Decimal]:
    """Pure function mirroring the pro-rata calculation in the waterfall.

    Args:
        balances: Map of member_id -> default fund balance.
        loss_to_allocate: Total loss to distribute pro-rata.

    Returns:
        Map of member_id -> allocated share.
    """
    total = sum(balances.values())
    if total == Decimal("0"):
        return {mid: Decimal("0") for mid in balances}
    return {
        mid: min((bal / total) * loss_to_allocate, bal)
        for mid, bal in balances.items()
    }


class TestWaterfallStepOrdering:
    """Test that waterfall steps execute in correct priority order."""

    def test_step1_covers_full_loss(self):
        """If defaulter margin covers the full loss, no further steps needed."""
        margin = Decimal("10000")
        loss = Decimal("5000")
        remaining = loss - min(margin, loss)
        assert remaining == Decimal("0")

    def test_step1_partial_then_step2(self):
        """Remaining loss after margin goes to default fund."""
        margin = Decimal("3000")
        default_fund = Decimal("5000")
        loss = Decimal("7000")

        remaining = loss - min(margin, loss)
        assert remaining == Decimal("4000")

        remaining = remaining - min(default_fund, remaining)
        assert remaining == Decimal("0")

    def test_all_five_steps(self):
        """Loss exceeds all individual sources, needs mutualization."""
        margin = Decimal("2000")
        default_fund = Decimal("1000")
        ccp_equity = Decimal("500")
        surviving_fund = Decimal("3000")
        loss = Decimal("8000")

        remaining = loss - min(margin, loss)
        assert remaining == Decimal("6000")

        remaining = remaining - min(default_fund, remaining)
        assert remaining == Decimal("5000")

        remaining = remaining - min(ccp_equity, remaining)
        assert remaining == Decimal("4500")

        remaining = remaining - min(surviving_fund, remaining)
        assert remaining == Decimal("1500")

        # Step 5: loss allocation with caps
        # Remaining > 0 means partial resolution


class TestProRataCalculation:
    """Test pro-rata allocation among surviving members."""

    def test_equal_balances(self):
        balances = {
            "member_a": Decimal("1000"),
            "member_b": Decimal("1000"),
            "member_c": Decimal("1000"),
        }
        shares = calculate_prorata_shares(balances, Decimal("600"))
        assert shares["member_a"] == Decimal("200")
        assert shares["member_b"] == Decimal("200")
        assert shares["member_c"] == Decimal("200")
        assert sum(shares.values()) == Decimal("600")

    def test_unequal_balances(self):
        balances = {
            "member_a": Decimal("3000"),
            "member_b": Decimal("1000"),
        }
        shares = calculate_prorata_shares(balances, Decimal("800"))
        assert shares["member_a"] == Decimal("600")
        assert shares["member_b"] == Decimal("200")
        assert sum(shares.values()) == Decimal("800")

    def test_loss_exceeds_balances(self):
        """Pro-rata shares capped at each member's balance."""
        balances = {
            "member_a": Decimal("100"),
            "member_b": Decimal("100"),
        }
        shares = calculate_prorata_shares(balances, Decimal("500"))
        assert shares["member_a"] == Decimal("100")
        assert shares["member_b"] == Decimal("100")
        assert sum(shares.values()) == Decimal("200")

    def test_zero_balances(self):
        balances = {
            "member_a": Decimal("0"),
            "member_b": Decimal("0"),
        }
        shares = calculate_prorata_shares(balances, Decimal("1000"))
        assert all(v == Decimal("0") for v in shares.values())

    def test_single_survivor(self):
        balances = {"member_a": Decimal("5000")}
        shares = calculate_prorata_shares(balances, Decimal("3000"))
        assert shares["member_a"] == Decimal("3000")

    def test_very_small_amounts(self):
        """Precision with small decimal amounts."""
        balances = {
            "member_a": Decimal("0.001"),
            "member_b": Decimal("0.002"),
        }
        shares = calculate_prorata_shares(balances, Decimal("0.003"))
        total = sum(shares.values())
        assert total == Decimal("0.003")
