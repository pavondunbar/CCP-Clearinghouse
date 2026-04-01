"""Unit tests for the multilateral netting calculator.

Tests the pure calculate_net_obligations function without any
database dependency. Validates netting logic for single pairs,
partial offsets, multiple instruments, and multiple members.
"""

from decimal import Decimal

from netting_engine.netting import calculate_net_obligations


class TestNettingSinglePair:
    """Test netting with a single buy/sell pair."""

    def test_netting_single_pair_nets_to_zero(self):
        """One buy and one sell of equal quantity nets to zero."""
        positions = [
            {
                "member_id": "member-1",
                "instrument_id": "inst-1",
                "side": "BUY",
                "total_quantity": Decimal("100"),
                "total_value": Decimal("10000"),
                "latest_price": Decimal("100"),
                "settlement_type": "cash",
            },
            {
                "member_id": "member-1",
                "instrument_id": "inst-1",
                "side": "SELL",
                "total_quantity": Decimal("100"),
                "total_value": Decimal("10000"),
                "latest_price": Decimal("100"),
                "settlement_type": "cash",
            },
        ]
        result = calculate_net_obligations(positions)
        assert result == []


class TestNettingPartialOffset:
    """Test netting with partial offsets."""

    def test_netting_partial_offset(self):
        """Multiple trades that partially offset produce residual."""
        positions = [
            {
                "member_id": "member-1",
                "instrument_id": "inst-1",
                "side": "BUY",
                "total_quantity": Decimal("150"),
                "total_value": Decimal("15000"),
                "latest_price": Decimal("100"),
                "settlement_type": "cash",
            },
            {
                "member_id": "member-1",
                "instrument_id": "inst-1",
                "side": "SELL",
                "total_quantity": Decimal("100"),
                "total_value": Decimal("10000"),
                "latest_price": Decimal("100"),
                "settlement_type": "cash",
            },
        ]
        result = calculate_net_obligations(positions)
        assert len(result) == 1
        obl = result[0]
        assert obl["member_id"] == "member-1"
        assert obl["net_quantity"] == Decimal("50")
        assert obl["net_amount"] == Decimal("5000")
        assert obl["settlement_amount"] == Decimal("5000")


class TestNettingMultipleInstruments:
    """Test that netting is performed per-instrument."""

    def test_netting_multiple_instruments(self):
        """Positions in different instruments net independently."""
        positions = [
            {
                "member_id": "member-1",
                "instrument_id": "inst-1",
                "side": "BUY",
                "total_quantity": Decimal("100"),
                "total_value": Decimal("10000"),
                "latest_price": Decimal("100"),
                "settlement_type": "cash",
            },
            {
                "member_id": "member-1",
                "instrument_id": "inst-2",
                "side": "SELL",
                "total_quantity": Decimal("200"),
                "total_value": Decimal("10000"),
                "latest_price": Decimal("50"),
                "settlement_type": "dvp",
            },
        ]
        result = calculate_net_obligations(positions)
        assert len(result) == 2

        by_inst = {o["instrument_id"]: o for o in result}
        assert by_inst["inst-1"]["net_quantity"] == Decimal("100")
        assert by_inst["inst-1"]["net_amount"] == Decimal("10000")
        assert by_inst["inst-2"]["net_quantity"] == Decimal("-200")
        assert by_inst["inst-2"]["net_amount"] == Decimal("-10000")
        assert by_inst["inst-2"]["settlement_amount"] == Decimal("10000")


class TestNettingMultipleMembers:
    """Test netting across three members with cross-trades."""

    def test_netting_multiple_members(self):
        """Three members with overlapping positions net correctly."""
        positions = [
            {
                "member_id": "member-A",
                "instrument_id": "inst-1",
                "side": "BUY",
                "total_quantity": Decimal("300"),
                "total_value": Decimal("30000"),
                "latest_price": Decimal("100"),
                "settlement_type": "cash",
            },
            {
                "member_id": "member-A",
                "instrument_id": "inst-1",
                "side": "SELL",
                "total_quantity": Decimal("100"),
                "total_value": Decimal("10000"),
                "latest_price": Decimal("100"),
                "settlement_type": "cash",
            },
            {
                "member_id": "member-B",
                "instrument_id": "inst-1",
                "side": "BUY",
                "total_quantity": Decimal("50"),
                "total_value": Decimal("5000"),
                "latest_price": Decimal("100"),
                "settlement_type": "cash",
            },
            {
                "member_id": "member-B",
                "instrument_id": "inst-1",
                "side": "SELL",
                "total_quantity": Decimal("200"),
                "total_value": Decimal("20000"),
                "latest_price": Decimal("100"),
                "settlement_type": "cash",
            },
            {
                "member_id": "member-C",
                "instrument_id": "inst-1",
                "side": "SELL",
                "total_quantity": Decimal("50"),
                "total_value": Decimal("5000"),
                "latest_price": Decimal("100"),
                "settlement_type": "cash",
            },
        ]
        result = calculate_net_obligations(positions)
        by_member = {o["member_id"]: o for o in result}

        # member-A: buy 300 - sell 100 = net +200
        assert by_member["member-A"]["net_quantity"] == Decimal("200")
        assert by_member["member-A"]["net_amount"] == Decimal("20000")

        # member-B: buy 50 - sell 200 = net -150
        assert by_member["member-B"]["net_quantity"] == Decimal("-150")
        assert by_member["member-B"]["net_amount"] == Decimal("-15000")
        assert by_member["member-B"]["settlement_amount"] == Decimal(
            "15000"
        )

        # member-C: sell 50 = net -50
        assert by_member["member-C"]["net_quantity"] == Decimal("-50")
        assert by_member["member-C"]["net_amount"] == Decimal("-5000")


class TestNettingEdgeCases:
    """Test edge cases in netting calculation."""

    def test_netting_no_open_trades(self):
        """Empty positions list returns empty obligations."""
        result = calculate_net_obligations([])
        assert result == []

    def test_netting_calculates_settlement_amounts(self):
        """settlement_amount should always be abs(net_amount)."""
        positions = [
            {
                "member_id": "member-1",
                "instrument_id": "inst-1",
                "side": "SELL",
                "total_quantity": Decimal("75"),
                "total_value": Decimal("15000"),
                "latest_price": Decimal("200"),
                "settlement_type": "cash",
            },
        ]
        result = calculate_net_obligations(positions)
        assert len(result) == 1
        obl = result[0]
        # net_quantity = 0 - 75 = -75
        assert obl["net_quantity"] == Decimal("-75")
        # net_amount = -75 * 200 = -15000
        assert obl["net_amount"] == Decimal("-15000")
        # settlement_amount = abs(-15000) = 15000
        assert obl["settlement_amount"] == Decimal("15000")
