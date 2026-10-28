"""Static product scope, separate from live host capability or authorization."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def module_catalog():
    """Read public release metadata once; never contact AMI or a database."""
    path = Path(__file__).parent / 'themes/qpanel/static/data/module-catalog.json'
    return json.loads(path.read_text(encoding='utf-8'))
