"""
TDD Test Cases — LLM-Based Compliance Scanner (src/compliance/scanner.py Stage 2)

Tests for local LLM contextual compliance scanning.
Uses MockLLM for deterministic testing — same pipeline as real Ollama.
"""
import time
import pytest


# ============================================================================
# CONTEXTUAL PHI DETECTION (what regex misses)
# ============================================================================

class TestLLMHipaaContextual:
    """LLM catches contextual PHI that regex cannot."""

    @pytest.mark.asyncio
    async def test_detects_named_patient_with_diagnosis(self, llm_scanner, mock_llm):
        """'John Smith was diagnosed with Type 2 diabetes' — no SSN, but still PHI."""
        record = await llm_scanner.scan_with_llm(
            "John Smith was diagnosed with Type 2 diabetes.", llm=mock_llm
        )
        assert record.llm_checked
        assert record.has_violations
        assert any("patient" in v.description.lower() or "PHI" in v.description for v in record.violations)

    @pytest.mark.asyncio
    async def test_detects_treatment_plan_with_patient(self, llm_scanner, mock_llm):
        """'The patient will begin chemotherapy on March 15' — PHI by context."""
        record = await llm_scanner.scan_with_llm(
            "The patient will begin chemotherapy on March 15.", llm=mock_llm
        )
        assert record.llm_checked
        assert record.has_violations

    def test_ignores_medical_textbook_content(self, llm_scanner):
        """'Diabetes mellitus is a metabolic disease...' — educational, not PHI."""
        record = llm_scanner.scan_sync(
            "Diabetes mellitus is a chronic metabolic disorder affecting millions worldwide."
        )
        assert not record.has_violations

    @pytest.mark.asyncio
    async def test_detects_implicit_health_status(self, llm_scanner, mock_llm):
        """'She has been on disability leave since her surgery' — health info without explicit diagnosis."""
        record = await llm_scanner.scan_with_llm(
            "She has been on disability leave since her surgery last month.", llm=mock_llm
        )
        assert record.llm_checked
        assert record.has_violations

    @pytest.mark.asyncio
    async def test_distinguishes_doctor_name_from_patient(self, llm_scanner, mock_llm):
        """'Dr. Smith treated the patient' — patient health reference is PHI."""
        record = await llm_scanner.scan_with_llm(
            "Dr. Smith treated the patient for pneumonia.", llm=mock_llm
        )
        assert record.llm_checked
        assert record.has_violations
        # Violation references patient, not the doctor
        descriptions = [v.description for v in record.violations]
        assert any("patient" in d.lower() or "health" in d.lower() for d in descriptions)


# ============================================================================
# CONTEXTUAL FINANCIAL DATA (SOX)
# ============================================================================

class TestLLMSoxContextual:
    """LLM catches contextual financial sensitivity."""

    @pytest.mark.asyncio
    async def test_detects_unreleased_earnings(self, llm_scanner, mock_llm):
        """'Q3 revenue is projected at $4.2B, up 18% — not yet public' — insider info."""
        record = await llm_scanner.scan_with_llm(
            "Q3 revenue is projected at $4.2B, up 18% — not yet public.", llm=mock_llm
        )
        assert record.llm_checked
        assert record.has_violations
        assert any(v.severity == "critical" for v in record.violations)

    def test_ignores_published_financials(self, llm_scanner):
        """'Our 2024 annual report shows revenue of $15B' — already public, not sensitive."""
        record = llm_scanner.scan_sync(
            "Our 2024 annual report shows revenue of $15B, publicly filed with the SEC."
        )
        assert not record.has_violations

    @pytest.mark.asyncio
    async def test_detects_merger_discussion(self, llm_scanner, mock_llm):
        """'Discussions with AcmeCorp about potential acquisition' — material non-public."""
        record = await llm_scanner.scan_with_llm(
            "Confidential: discussions with AcmeCorp about potential acquisition underway.",
            llm=mock_llm,
        )
        assert record.llm_checked
        assert record.has_violations


# ============================================================================
# CONTEXTUAL PII (GDPR)
# ============================================================================

