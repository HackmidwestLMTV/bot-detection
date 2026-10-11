"""Five-second collection and synthetic traces; all evidence stays disposable."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from contracts.presentation import DURATION_MS, PRESENTATION_VERSION
from engine.calibrate import load_traces
from engine import calibrate
from engine.devserver import create_app
from engine.features_v2 import representation
from engine.forger import forge_trail
from engine.ml.attacks import FAMILIES, samples
from engine.path import DEFAULT_PATH_VERSION


def test_recorder_and_red_share_a_full_five_second_challenge(tmp_path):
    with TestClient(create_app(traces_dir=tmp_path)) as client:
        ch = client.post('/dev/challenges').json()
        assert ch['duration_ms'] == DURATION_MS == 5000
        assert ch['presentation_version'] == PRESENTATION_VERSION == 'plain_ring_5s_v2'
        trace = forge_trail(ch['seed'], path_version=ch['path_version'], duration_ms=ch['duration_ms'])
        assert len(trace) == 301 and trace[0][0] == 0 and trace[-1][0] == 5000
        np.testing.assert_allclose(np.diff(np.array(trace)[:, 0]), 1000 / 60)
        body = dict(challenge_id=ch['challenge_id'], presentation_version=ch['presentation_version'],
                    samples=trace, device='mouse', pointer_type='mouse')
        assert client.post('/dev/attempts', json=body).status_code == 200
        ch = client.post('/dev/challenges').json()
        body.update(challenge_id=ch['challenge_id'], samples=[[0, 100, 100], [5001, 150, 150]])
        assert client.post('/dev/attempts', json=body).status_code == 400
    assert not list(tmp_path.iterdir()), 'scoring alone must not save a raw recording'


@pytest.mark.parametrize('family', FAMILIES)
def test_shadow_inputs_cover_five_seconds_and_keep_sixty_hz_representation(family):
    trace = samples(42, family)
    assert trace[0][0] == 0 and trace[-1][0] == 5000
    rep = representation(trace, 42)
    assert rep['sequence'].shape == (301, 8)
    assert rep['quality']['eligible'] is True
    assert rep['features']['span_ms'] == 5000
    short = [row for row in trace if row[0] <= 3000]
    assert representation(short, 42)['quality']['eligible'] is False


def test_old_three_second_plain_ring_recordings_remain_auditable_but_excluded(tmp_path):
    base = dict(seed=42, path_version=DEFAULT_PATH_VERSION, device='mouse', cohort='human_test',
                round_id=None, tester={'consent': True})
    old = {**base, 'presentation_version': 'plain_ring_v1',
           'samples': forge_trail(42, path_version=DEFAULT_PATH_VERSION, duration_ms=3000)}
    current = {**base, 'presentation_version': PRESENTATION_VERSION,
               'samples': forge_trail(42, path_version=DEFAULT_PATH_VERSION)}
    for name, trace in [('old.json', old), ('current.json', current)]:
        (tmp_path / name).write_text(json.dumps(trace))
    rows, rejected = load_traces(tmp_path, DEFAULT_PATH_VERSION)
    assert not rejected and [row['file'] for row in rows] == ['current.json']
    rows, rejected = load_traces(tmp_path, DEFAULT_PATH_VERSION, 'plain_ring_v1')
    assert not rejected and [row['file'] for row in rows] == ['old.json']


def test_historical_audit_compares_attacks_with_the_same_recorded_duration(tmp_path, monkeypatch):
    from pathlib import Path
    baseline = json.loads((Path(__file__).parents[2] / 'contracts/fixtures/variant_v1.json').read_text())
    historical = dict(seed=42, path_version='smooth_v2', presentation_version='plain_ring_v1',
                      device='mouse', cohort='human_test', round_id=None, tester={'consent': True},
                      samples=forge_trail(42, path_version='smooth_v2', duration_ms=3000))
    (tmp_path / 'historical.json').write_text(json.dumps(historical))
    durations = []
    def observed(*args, **kwargs):
        trace = forge_trail(*args, **kwargs)
        durations.append(trace[-1][0])
        return trace
    monkeypatch.setattr(calibrate, 'forge_trail', observed)
    report = calibrate.calibration_report(tmp_path, baseline, path_version='smooth_v2', presentation_version='plain_ring_v1')
    assert report['recordings'] == 1 and report['naive_forgeries']['total'] == 1
    assert durations == [3000]
