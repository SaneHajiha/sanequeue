from sanequeue.reporting.preview_policy import builder_preview_request
from sanequeue.reporting.preview_policy import diagnostics_preview_request


def test_preview_allows_only_specific_builder_routes_not_call_control_or_prefixes():
    for path in ('/api/history/builder/preview', '/api/history/builder/export.csv',
                 '/api/history/builder/templates', '/api/history/builder/templates/'+'a'*32):
        assert builder_preview_request(path)
    for path in ('/api/control', '/api/members/pause', '/api/ami/connect',
                 '/api/history/builder/execute', '/api/history/builder/export.csv/extra',
                 '/api/history/builder/templates/../../control',
                 '/api/history/builder/templates/'+'a'*33):
        assert not builder_preview_request(path)


def test_preview_incident_workflow_exception_never_allows_collection_or_pbx_control():
    assert diagnostics_preview_request('/api/diagnostics/incidents')
    for size in (32,64):assert diagnostics_preview_request('/api/diagnostics/incidents/'+'a'*size)
    for path in ('/api/diagnostics/capture/start','/api/diagnostics/commands',
                 '/api/diagnostics/incidents/'+('a'*33),'/api/diagnostics/incidents/'+('a'*32)+'/capture',
                 '/api/control','/api/ami/connect'):
        assert not diagnostics_preview_request(path)
