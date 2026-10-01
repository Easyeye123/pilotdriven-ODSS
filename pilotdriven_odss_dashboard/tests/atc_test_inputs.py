"""Lazy external ATC test inputs; standalone images omit the sibling app/PDFs."""
import json
import os
from pathlib import Path

import pytest

from tests.cross_runtime import sibling_app_root


def load_enroute_fixture(name, *, test_file=None):
    key = 'PILOTDRIVEN_APP_ROOT'
    configured = key in os.environ
    if configured and not os.environ[key].strip():
        raise ValueError(f'{key} is configured but empty')
    app = Path(os.environ[key]) if configured else sibling_app_root(
        Path(test_file) if test_file is not None else Path(__file__), 'pd-code-e-helpyou-20260921')
    if app is None or not app.exists():
        if configured:
            raise FileNotFoundError(f'Configured {key} is missing: {app}')
        pytest.skip(f'External app fixture not bundled; {key} is unset')
    # An existing app is selected evidence: missing/invalid members must fail.
    return json.loads((app / 'tests/fixtures/enroute-contact' / f'{name}.json').read_text())


def private_cfp_source(filename, *, test_file=None):
    key = 'PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR'
    configured = key in os.environ
    if configured and not os.environ[key].strip():
        raise ValueError(f'{key} is configured but empty')
    start = Path(test_file) if test_file is not None else Path(__file__)
    corpus = Path(os.environ[key]) if configured else start.resolve().parent.parent.parent / 'private_cfp_corpus'
    if not corpus.exists():
        if configured:
            raise FileNotFoundError(f'Configured {key} is missing: {corpus}')
        pytest.skip(f'Private CFP original not bundled; {key} is unset')
    if not corpus.is_dir():
        raise NotADirectoryError(f'Private CFP corpus is not a directory: {corpus}')
    source = corpus / filename
    if not source.is_file():
        raise FileNotFoundError(f'Required private CFP member is missing: {source}')
    return source
