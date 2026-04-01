"""Unit tests for margin calculation functions."""

from decimal import Decimal

from margin_engine.calculator import calculate_initial_margin, calculate_variation_margin


class TestInitialMargin:
    """Test IM calculation: abs(net_quantity) * latest_price * margin_rate_im."""

    def test_long_position(self):
        result = calculate_initial_margin(
            net_quantity=Decimal("10"),
            latest_price=Decimal("65000"),
            margin_rate_im=Decimal("0.1"),
        )
        assert result == Decimal("65000")

    def test_short_position(self):
        result = calculate_initial_margin(
            net_quantity=Decimal("-5"),
            latest_price=Decimal("3500"),
            margin_rate_im=Decimal("0.12"),
        )
        assert result == Decimal("2100")

    def test_zero_position(self):
        result = calculate_initial_margin(
            net_quantity=Decimal("0"),
            latest_price=Decimal("65000"),
            margin_rate_im=Decimal("0.1"),
        )
        assert result == Decimal("0")

    def test_fractional_quantity(self):
        result = calculate_initial_margin(
            net_quantity=Decimal("0.5"),
            latest_price=Decimal("65000"),
            margin_rate_im=Decimal("0.1"),
        )
        assert result == Decimal("3250.0")


class TestVariationMargin:
    """Test VM calculation: (current_price - previous_mark) * net_quantity."""

    def test_price_increase_long(self):
        """Long position with price increase → member receives."""
        result = calculate_variation_margin(
            net_quantity=Decimal("10"),
            current_price=Decimal("66000"),
            previous_mark=Decimal("65000"),
        )
        assert result == Decimal("10000")

    def test_price_decrease_long(self):
        """Long position with price decrease → member owes."""
        result = calculate_variation_margin(
            net_quantity=Decimal("10"),
            current_price=Decimal("64000"),
            previous_mark=Decimal("65000"),
        )
        assert result == Decimal("-10000")

    def test_price_increase_short(self):
        """Short position with price increase → member owes."""
        result = calculate_variation_margin(
            net_quantity=Decimal("-5"),
            current_price=Decimal("66000"),
            previous_mark=Decimal("65000"),
        )
        assert result == Decimal("-5000")

    def test_price_decrease_short(self):
        """Short position with price decrease → member receives."""
        result = calculate_variation_margin(
            net_quantity=Decimal("-5"),
            current_price=Decimal("64000"),
            previous_mark=Decimal("65000"),
        )
        assert result == Decimal("5000")

    def test_no_price_change(self):
        result = calculate_variation_margin(
            net_quantity=Decimal("10"),
            current_price=Decimal("65000"),
            previous_mark=Decimal("65000"),
        )
        assert result == Decimal("0")

    def test_zero_position(self):
        result = calculate_variation_margin(
            net_quantity=Decimal("0"),
            current_price=Decimal("66000"),
            previous_mark=Decimal("65000"),
        )
        assert result == Decimal("0")
