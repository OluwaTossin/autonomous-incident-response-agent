"""Pure connection-budget and load-result readiness calculations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServicePool:
    service: str
    task_count: int
    pool_size: int
    max_overflow: int

    @property
    def maximum_connections(self) -> int:
        if min(self.task_count, self.pool_size, self.max_overflow) < 0:
            raise ValueError("connection budget values cannot be negative")
        return self.task_count * (self.pool_size + self.max_overflow)


@dataclass(frozen=True, slots=True)
class ConnectionBudget:
    total: int
    safe_limit: int
    headroom: int
    accepted: bool


def evaluate_connection_budget(
    pools: tuple[ServicePool, ...], *, database_max_connections: int, reserve_percent: int = 25
) -> ConnectionBudget:
    if database_max_connections <= 0 or not 1 <= reserve_percent <= 90:
        raise ValueError("invalid database capacity inputs")
    total = sum(pool.maximum_connections for pool in pools)
    safe_limit = database_max_connections * (100 - reserve_percent) // 100
    return ConnectionBudget(total, safe_limit, safe_limit - total, total <= safe_limit)


def percentile(values: list[float], quantile: float) -> float:
    if not values or not 0 <= quantile <= 1:
        raise ValueError("percentile requires values and a quantile from zero to one")
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * quantile + 0.5))
    return ordered[index]
