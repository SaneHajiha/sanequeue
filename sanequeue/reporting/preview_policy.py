"""Narrow report-only POST exception for the isolated reporting preview."""
import re


def builder_preview_request(path):
    """Routes still enforce login, CSRF, scope and their own resource limits."""
    return path in {
        '/api/history/builder/preview',
        '/api/history/builder/export.csv',
        '/api/history/builder/templates',
    } or re.fullmatch(r'/api/history/builder/templates/[0-9a-f]{32}', path) is not None


def diagnostics_preview_request(path):
    """Only private incident storage/workflow; no collection/control routes."""
    return path == '/api/diagnostics/incidents' or re.fullmatch(
        r'/api/diagnostics/incidents/(?:[0-9a-f]{32}|[0-9a-f]{64})', path) is not None
