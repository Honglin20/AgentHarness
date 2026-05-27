"""Tests for user isolation in BenchmarkStore."""
from __future__ import annotations

import pytest

from harness.benchmark_store import BenchmarkStore


@pytest.fixture
def store(tmp_path):
    return BenchmarkStore(benchmarks_dir=tmp_path)


class TestBenchmarkStoreIsolation:
    def test_save_and_list_with_user_id(self, store):
        """User A's benchmarks filtered from User B's.

        Benchmarks without user_id are only visible when no filter is applied
        (or when explicitly filtering for user_id="default").
        """
        store.save_benchmark("bm-a", [{"label": "Task A"}], user_id="user_a")
        store.save_benchmark("bm-b", [{"label": "Task B"}], user_id="user_b")
        store.save_benchmark("bm-shared", [{"label": "Shared"}])  # no user_id

        # user_a sees only their own benchmark (bm-shared has user_id="default")
        assert len(store.list_benchmarks(user_id="user_a")) == 1  # bm-a
        # user_b sees only their own benchmark
        assert len(store.list_benchmarks(user_id="user_b")) == 1  # bm-b
        # no filter returns all
        assert len(store.list_benchmarks()) == 3
        # shared benchmarks visible when filtering for "default"
        assert len(store.list_benchmarks(user_id="default")) == 1  # bm-shared

    def test_list_results_filtered_by_user(self, store):
        """Results filtered by user_id.

        Results without user_id have implicit user_id="default".
        """
        store.save_benchmark("test-bm", [{"label": "T"}])
        store.save_result("test-bm", {"run_id": "r1", "user_id": "user_a", "status": "completed"})
        store.save_result("test-bm", {"run_id": "r2", "user_id": "user_b", "status": "completed"})
        store.save_result("test-bm", {"run_id": "r3", "status": "completed"})  # no user_id → "default"

        # user_a sees only their own result (r3 is "default", not "user_a")
        results_a = store.list_results("test-bm", user_id="user_a")
        assert len(results_a) == 1
        assert results_a[0]["run_id"] == "r1"

        # user_b sees only their own result
        results_b = store.list_results("test-bm", user_id="user_b")
        assert len(results_b) == 1
        assert results_b[0]["run_id"] == "r2"

        # default user sees the result without user_id
        results_default = store.list_results("test-bm", user_id="default")
        assert len(results_default) == 1
        assert results_default[0]["run_id"] == "r3"

        # no filter returns all
        assert len(store.list_results("test-bm")) == 3

    def test_benchmark_record_carries_user_id(self, store):
        store.save_benchmark("my-bm", [{"label": "T"}], user_id="user_x")
        bm = store.load_benchmark("my-bm")
        assert bm["user_id"] == "user_x"

    def test_benchmark_without_user_id_is_default(self, store):
        """Legacy benchmarks without user_id — no user_id key in the record."""
        store.save_benchmark("legacy-bm", [{"label": "T"}])
        bm = store.load_benchmark("legacy-bm")
        assert "user_id" not in bm
        # Visible in unfiltered list
        assert len(store.list_benchmarks()) == 1
        # Visible when filtering for "default" sentinel
        assert len(store.list_benchmarks(user_id="default")) == 1
        # Not visible to arbitrary users
        assert len(store.list_benchmarks(user_id="anyone")) == 0

    def test_delete_benchmark_removes_all_results(self, store):
        store.save_benchmark("del-me", [{"label": "T"}], user_id="user_a")
        store.save_result("del-me", {"run_id": "r1", "status": "completed"})
        assert store.delete_benchmark("del-me")
        assert store.load_benchmark("del-me") is None
