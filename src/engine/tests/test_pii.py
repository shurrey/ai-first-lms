"""Tests for the PII filter guardrail."""

from __future__ import annotations

import pytest

from engine.guardrails.pii import REDACTION, scan_and_redact


def test_redacts_ssn():
    result = scan_and_redact("SSN is 123-45-6789")
    assert REDACTION in result.text
    assert "123-45-6789" not in result.text
    assert result.had_pii
    assert result.detections[0].pii_type == "ssn"


def test_redacts_email():
    result = scan_and_redact("Contact student@example.com for details")
    assert REDACTION in result.text
    assert "student@example.com" not in result.text
    assert result.detections[0].pii_type == "email"


def test_redacts_phone():
    result = scan_and_redact("Call (555) 123-4567 for help")
    assert REDACTION in result.text
    assert "(555) 123-4567" not in result.text


def test_redacts_credit_card():
    result = scan_and_redact("Card: 4111-1111-1111-1111")
    assert REDACTION in result.text
    assert "4111" not in result.text


def test_no_pii_passes_through():
    text = "Recursion is when a function calls itself."
    result = scan_and_redact(text)
    assert result.text == text
    assert result.had_pii is False
    assert len(result.detections) == 0


def test_multiple_pii_in_same_text():
    text = "Email: test@test.com, SSN: 999-88-7777"
    result = scan_and_redact(text)
    assert result.had_pii
    assert len(result.detections) == 2
    assert "test@test.com" not in result.text
    assert "999-88-7777" not in result.text


def test_allowed_fields_bypass_redaction():
    text = "Send to student@school.edu"
    result = scan_and_redact(text, allowed_fields=["email"])
    assert result.text == text
    assert result.had_pii is False


def test_allowed_fields_only_bypass_specified():
    text = "Email: a@b.com, SSN: 123-45-6789"
    result = scan_and_redact(text, allowed_fields=["email"])
    assert "a@b.com" in result.text  # email allowed
    assert "123-45-6789" not in result.text  # SSN still redacted
    assert result.had_pii


def test_detection_includes_original():
    result = scan_and_redact("SSN: 111-22-3333")
    assert result.detections[0].original == "111-22-3333"


def test_redaction_placeholder():
    result = scan_and_redact("SSN: 111-22-3333")
    assert f"SSN: {REDACTION}" == result.text


def test_uuid_digits_are_not_redacted():
    text = "course 12345678-1234-1234-1234-123456789012 card 4111 1111 1111 1111"
    result = scan_and_redact(text)
    assert result.text == "course 12345678-1234-1234-1234-123456789012 card [REDACTED]"
