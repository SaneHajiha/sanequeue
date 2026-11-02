"""Product metadata must remain distinct from installed/accepted capabilities."""
import re
from pathlib import Path
from qpanel.product_catalog import module_catalog


def test_catalog_has_all_documented_modules_and_truthful_boundaries():
    catalog = module_catalog()
    ids = [row['id'] for row in catalog['modules']]
    assert len(ids) == len(set(ids)) == 37
    assert {state: sum(m['implementation'] == state for m in catalog['modules']) for state in ('built','partial','planned')} == {'built':9,'partial':15,'planned':13}
    source = (Path(__file__).parents[1] / 'docs/MODULE_CATALOG.fa.md').read_text(encoding='utf-8')
    documented = re.findall(r'^\| `([a-z_]+)` \|', source, re.M)
    assert set(documented) == set(ids)
    for row in catalog['modules']:
        assert row['state'] in ('beta', 'planned')
        assert row['group'] in {g['id'] for g in catalog['groups']}
        assert row['acceptance']['fa'] and row['acceptance']['en']
        assert row['features']
        for feature in row['features']:
            assert feature['fa'] and feature['en']
            assert feature['state'] in ('beta', 'planned')


def test_distinct_callback_and_ai_products_are_not_advertised_as_complete():
    items = {m['id']: m for m in module_catalog()['modules']}
    assert items['extension_callback']['state'] == 'beta'
    assert items['queue_callback']['state'] == 'planned'
    assert items['ai_transcription']['state'] == 'beta'
    assert items['ai_voice_assistant']['state'] == 'planned'
    assert any(f['state'] == 'planned' for f in items['customer_surveys']['features'])
    assert any(f['state'] == 'planned' for f in items['exports_builder']['features'])
