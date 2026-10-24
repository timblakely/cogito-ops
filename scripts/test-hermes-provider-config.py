#!/usr/bin/env python3
"""Regression check: startup/restore cannot recreate a pinned or dual catalogue."""
from pathlib import Path
import tempfile
import yaml

source = Path(__file__).resolve().parents[1] / 'kubernetes/apps/llm/hermes/app/configure.py'
with tempfile.TemporaryDirectory() as directory:
    home = Path(directory)
    config_path = home / 'config.yaml'
    config_path.write_text(yaml.safe_dump({
        'providers': {
            'litellm-chat': {'discover_models': False, 'models': {'retired': {}}},
            'litellm-responses': {'models': {'retired': {}}},
            'user-endpoint': {'api': 'https://example.invalid/v1'},
        },
        'model': {'context_length': 262144},
        'user-setting': {'preserve': True},
    }))
    code = compile(source.read_text().replace('/opt/data', directory).replace('Path("/bundle")', f'Path({str(home / "missing-bundle")!r})'), str(source), 'exec')
    exec(code, {'__name__': '__main__'})
    first = config_path.read_text()
    config = yaml.safe_load(first)
    providers = config['providers']
    assert 'litellm-responses' not in providers
    assert providers['litellm-chat']['discover_models'] is True
    assert 'models' not in providers['litellm-chat']
    assert providers['litellm-chat']['transport'] == 'chat_completions'
    assert 'context_length' not in config['model']
    assert providers['user-endpoint'] == {'api': 'https://example.invalid/v1'}
    assert config['user-setting'] == {'preserve': True}
    exec(code, {'__name__': '__main__'})
    assert config_path.read_text() == first, 'Reconciliation must be idempotent'
print('PASS: migration, dynamic discovery, user settings, idempotent restart')
