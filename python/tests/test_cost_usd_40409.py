"""#40409: SDK types expose the ``cost_usd`` field added by #40388."""

from alterlab import _transport as t


def test_batch_transport_types_declare_cost_usd():
    assert t._BatchResponseRequired.__annotations__["cost_usd"] is str
    assert t._BatchStatusResponseRequired.__annotations__["cost_usd"] is str
    assert t._BatchStatusResponseRequired.__annotations__["credits_used"] is int
    assert "estimated_credits" in t.BatchStatusResponse.__annotations__
