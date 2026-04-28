"""
Start the PPO API server + dashboard.

Usage:
    python -m scripts.run_server
    # → open http://127.0.0.1:8000/dashboard
"""

from __future__ import annotations

import uvicorn

from ppo.config import settings


def main() -> None:
    print("=" * 60)
    print("  Port Power Orchestrator — API server")
    print(f"  http://{settings.api_host}:{settings.api_port}/dashboard")
    print(f"  http://{settings.api_host}:{settings.api_port}/docs")
    print("=" * 60)
    uvicorn.run(
        "ppo.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level="info",
    )


if __name__ == "__main__":
    main()
