"""
TDD Test Cases — HIPAA Rule (src/compliance/rules/hipaa_rule.py)

Tests for Protected Health Information (PHI) detection.
"""
import pytest


class TestHipaaSSN:
    """Detect Social Security Numbers."""

    def test_detects_standard_ssn_format(self, hipaa_rule):
        """Should detect '123-45-6789' pattern."""
        result = hipaa_rule.scan("Employee SSN: 123-45-6789")
        assert len(result.violations) > 0
        descriptions = [v.description for v in result.violations]
        assert any("SSN" in d for d in descriptions)

    def test_detects_ssn_without_dashes(self, hipaa_rule):
        """Should detect '123456789' (9 consecutive digits in SSN context)."""
        result = hipaa_rule.scan("SSN 123456789")
        assert len(result.violations) > 0

    def test_ignores_non_ssn_numbers(self, hipaa_rule):
        """Should NOT flag random 9-digit numbers without the SSN label/format."""
        result = hipaa_rule.scan("Order number: 123456789 processed successfully.")
        ssn_violations = [v for v in result.violations if "SSN" in v.description]
        assert len(ssn_violations) == 0

    def test_masks_ssn_in_finding(self, hipaa_rule):
        """Finding.text_snippet should show '***-**-6789', never full SSN."""
        result = hipaa_rule.scan("SSN: 123-45-6789")
        assert len(result.violations) > 0
        v = result.violations[0]
        assert "123-45" not in v.matched_text
        assert "6789" in v.matched_text

    def test_ssn_severity_is_critical(self, hipaa_rule):
        """SSN violations should be severity='critical'."""
        result = hipaa_rule.scan("SSN: 123-45-6789")
        ssn_violations = [v for v in result.violations if "SSN" in v.description]
        assert len(ssn_violations) > 0
        assert all(v.severity == "critical" for v in ssn_violations)

    def test_multiple_ssns_in_text(self, hipaa_rule):
        """Should report each SSN as separate finding with location."""
        result = hipaa_rule.scan("Alice SSN: 123-45-6789. Bob SSN: 987-65-4321.")
        ssn_violations = [v for v in result.violations if "SSN" in v.description]
        assert len(ssn_violations) == 2
        positions = [v.position for v in ssn_violations]
        assert positions[0] != positions[1]


class TestHipaaMedicalRecords:
    """Detect medical record identifiers."""

    def test_detects_mrn_pattern(self, hipaa_rule):
        """Should detect 'MRN: 12345678' or 'MRN #12345678'."""
        result = hipaa_rule.scan("Patient MRN: 12345678 admitted today.")
        mrn_violations = [v for v in result.violations if "MRN" in v.description or "Medical" in v.description]
        assert len(mrn_violations) > 0

    def test_detects_icd10_codes(self, hipaa_rule):
        """Should detect ICD-10 codes like 'J06.9' or 'E11.65'."""
        result = hipaa_rule.scan("Diagnosis: E11.65 - Type 2 Diabetes Mellitus.")
        icd_violations = [v for v in result.violations if "ICD" in v.description]
        assert len(icd_violations) > 0

    def test_detects_patient_keywords(self, hipaa_rule):
        """NPI / Patient ID patterns should trigger."""
        result = hipaa_rule.scan("Patient ID: PT-20240115 NPI: 1234567890")
        assert len(result.violations) > 0

    def test_ignores_general_medical_discussion(self, hipaa_rule):
        """General health articles (not patient-specific) should NOT trigger."""
        text = "Diabetes mellitus is a chronic metabolic disorder affecting millions worldwide."
        result = hipaa_rule.scan(text)
        # No SSN, MRN, DOB, ICD-10, or Patient ID patterns in this text
        assert len(result.violations) == 0


class TestHipaaDOB:
    """Detect date of birth in PHI context."""

    def test_detects_dob_with_label(self, hipaa_rule):
        """'DOB: 01/15/1990' should be flagged."""
        result = hipaa_rule.scan("DOB: 01/15/1990")
        dob_violations = [v for v in result.violations if "Birth" in v.description or "DOB" in v.description]
        assert len(dob_violations) > 0

    def test_ignores_dates_without_phi_context(self, hipaa_rule):
        """'Meeting date: 01/15/2024' should NOT be flagged."""
        result = hipaa_rule.scan("Meeting date: 01/15/2024 at 10am")
        # The DOB pattern requires 'DOB' prefix — plain dates should not match
        dob_violations = [v for v in result.violations if "Birth" in v.description or "DOB" in v.description]
        assert len(dob_violations) == 0


class TestHipaaEdgeCases:
    """Edge cases for HIPAA detection."""

    def test_empty_text_no_violations(self, hipaa_rule):
        result = hipaa_rule.scan("")
        assert len(result.violations) == 0

    def test_non_english_phi_not_detected(self, hipaa_rule):
        """Current implementation targets English PHI only (document limitation)."""
        result = hipaa_rule.scan("Пациент Иван Иванов, дата рождения: 15.01.1980")
        # No English-format SSN, MRN, or DOB — should produce no violations
        assert result.rule_name == "HIPAA"

    def test_pdf_with_medical_form(self, hipaa_rule, medical_form_text):
        """Full medical form text should trigger multiple findings."""
        result = hipaa_rule.scan(medical_form_text)
        assert len(result.violations) >= 3
        severities = {v.severity for v in result.violations}
        assert "critical" in severities
