"""Routers package — API route modules."""

# Routes are mounted directly in main.py to keep structure simple.
# For larger services, split into:
#   routers/
#     __init__.py
#     internal.py   — /internal/*
#     proxy.py      — /v1/*
#     admin.py      — /admin/*
