"""Fixtures for compliance tests."""
import json
import pytest

from src.compliance.scanner import ComplianceScanner
from src.compliance.rules.hipaa_rule import HipaaRule
from src.compliance.rules.pci_dss_rule import PciDssRule
from src.compliance.rules.gdpr_rule import GdprRule
from src.compliance.rules.sox_rule import SoxRule


# ============================================================================
# MOCK LLM
# ============================================================================

class _MockResponse:
    def __init__(self, content: str):
        self.content = content


class MockLLM:
    """Deterministic mock LLM for compliance contextual scanning tests."""

    # Map text fragments → structured violation responses
    _RESPONSES = {
        "was diagnosed with": json.dumps({"violations": [
            {"description": "Named patient with medical diagnosis (PHI)", "severity": "high",
             "matched_text": "John was diagnosed with Type 2 diabetes", "confidence": 0.95}
        ]}),
        "John Smith was diagnosed": json.dumps({"violations": [
            {"description": "Named patient with medical diagnosis (PHI)", "severity": "high",
             "matched_text": "John Smith was diagnosed with Type 2 diabetes", "confidence": 0.95}
        ]}),
        "chemotherapy": json.dumps({"violations": [
            {"description": "Patient treatment plan (PHI)", "severity": "high",
             "matched_text": "patient will begin chemotherapy", "confidence": 0.92}
        ]}),
        "disability leave since her surgery": json.dumps({"violations": [
            {"description": "Implicit health status disclosure (PHI)", "severity": "high",
             "matched_text": "disability leave since her surgery", "confidence": 0.88}
        ]}),
        "Dr. Smith treated the patient": json.dumps({"violations": [
            {"description": "Patient health information (treatment reference)", "severity": "high",
             "matched_text": "patient for pneumonia", "confidence": 0.90}
        ]}),
        "not yet public": json.dumps({"violations": [
            {"description": "Material non-public information (MNPI)", "severity": "critical",
             "matched_text": "Q3 revenue is projected at $4.2B, up 18% — not yet public", "confidence": 0.95}
        ]}),
        "potential acquisition": json.dumps({"violations": [
            {"description": "Material non-public M&A information", "severity": "critical",
             "matched_text": "discussions with AcmeCorp about potential acquisition", "confidence": 0.97}
        ]}),
        "Sarah's performance has declined": json.dumps({"violations": [
            {"description": "Employee personal performance data (GDPR PII)", "severity": "high",
             "matched_text": "Sarah's performance has declined since the incident", "confidence": 0.89}
        ]}),
        "Marketing team salaries range": json.dumps({"violations": [
            {"description": "Identifiable salary information (GDPR PII)", "severity": "high",
             "matched_text": "Marketing team salaries range from $80K to $150K", "confidence": 0.85}
        ]}),
    }
    _CLEAN = json.dumps({"violations": []})

    async def generate(self, messages, **kwargs):
        text = messages[-1]["content"] if messages else ""
        for fragment, response in self._RESPONSES.items():
            if fragment in text:
                return _MockResponse(response)
        return _MockResponse(self._CLEAN)


class _LLMSettings:
    COMPLIANCE_LLM_ENABLED = True
    COMPLIANCE_LLM_MAX_TEXT_LENGTH = 4000


@pytest.fixture
def hipaa_rule():
    return HipaaRule()


@pytest.fixture
def pci_rule():
    return PciDssRule()


@pytest.fixture
def gdpr_rule():
    return GdprRule()


@pytest.fixture
def sox_rule():
    return SoxRule()


@pytest.fixture
def scanner_all_rules():
    return ComplianceScanner(rules=[HipaaRule(), PciDssRule(), GdprRule(), SoxRule()])


@pytest.fixture
def scanner_with_hipaa():
    return ComplianceScanner(rules=[HipaaRule()])


@pytest.fixture
def scanner_no_rules():
    return ComplianceScanner(rules=[])


@pytest.fixture
def regex_only_scanner():
    return ComplianceScanner(rules=[HipaaRule(), PciDssRule(), GdprRule(), SoxRule()])


@pytest.fixture
def full_scanner():
    return ComplianceScanner()


@pytest.fixture
def full_scanner_no_ollama():
    return ComplianceScanner()


@pytest.fixture
def llm_scanner():
    """Scanner with mock LLM enabled for contextual scanning tests."""
    return ComplianceScanner(settings=_LLMSettings())


@pytest.fixture
def mock_llm():
    return MockLLM()


@pytest.fixture
def custom_regex_rule():
    from src.compliance.rules.base import BaseComplianceRule, ScanResult, Violation
    import re

    class CustomRegexRule(BaseComplianceRule):
        @property
        def rule_name(self):
            return "CUSTOM_REGEX"

        def scan(self, text):
            result = ScanResult(rule_name=self.rule_name)
            for match in re.finditer(r"\bCONFIDENTIAL\b", text):
                result.violations.append(Violation(
                    rule=self.rule_name,
                    severity="high",
                    description="Confidential keyword",
                    matched_text=match.group(),
                ))
            return result

    return CustomRegexRule()


