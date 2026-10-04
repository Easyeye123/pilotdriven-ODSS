"""LABELLED fixture-discovery controls; no source or aviation answers."""
import json
from pathlib import Path

import pytest

from tests.atc_test_inputs import load_enroute_fixture, private_cfp_source

KEY = 'PILOTDRIVEN_APP_ROOT'
NAME = 'LABELLED-SYNTHETIC'
VALUE = {'labelled': 'synthetic fixture-discovery metadata'}


def write_fixture(app, body=None):
    directory = app / 'tests/fixtures/enroute-contact'
    directory.mkdir(parents=True)
    (directory / f'{NAME}.json').write_text(json.dumps(VALUE) if body is None else body)


def sibling_case(tmp_path):
    test_file = tmp_path / 'odss/dashboard/tests/test_x.py'
    return test_file, tmp_path / 'pd-code-e-helpyou-20260921'


@pytest.mark.parametrize('test_file', ['/app/tests/test_x.py', '/tests/test_x.py'])
def test_shallow_unconfigured_external_fixture_skips_only_at_body_time(monkeypatch, test_file):
    monkeypatch.delenv(KEY, raising=False)
    with pytest.raises(pytest.skip.Exception, match='not bundled.*PILOTDRIVEN_APP_ROOT is unset'):
        load_enroute_fixture(NAME, test_file=Path(test_file))


def test_unconfigured_absent_sibling_is_an_explicit_optional_skip(monkeypatch, tmp_path):
    monkeypatch.delenv(KEY, raising=False)
    test_file, _ = sibling_case(tmp_path)
    with pytest.raises(pytest.skip.Exception, match='not bundled'):
        load_enroute_fixture(NAME, test_file=test_file)


def test_default_sibling_and_configured_fixture_both_preserve_actual_values(monkeypatch, tmp_path):
    test_file, sibling = sibling_case(tmp_path)
    write_fixture(sibling)
    monkeypatch.delenv(KEY, raising=False)
    assert load_enroute_fixture(NAME, test_file=test_file) == VALUE
    configured = tmp_path / 'configured-app'
    write_fixture(configured)
    monkeypatch.setenv(KEY, str(configured))
    assert load_enroute_fixture(NAME, test_file=Path('/app/tests/test_x.py')) == VALUE


@pytest.mark.parametrize('value', ['', '   ', 'absent'])
def test_invalid_configured_root_never_falls_back_to_valid_sibling(monkeypatch, tmp_path, value):
    test_file, sibling = sibling_case(tmp_path)
    write_fixture(sibling)
    monkeypatch.setenv(KEY, str(tmp_path / value) if value == 'absent' else value)
    with pytest.raises((ValueError, FileNotFoundError), match='configured but empty|Configured .* is missing'):
        load_enroute_fixture(NAME, test_file=test_file)


@pytest.mark.parametrize('configured', [False, True])
def test_existing_partial_input_never_skips_missing_member(monkeypatch, tmp_path, configured):
    test_file, sibling = sibling_case(tmp_path)
    sibling.mkdir()
    if configured:
        monkeypatch.setenv(KEY, str(sibling))
    else:
        monkeypatch.delenv(KEY, raising=False)
    with pytest.raises(FileNotFoundError):
        load_enroute_fixture(NAME, test_file=test_file)


def test_configured_file_root_and_malformed_json_fail_without_fallback(monkeypatch, tmp_path):
    test_file, sibling = sibling_case(tmp_path)
    write_fixture(sibling)
    invalid = tmp_path / 'not-a-directory'
    invalid.write_text('LABELLED SYNTHETIC invalid path')
    monkeypatch.setenv(KEY, str(invalid))
    with pytest.raises(NotADirectoryError):
        load_enroute_fixture(NAME, test_file=test_file)
    malformed = tmp_path / 'malformed-app'
    write_fixture(malformed, '{ LABELLED SYNTHETIC broken JSON')
    monkeypatch.setenv(KEY, str(malformed))
    with pytest.raises(json.JSONDecodeError):
        load_enroute_fixture(NAME, test_file=test_file)


