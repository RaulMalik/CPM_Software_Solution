# PPO Development Split - 7 Day Plan

~~## Day 1 (Wed Apr 16) - Foundation~~
- ppo/config.py
- ppo/__init__.py
- ppo/__main__.py
- ppo/storage/models.py
- ppo/storage/database.py
- ppo/storage/__init__.py

~~## Day 2 (Thu Apr 17) - Data Layer~~
- ppo/data/scada_client.py
- ppo/data/ais_client.py
- ppo/data/nordpool_client.py
- ppo/data/cruise_schedule.py
- ppo/data/__init__.py

~~## Day 3 (Fri Apr 18) - Core Logic Part 1~~
- ppo/core/capacity_forecaster.py
- ppo/core/load_shedding.py
- ppo/core/bess_controller.py

## Day 4 (Sat Apr 19) - Core Logic Part 2
- ppo/core/lease_manager.py
- ppo/core/priority_engine.py
- ppo/core/__init__.py

## Day 5 (Sun Apr 20) - Storage & API
- ppo/storage/repositories.py
- ppo/api/main.py
- ppo/api/deps.py
- ppo/api/__init__.py

## Day 6 (Mon Apr 21) - API Routes
- ppo/api/schemas.py
- ppo/api/routes/__init__.py
- ppo/api/routes/dashboard.py
- ppo/api/routes/tenants.py
- ppo/api/routes/leases.py
- ppo/api/routes/bess.py
- ppo/api/routes/capacity.py
- ppo/api/routes/events.py
- ppo/api/routes/system.py

## Day 7 (Tue Apr 22) - Runtime & Testing
- scripts/run_server.py
- scripts/run_simulation.py
- scripts/seed_db.py
- scripts/__init__.py
- ppo/simulation/simulator.py
- ppo/simulation/visualizations.py
- ppo/simulation/__init__.py
- tests/conftest.py
- tests/test_bess_controller.py
- tests/test_capacity_forecaster.py
- tests/test_load_shedding.py
- tests/test_lease_manager.py
- requirements.txt
- README.md