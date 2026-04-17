"""Agent Router Service — Hermes Enterprise SaaS Platform Control Plane.

Routes user requests to Agent Pods via Redis routing table.
Handles hot/cold pod scheduling, session locks, and cold-start coordination.
"""

__version__ = "0.1.0"
