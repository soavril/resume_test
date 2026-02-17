"""Tests for SSRF URL validation utility."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from resume_tailor.utils.url_validator import SSRFError, validate_url


class TestValidateUrl:
    """Test URL validation blocks internal/private addresses."""

    def test_blocks_localhost(self):
        with pytest.raises(SSRFError, match="Blocked internal hostname"):
            validate_url("http://localhost/admin")

    def test_blocks_localhost_localdomain(self):
        with pytest.raises(SSRFError, match="Blocked internal hostname"):
            validate_url("http://localhost.localdomain/path")

    def test_blocks_127_0_0_1(self):
        with pytest.raises(SSRFError):
            validate_url("http://127.0.0.1/admin")

    def test_blocks_ipv6_loopback(self):
        with pytest.raises(SSRFError):
            validate_url("http://[::1]/admin")

    def test_blocks_10_network(self):
        with pytest.raises(SSRFError):
            validate_url("http://10.0.0.1/internal")

    def test_blocks_172_16_network(self):
        with pytest.raises(SSRFError):
            validate_url("http://172.16.0.1/internal")

    def test_blocks_192_168_network(self):
        with pytest.raises(SSRFError):
            validate_url("http://192.168.1.1/internal")

    def test_blocks_hostname_resolving_to_private_ip(self):
        """Hostname that DNS-resolves to a private IP should be blocked."""
        fake_result = [(2, 1, 6, "", ("10.0.0.5", 0))]
        with patch("socket.getaddrinfo", return_value=fake_result):
            with pytest.raises(SSRFError, match="resolves to blocked address"):
                validate_url("http://evil.example.com/steal")

    def test_allows_external_url(self):
        """Public IPs should be allowed."""
        fake_result = [(2, 1, 6, "", ("142.250.80.46", 0))]
        with patch("socket.getaddrinfo", return_value=fake_result):
            result = validate_url("https://www.google.com/careers")
            assert result == "https://www.google.com/careers"

    def test_allows_https(self):
        fake_result = [(2, 1, 6, "", ("151.101.1.140", 0))]
        with patch("socket.getaddrinfo", return_value=fake_result):
            result = validate_url("https://example.com/form")
            assert result == "https://example.com/form"

    def test_rejects_ftp_scheme(self):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            validate_url("ftp://example.com/file")

    def test_rejects_file_scheme(self):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            validate_url("file:///etc/passwd")

    def test_rejects_empty_hostname(self):
        with pytest.raises(ValueError, match="No hostname"):
            validate_url("http:///path")

    def test_rejects_unresolvable_hostname(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name resolution failed")):
            with pytest.raises(ValueError, match="Cannot resolve hostname"):
                validate_url("http://this-domain-does-not-exist-xyz123.com/path")