def test_private_source_unconfigured_absence_and_shallow_path_are_explicit_skips(monkeypatch, tmp_path):
    monkeypatch.delenv('PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR', raising=False)
    for test_file in [Path('/app/tests/test_x.py'), tmp_path / 'odss/dashboard/tests/test_x.py']:
        with pytest.raises(pytest.skip.Exception, match='not bundled.*is unset'):
            private_cfp_source('LABELLED-SYNTHETIC.pdf', test_file=test_file)


def test_private_source_default_and_configured_paths_keep_the_actual_file(monkeypatch, tmp_path):
    key = 'PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR'
    test_file = tmp_path / 'odss/dashboard/tests/test_x.py'
    sibling = tmp_path / 'odss/private_cfp_corpus'
    sibling.mkdir(parents=True)
    (sibling / 'LABELLED-SYNTHETIC.pdf').write_text('LABELLED SYNTHETIC sibling')
    monkeypatch.delenv(key, raising=False)
    assert private_cfp_source('LABELLED-SYNTHETIC.pdf', test_file=test_file).read_text() == 'LABELLED SYNTHETIC sibling'
    configured = tmp_path / 'configured-private-corpus'
    configured.mkdir()
    (configured / 'LABELLED-SYNTHETIC.pdf').write_text('LABELLED SYNTHETIC configured')
    monkeypatch.setenv(key, str(configured))
    assert private_cfp_source('LABELLED-SYNTHETIC.pdf', test_file=test_file).read_text() == 'LABELLED SYNTHETIC configured'


@pytest.mark.parametrize('value', ['', '   ', 'absent'])
def test_private_source_invalid_configured_root_cannot_borrow_valid_sibling(monkeypatch, tmp_path, value):
    test_file = tmp_path / 'odss/dashboard/tests/test_x.py'
    sibling = tmp_path / 'odss/private_cfp_corpus'
    sibling.mkdir(parents=True)
    (sibling / 'LABELLED-SYNTHETIC.pdf').write_text('LABELLED SYNTHETIC sibling')
    monkeypatch.setenv('PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR', str(tmp_path / value) if value == 'absent' else value)
    with pytest.raises((ValueError, FileNotFoundError), match='configured but empty|Configured .* is missing'):
        private_cfp_source('LABELLED-SYNTHETIC.pdf', test_file=test_file)


@pytest.mark.parametrize('configured', [False, True])
def test_private_source_existing_partial_root_must_not_skip(monkeypatch, tmp_path, configured):
    test_file = tmp_path / 'odss/dashboard/tests/test_x.py'
    sibling = tmp_path / 'odss/private_cfp_corpus'
    sibling.mkdir(parents=True)
    key = 'PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR'
    if configured:
        monkeypatch.setenv(key, str(sibling))
    else:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(FileNotFoundError, match='Required private CFP member is missing'):
        private_cfp_source('LABELLED-SYNTHETIC.pdf', test_file=test_file)


def test_private_source_invalid_root_and_damaged_bytes_fail_own_integrity(monkeypatch, tmp_path):
    import hashlib
    key = 'PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR'
    invalid = tmp_path / 'not-a-directory'
    invalid.write_text('LABELLED SYNTHETIC invalid path')
    monkeypatch.setenv(key, str(invalid))
    with pytest.raises(NotADirectoryError):
        private_cfp_source('LABELLED-SYNTHETIC.pdf')
    corpus = tmp_path / 'damaged-corpus'
    corpus.mkdir()
    (corpus / 'LABELLED-SYNTHETIC.pdf').write_bytes(b'LABELLED SYNTHETIC damaged bytes')
    monkeypatch.setenv(key, str(corpus))
    source = private_cfp_source('LABELLED-SYNTHETIC.pdf')
    with pytest.raises(AssertionError):
        assert hashlib.sha256(source.read_bytes()).hexdigest() == hashlib.sha256(b'LABELLED SYNTHETIC original bytes').hexdigest()
