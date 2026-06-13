"""Local web UI surface for the Premiere Pro Connector (PRD §4 req 9 / §9 Q6).

A thin FastAPI layer over ``engine.pipeline.run_autocut`` — same engine, same output as the
CLI. Localhost only; no LLM, no outbound network. See ``web/app.py``.
"""
