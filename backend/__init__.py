"""NavIC website backend package.

The deployable FastAPI application is exposed by :mod:`backend.python_fastapi.application.main`.
The TCP transport and shared domain implementation remain in the independent
``navic_tcp`` package; this package provides the website-facing application
composition, configuration, database access, services and integrations.
"""
