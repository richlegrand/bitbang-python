"""The device challenge (bitbang-docs/device-origins.md, "The device
challenge"): an offer carries 16 random bytes, and the payload that names
them -- with the fingerprint as its 32 bytes, so it fits RSA-2048 OAEP -- is
good for that connection only. These drive _check_binding, which
handle_answer calls after the access code has been checked.
"""

import base64
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bitbang.adapter import CHALLENGE_LEN, VerifyError, _check_binding  # noqa: E402

FP = ':'.join(['AB'] * 32)
ISSUED = bytes([7]) * CHALLENGE_LEN


def b64(b):
    return base64.b64encode(b).decode('ascii')


def challenge_payload(**over):
    p = {
        'fp': b64(bytes([0xAB]) * 32),
        'nonce': b64(b'0123456789abcdef'),
        'code': 'ABCDEFGHIJK',
        'challenge': b64(ISSUED),
    }
    p.update(over)
    return p


def test_challenge_form_accepted():
    assert _check_binding(challenge_payload(), FP, ISSUED) is True


def test_payload_fits_the_key():
    # As browsers write it: JSON.stringify, no spaces.
    size = len(json.dumps(challenge_payload(), separators=(',', ':')))
    assert size <= 190, size


def test_older_form_accepted_as_replayable():
    p = {'fingerprint': FP.lower(), 'nonce': b64(b'x' * 16), 'code': 'ABCDEFGHIJK'}
    assert _check_binding(p, FP, ISSUED) is False


@pytest.mark.parametrize('payload, issued', [
    (challenge_payload(challenge=b64(bytes([8]) * CHALLENGE_LEN)), ISSUED),   # another challenge
    (challenge_payload(challenge='!!'), ISSUED),                              # not base64
    (challenge_payload(fp=b64(bytes([1]) * 32)), ISSUED),                     # another fingerprint
    (challenge_payload(fp=b64(b'\x01\x02')), ISSUED),                         # short fingerprint
    ({k: v for k, v in challenge_payload().items() if k != 'challenge'}, ISSUED),  # fp, no challenge
    ({k: v for k, v in challenge_payload(fingerprint=FP).items() if k != 'fp'}, ISSUED),  # mixed
    (challenge_payload(fingerprint=FP), ISSUED),                              # both fingerprints
    (challenge_payload(), None),                                              # none issued
    ({'fingerprint': ':'.join(['CD'] * 32), 'nonce': 'eA=='}, ISSUED),       # old, wrong fp
    ({'nonce': 'eA=='}, ISSUED),                                              # no fingerprint at all
])
def test_rejected(payload, issued):
    with pytest.raises(VerifyError):
        _check_binding(payload, FP, issued)


def test_no_fingerprint_in_sdp():
    with pytest.raises(VerifyError):
        _check_binding(challenge_payload(), '', ISSUED)
