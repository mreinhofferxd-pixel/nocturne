"""Tests for the §9 pre-task budget PROJECTION (orchestrator.avg_task_cost +
projected_over_budget pure helpers).

The post-hoc over_budget cap only halts AFTER spend has already breached the cap.
The projection refines it: at each task boundary the harness estimates the next
task's cost from the running average and halts BEFORE starting a task whose
projected end-cost would exceed the cap. These pin both helpers -- the average's
zero-guard, and the projection's under / at / over cases plus the disabled
(None / 0 / negative) cap that keeps the guard opt-in.
"""
import orchestrator as o


# ---------------------------------------------------------------- avg_task_cost
def test_avg_zero_guard_no_tasks_done():
    # No completed task yet -> no division, mean is 0.0 (not a ZeroDivisionError).
    assert o.avg_task_cost(0.0, 0) == 0.0


def test_avg_zero_guard_negative_count():
    assert o.avg_task_cost(9.0, -1) == 0.0


def test_avg_normal_average():
    assert o.avg_task_cost(6.0, 3) == 2.0


def test_avg_single_task():
    assert o.avg_task_cost(1.5, 1) == 1.5


# ---------------------------------------------------------------- projection: active cap
def test_projected_under_cap_is_false():
    # 3.0 spent + ~1.0/task = 4.0 projected, under the 5.0 cap.
    assert o.projected_over_budget(3.0, 1.0, 5.0) is False


def test_projected_at_cap_is_false():
    # Projected end-cost lands EXACTLY on the cap -> not over (strict >), so start it.
    assert o.projected_over_budget(4.0, 1.0, 5.0) is False


def test_projected_over_cap_is_true():
    # 4.5 spent + ~1.0/task = 5.5 projected > 5.0 cap -> halt before starting.
    assert o.projected_over_budget(4.5, 1.0, 5.0) is True


def test_projected_zero_avg_reduces_to_spend():
    # First-task case: avg is 0, so projection == over_budget's strict form.
    assert o.projected_over_budget(4.0, 0.0, 5.0) is False
    assert o.projected_over_budget(5.5, 0.0, 5.0) is True


# ---------------------------------------------------------------- projection: disabled cap
def test_projected_none_cap_disables_guard():
    assert o.projected_over_budget(1000.0, 50.0, None) is False


def test_projected_zero_cap_disables_guard():
    assert o.projected_over_budget(1000.0, 50.0, 0) is False


def test_projected_negative_cap_disables_guard():
    assert o.projected_over_budget(1000.0, 50.0, -1) is False
