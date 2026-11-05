import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.live_tickets import OneTimeTicketStore


def test_ticket_is_bound_to_user_and_can_be_consumed_once():
    store = OneTimeTicketStore(token_factory=lambda: "ticket-1")
    ticket = store.issue("creator")
    assert store.consume(ticket) == "creator"
    assert store.consume(ticket) is None


def test_ticket_expires():
    now = [100.0]
    store = OneTimeTicketStore(
        ttl_seconds=10,
        clock=lambda: now[0],
        token_factory=lambda: "ticket-expiring",
    )
    ticket = store.issue("creator")
    now[0] = 111.0
    assert store.consume(ticket) is None


def test_ticket_rejects_empty_user_and_empty_ticket():
    store = OneTimeTicketStore(token_factory=lambda: "ticket-2")
    try:
        store.issue("")
    except ValueError:
        pass
    else:
        raise AssertionError("An empty user must be rejected.")
    assert store.consume("") is None
