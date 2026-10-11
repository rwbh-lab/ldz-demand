"""
Chart functions (Plotly) and the shared theme.

Charts are plain functions returning plotly Figures, styled by the active theme in charts.style.
They know nothing about the dashboard framework, so the same figures work in Marimo pages, scripts
or static exports.
"""