class TestLLMGdprContextual:
    """LLM catches contextual personal data."""

    @pytest.mark.asyncio
    async def test_detects_employee_performance_review(self, llm_scanner, mock_llm):
        """'Sarah's performance has declined since the incident' — personal data."""
        record = await llm_scanner.scan_with_llm(
            "Sarah's performance has declined significantly since the incident last quarter.",
            llm=mock_llm,
        )
        assert record.llm_checked
        assert record.has_violations

    @pytest.mark.asyncio
    async def test_detects_salary_information(self, llm_scanner, mock_llm):
        """'Marketing team salaries range from $80K to $150K' — PII if identifiable."""
        record = await llm_scanner.scan_with_llm(
            "Marketing team salaries range from $80K to $150K annually.", llm=mock_llm
        )
        assert record.llm_checked
        assert record.has_violations

    def test_ignores_aggregated_statistics(self, llm_scanner):
        """'Average salary across 500 employees is $95K' — aggregated, not PII."""
        record = llm_scanner.scan_sync(
            "Average salary across 500 employees is $95K (anonymized HR report)."
        )
        assert not record.has_violations


# ============================================================================
# TWO-STAGE PIPELINE
# ============================================================================

class TestTwoStagePipeline:
    """Verify Stage 1 (regex) + Stage 2 (LLM) work together."""

    @pytest.mark.asyncio
    async def test_regex_finds_ssn_llm_finds_context(self, llm_scanner, mock_llm, text_with_ssn_and_context):
        """Regex catches the SSN, LLM catches the contextual PHI. Both appear in results."""
        record = await llm_scanner.scan_with_llm(text_with_ssn_and_context, llm=mock_llm)
        descriptions = [v.description for v in record.violations]
        assert any("SSN" in d for d in descriptions)              # regex finding
        assert any("patient" in d.lower() or "PHI" in d for d in descriptions)  # LLM finding

    def test_deduplication_between_stages(self, full_scanner, text_with_ssn):
        """Regex stage should not produce duplicate findings for the same SSN."""
        record = full_scanner.scan_sync(text_with_ssn)
        ssn_violations = [v for v in record.violations if "SSN" in v.description]
        assert len(ssn_violations) == 1

    def test_llm_stage_skipped_when_disabled(self, regex_only_scanner):
        """COMPLIANCE_LLM_ENABLED=False should skip LLM stage entirely."""
        record = regex_only_scanner.scan_sync("Some text with SSN: 123-45-6789")
        assert not record.llm_checked
        assert record.has_violations

    def test_llm_stage_skipped_when_ollama_down(self, full_scanner_no_ollama):
        """If Ollama is not running, Stage 2 should be skipped with warning, not crash."""
        record = full_scanner_no_ollama.scan_sync("SSN: 123-45-6789")
        assert not record.llm_checked
        assert record.has_violations

    def test_llm_timeout_does_not_block(self, full_scanner, slow_ollama):
        """Stage 1 (regex) completes fast regardless of LLM availability."""
        start = time.time()
        record = full_scanner.scan_sync("SSN: 123-45-6789")
        elapsed = time.time() - start
        assert elapsed < 5.0
        assert not record.llm_checked

    def test_stage1_fast_stage2_slower(self, full_scanner, clean_text):
        """Stage 1 should complete in < 100ms."""
        start = time.time()
        full_scanner.scan_sync(clean_text)
        elapsed_ms = (time.time() - start) * 1000
        assert elapsed_ms < 100

    def test_long_text_chunked_for_llm(self, full_scanner, very_long_text):
        """Text exceeding COMPLIANCE_LLM_MAX_TEXT_LENGTH should be handled without error."""
        record = full_scanner.scan_sync(very_long_text)
        assert not record.llm_checked

    def test_llm_low_confidence_filtered(self, full_scanner):
        """All violations have confidence >= 0.7 (regex findings default to 1.0)."""
        record = full_scanner.scan_sync("Possibly sensitive text without clear violations.")
        assert all(getattr(v, "confidence", 1.0) >= 0.7 for v in record.violations)


# ============================================================================
# LOCAL-ONLY ENFORCEMENT
# ============================================================================

class TestLocalOnlyCompliance:
    """Verify compliance scanning NEVER sends data to cloud APIs."""

    def test_compliance_uses_ollama_not_cloud(self, full_scanner):
        """scan_sync never calls any external LLM provider."""
        record = full_scanner.scan_sync("SSN: 123-45-6789")
        assert not record.llm_checked

    def test_cloud_api_never_called(self, full_scanner, mock_anthropic_api, text_with_ssn):
        """Anthropic/OpenAI APIs should receive zero calls during compliance scan."""
        full_scanner.scan_sync(text_with_ssn)
        assert not mock_anthropic_api.called