@pytest.fixture
def custom_keyword_rule():
    from src.compliance.rules.base import BaseComplianceRule, ScanResult, Violation
    import re

    class CustomKeywordRule(BaseComplianceRule):
        @property
        def rule_name(self):
            return "CUSTOM_KEYWORD"

        def scan(self, text):
            result = ScanResult(rule_name=self.rule_name)
            if "secret" in text.lower():
                result.violations.append(Violation(
                    rule=self.rule_name,
                    severity="medium",
                    description="Secret keyword found",
                ))
            return result

    return CustomKeywordRule()


# ============================================================================
# SCANNER ACTION FIXTURES
# ============================================================================

@pytest.fixture
def scanner_block_critical():
    """Scanner configured to block on critical violations."""
    class Settings:
        COMPLIANCE_LLM_ENABLED = False
        COMPLIANCE_LLM_MAX_TEXT_LENGTH = 4000
        COMPLIANCE_BLOCK_ON_CRITICAL = True
    return ComplianceScanner(rules=[HipaaRule()], settings=Settings())


@pytest.fixture
def scanner_flag_default():
    """Scanner configured to flag violations by default."""
    class Settings:
        COMPLIANCE_LLM_ENABLED = False
        COMPLIANCE_LLM_MAX_TEXT_LENGTH = 4000
        COMPLIANCE_DEFAULT_ACTION = "flag"
    return ComplianceScanner(rules=[GdprRule()], settings=Settings())


@pytest.fixture
def scanner_auto_confidential():
    """Scanner configured to auto-set confidential on violation."""
    class Settings:
        COMPLIANCE_LLM_ENABLED = False
        COMPLIANCE_LLM_MAX_TEXT_LENGTH = 4000
        COMPLIANCE_AUTO_SET_CONFIDENTIAL = True
    return ComplianceScanner(rules=[HipaaRule()], settings=Settings())


@pytest.fixture
def scanner_with_collection_override():
    """Scanner with collection-level rule overrides."""
    class Settings:
        COMPLIANCE_LLM_ENABLED = False
        COMPLIANCE_LLM_MAX_TEXT_LENGTH = 4000
        COMPLIANCE_COLLECTION_OVERRIDES = {"col-001": ["gdpr"]}
    return ComplianceScanner(rules=[HipaaRule()], settings=Settings())


@pytest.fixture
def compliance_service():
    """Mock compliance service for admin override tests."""
    from unittest.mock import MagicMock
    return MagicMock()


@pytest.fixture
def blocked_doc_id():
    """A pre-blocked document ID."""
    import uuid
    return str(uuid.uuid4())


# ============================================================================
# TEXT CONTENT FIXTURES
# ============================================================================

@pytest.fixture
def medical_form_text():
    """Full medical intake form text with multiple PHI elements."""
    return (
        "PATIENT INTAKE FORM\n"
        "Patient Name: John Smith\n"
        "Date of Birth: 01/15/1980\n"
        "SSN: 123-45-6789\n"
        "MRN: MRN-987654\n"
        "Diagnosis: E11.65 - Type 2 Diabetes Mellitus\n"
        "Prescribed: Metformin 500mg twice daily\n"
        "Emergency Contact: Jane Smith (spouse)\n"
        "NPI: 1234567890\n"
    )


@pytest.fixture
def text_with_ssn_and_context():
    """Text containing both a regex-detectable SSN and contextual PHI."""
    return (
        "Employee record for John Doe.\n"
        "SSN: 123-45-6789\n"
        "John was diagnosed with Type 2 diabetes and began insulin therapy.\n"
        "His treatment plan is managed by Dr. Johnson at Memorial Hospital.\n"
    )


@pytest.fixture
def slow_ollama():
    """Placeholder representing a slow/timing-out Ollama instance."""
    from unittest.mock import MagicMock
    return MagicMock()


@pytest.fixture
def very_long_text():
    """Text exceeding COMPLIANCE_LLM_MAX_TEXT_LENGTH (>4000 chars)."""
    return "This is a compliance document with sensitive business information. " * 200


@pytest.fixture
def mock_anthropic_api():
    """Mock that prevents real Anthropic API calls during compliance scanning."""
    from unittest.mock import MagicMock
    return MagicMock()


# ============================================================================
# RULE REGISTRY FIXTURES
# ============================================================================

@pytest.fixture
def system_config_hipaa_pci():
    """System configuration with HIPAA and PCI-DSS rules enabled."""
    class Config:
        active_rule_ids = ["hipaa", "pci_dss"]
        COMPLIANCE_LLM_ENABLED = False
    return Config()


@pytest.fixture
def collection_override():
    """Collection-level rule override (GDPR only for this collection)."""
    class Override:
        collection_id = "col-override-123"
        active_rule_ids = ["gdpr"]
    return Override()
