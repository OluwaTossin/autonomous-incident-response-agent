from __future__ import annotations

import pytest

from app.security.outbound import UnsafeOutboundUrl, validate_public_https_url


@pytest.mark.parametrize(
    "value",
    [
        "http://provider.example",
        "https://localhost/token",
        "https://service.localhost/token",
        "https://127.0.0.1/token",
        "https://[::1]/token",
        "https://[::ffff:127.0.0.1]/token",
        "https://[2001:db8::1]/token",
        "https://10.0.0.8/token",
        "https://172.16.0.8/token",
        "https://192.168.1.8/token",
        "https://169.254.169.254/latest/meta-data/",
        "https://198.51.100.2/token",
        "https://203.0.113.2/token",
        "https://[fd00::1]/token",
        "https://user:secret@provider.example/token",
        "https://provider.example:8443/token",
    ],
)
def test_outbound_policy_rejects_ssrf_destinations(value: str) -> None:
    with pytest.raises(UnsafeOutboundUrl):
        validate_public_https_url(value, setting_name="TEST_URL")


def test_outbound_policy_accepts_public_https_destination() -> None:
    assert (
        validate_public_https_url(
            "https://cognito-idp.eu-west-2.amazonaws.com/pool/",
            setting_name="TEST_URL",
        )
        == "https://cognito-idp.eu-west-2.amazonaws.com/pool"
    )
