"""
Visualization helpers.

Generates matplotlib charts from forecasts and scenario results. These are
the pitch-ready figures for the Demo Day poster and the proposal report.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from ppo.core.capacity_forecaster import ForecastSummary
from ppo.simulation.simulator import ScenarioResult


# Consistent CMP palette
CMP_DARK = "#1B2A4A"
CMP_BLUE = "#3A7EBF"
CMP_GREEN = "#5FA55A"
CMP_TEAL = "#1ABC9C"
CMP_ORANGE = "#E8863A"
CMP_RED = "#C0392B"
CMP_GRAY = "#95A5A6"
CMP_LIGHT = "#ECF0F1"
BG = "#FAFBFC"


def _style():
    plt.rcParams.update({
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "axes.edgecolor": CMP_DARK,
        "axes.labelcolor": CMP_DARK,
        "text.color": CMP_DARK,
        "xtick.color": CMP_DARK,
        "ytick.color": CMP_DARK,
        "font.family": "sans-serif",
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.color": CMP_GRAY,
    })


def plot_capacity_heatmap(summary: ForecastSummary, out: str | Path) -> Path:
    """Heatmap of leasable capacity over the forecast horizon (by hour of day)."""
    _style()

    # Bucket points by day × hour
    days: dict[datetime, dict[int, float]] = {}
    for p in summary.points:
        day = datetime(p.target_time.year, p.target_time.month, p.target_time.day)
        days.setdefault(day, {})[p.target_time.hour] = p.leasable_mw

    day_keys = sorted(days.keys())
    matrix = np.zeros((len(day_keys), 24))
    for i, d in enumerate(day_keys):
        for h in range(24):
            matrix[i, h] = days[d].get(h, 0.0)

    fig, ax = plt.subplots(figsize=(13, max(2, 0.6 * len(day_keys) + 2)))
    im = ax.imshow(matrix, aspect="auto", cmap="RdYlGn", vmin=0,
                   vmax=max(matrix.max(), 1))
    ax.set_xticks(range(24))
    ax.set_xticklabels([f"{h:02d}" for h in range(24)], fontsize=9)
    ax.set_yticks(range(len(day_keys)))
    ax.set_yticklabels([d.strftime("%a %d %b") for d in day_keys], fontsize=9)
    ax.set_xlabel("Hour of day")
    ax.set_title("PPO capacity forecast — leasable MW by hour")
    for i in range(len(day_keys)):
        for j in range(24):
            v = matrix[i, j]
            color = "white" if v < 6 else CMP_DARK
            ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                    fontsize=7, color=color, fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02).set_label("Leasable MW")
    fig.tight_layout()
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_load_shedding(
    result: ScenarioResult,
    grid_capacity_mw: float,
    out: str | Path,
    title: str | None = None,
) -> Path:
    """Plot the scenario's cruise / tenant / shed stack over time."""
    _style()

    times = [s.timestamp for s in result.states]
    cruise = [s.meter.cruise_load_mw for s in result.states]
    tenant = [s.meter.tenant_load_mw for s in result.states]
    shed = [s.shed_plan.total_shed_mw for s in result.states]

    fig, ax = plt.subplots(figsize=(13, 5.5))

    ax.fill_between(times, 0, cruise, color=CMP_BLUE, alpha=0.7,
                    label="Cruise load")
    ax.fill_between(
        times, cruise,
        [c + t for c, t in zip(cruise, tenant)],
        color=CMP_ORANGE, alpha=0.7, label="Tenant load",
    )
    ax.plot(times, [grid_capacity_mw] * len(times), "--",
            color=CMP_RED, lw=1.5, label=f"Grid capacity ({grid_capacity_mw} MW)")

    # Overlay shed moments
    for s in result.states:
        if not s.shed_plan.is_empty:
            ax.axvline(s.timestamp, color=CMP_GREEN, alpha=0.35, lw=1)

    ax.set_ylabel("Load (MW)")
    ax.set_xlabel("Time")
    ax.set_ylim(0, grid_capacity_mw * 1.15)
    ax.set_title(title or f"Scenario: {result.scenario_name}")
    ax.legend(loc="upper left", fontsize=9)

    # Summary annotation
    ax.text(
        0.98, 0.95,
        f"Total shed: {result.total_shed_mw:.2f} MW\n"
        f"Shed events: {result.shed_events_count}",
        transform=ax.transAxes,
        ha="right", va="top", fontsize=9, family="monospace",
        bbox=dict(boxstyle="round,pad=0.4", fc=CMP_LIGHT, ec=CMP_DARK),
    )

    fig.tight_layout()
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_revenue(
    monthly_revenue_dkk: dict[str, float],
    out: str | Path,
    title: str = "CMP revenue — infrastructure leasing model",
) -> Path:
    """Monthly revenue bar chart."""
    _style()

    months = list(monthly_revenue_dkk.keys())
    values = list(monthly_revenue_dkk.values())

    fig, ax = plt.subplots(figsize=(11, 5))
    bars = ax.bar(months, values, color=CMP_TEAL, edgecolor="white")
    ax.set_ylabel("DKK")
    ax.set_title(title)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.01,
                f"{v:,.0f}", ha="center", va="bottom",
                fontsize=8, fontweight="bold")
    total = sum(values)
    ax.text(0.02, 0.95, f"Annual total: {total:,.0f} DKK",
            transform=ax.transAxes, fontsize=10, va="top",
            bbox=dict(boxstyle="round,pad=0.4",
                      fc=CMP_LIGHT, ec=CMP_DARK))

    fig.tight_layout()
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path
