"""
Tests for job dispatch helpers.

Verifies singleton initialization behavior under concurrency.
"""

import threading

from src.jobs import dispatch


def test_get_dispatcher_initializes_singleton_once(monkeypatch):
    """Concurrent get_dispatcher calls should initialize the singleton once."""
    created: list[object] = []
    results: list[object] = []
    errors: list[Exception] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    class DummyDispatcher:
        pass

    def fake_build_dispatcher():
        dispatcher = DummyDispatcher()
        with lock:
            created.append(dispatcher)
        return dispatcher

    monkeypatch.setattr(dispatch, "_DISPATCHER", None)
    monkeypatch.setattr(dispatch, "_build_dispatcher", fake_build_dispatcher)

    def call_get_dispatcher() -> None:
        try:
            barrier.wait()
            dispatcher = dispatch.get_dispatcher()
            with lock:
                results.append(dispatcher)
        except Exception as exc:
            with lock:
                errors.append(exc)

    t1 = threading.Thread(target=call_get_dispatcher)
    t2 = threading.Thread(target=call_get_dispatcher)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == []
    assert len(created) == 1
    assert len(results) == 2
    assert results[0] is results[1]
