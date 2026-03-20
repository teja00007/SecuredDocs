"""Compliance scanner — detects sensitive content across multiple regulatory frameworks.

Frameworks covered:
  - HIPAA  : 18 PHI identifiers (health info, patient records, diagnoses)
  - PCI-DSS: Payment card numbers, CVVs, bank account data
  - GDPR   : EU personal data (national IDs, passports, biometrics mentions)
  - PII    : General personally identifiable info (SSN, email+name combos)
  - CUSTOM : Extensible registry for org-specific patterns

Returns a list of violations so the upload endpoint can reject non-compliant docs.
"""

import re
from dataclasses import dataclass, field


@dataclass
class ComplianceViolation:
    category: str       # e.g. "SSN", "CREDIT_CARD", "MRN"
    label: str          # human-readable label
    framework: str      # "HIPAA", "PCI_DSS", "GDPR", "PII", "CUSTOM"
    sample: str         # partially redacted snippet
    count: int = 1


# ---------------------------------------------------------------------------
# Pattern registry — (category, label, framework, compiled_regex)
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, str, str, re.Pattern]] = [

    # ── HIPAA ────────────────────────────────────────────────────────────────
    (
        "SSN",
        "Social Security Number",
        "HIPAA",
        re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    ),
    (
        "MRN",
        "Medical Record Number",
        "HIPAA",
        re.compile(
            r'\b(MRN|Medical\s+Record\s+(Number|No\.?|#))\s*[:\-#]?\s*[\w\-]+',
            re.IGNORECASE,
        ),
    ),
    (
        "DOB",
        "Date of Birth",
        "HIPAA",
        re.compile(
            r'\b(DOB|Date\s+of\s+Birth|Birth\s*[Dd]ate)\s*[:\-]?\s*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}',
            re.IGNORECASE,
        ),
    ),
    (
        "HEALTH_INSURANCE_ID",
        "Health Insurance / Beneficiary ID",
        "HIPAA",
        re.compile(
            r'\b(Health\s+Insurance|Insurance|Medicaid|Medicare|Beneficiary)\s*(ID|Member\s*ID|#)\s*[:\-]?\s*[\w\-]+',
            re.IGNORECASE,
        ),
    ),
    (
        "INSURANCE_CLAIM",
        "Insurance Claim Number",
        "HIPAA",
        re.compile(
            r'\b(Insurance\s+Claim|Claim)\s*(#|No\.?|Number)\s*[:\-]?\s*[\w\-]+',
            re.IGNORECASE,
        ),
    ),
    (
        "ICD_CODE",
        "ICD Diagnosis Code",
        "HIPAA",
        re.compile(
            r'\bICD-\d+\s*[:\-]?\s*[A-Z]\d{2}(\.\d{1,4})?\b',
            re.IGNORECASE,
        ),
    ),
    (
        "HIV_AIDS",
        "HIV/AIDS Status Disclosure",
        "HIPAA",
        re.compile(
            r'\b(HIV|AIDS)\b.{0,60}\b(positive|negative|status|result|diagnosed|diagnosis|test|undetectable|ART|antiretroviral)\b',
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "MENTAL_HEALTH",
        "Mental Health / Substance Use Condition",
        "HIPAA",
        re.compile(
            r'\b(bipolar\s+disorder|schizophrenia|major\s+depressive\s+disorder|PTSD|'
            r'post.traumatic\s+stress|panic\s+disorder|OUD|opioid\s+use\s+disorder|'
            r'substance\s+use\s+disorder|suboxone|methadone\s+treatment)\b',
            re.IGNORECASE,
        ),
    ),
    (
        "PATIENT_RECORD",
        "Patient Record / Medical Chart",
        "HIPAA",
        re.compile(
            r'\b(Patient\s+(Name|ID|Chart|MRN|DOB)|Medical\s+(Record|History|Chart)|'
            r'Treating\s+Physician|Diagnosis\s*[:\-]|Prescription\s*[:\-])\b',
            re.IGNORECASE,
        ),
    ),
    (
        "NPI",
        "National Provider Identifier (NPI)",
        "HIPAA",
        re.compile(r'\bNPI\s*[:\-#]?\s*\d{10}\b', re.IGNORECASE),
    ),
    (
        "BULK_PATIENT_TABLE",
        "Bulk Patient Data Export Table",
        "HIPAA",
        re.compile(
            r'(MRN|Medical\s+Record).{0,200}(Full\s+Name|Patient\s+Name|DOB|Date\s+of\s+Birth).{0,200}(Condition|Diagnosis|Phone)',
            re.IGNORECASE | re.DOTALL,
        ),
    ),

    # ── PCI-DSS ───────────────────────────────────────────────────────────────
    (
        "CREDIT_CARD",
        "Credit / Debit Card Number (PAN)",
        "PCI_DSS",
        re.compile(
            # Visa (4), Mastercard (51-55), Amex (34/37), Discover (6011/65)
            r'\b(?:4[0-9]{12}(?:[0-9]{3})?'
            r'|5[1-5][0-9]{14}'
            r'|3[47][0-9]{13}'
            r'|6(?:011|5[0-9]{2})[0-9]{12})'
            r'(?:[-\s]?[0-9]{4}){0,1}\b',
        ),
    ),
    (
        "CVV",
        "Card Security Code (CVV/CVC)",
        "PCI_DSS",
        re.compile(
            r'\b(CVV|CVC|CVC2|CVV2|CSC|security\s+code)\s*[:\-#]?\s*\d{3,4}\b',
            re.IGNORECASE,
        ),
    ),
    (
        "BANK_ACCOUNT",
        "Bank Account / Routing Number",
        "PCI_DSS",
        re.compile(
            r'\b(bank\s+account|account\s+number|routing\s+number|ABA\s+routing)\s*[:\-#]?\s*\d{8,17}\b',
            re.IGNORECASE,
        ),
    ),
    (
        "IBAN",
        "IBAN (International Bank Account Number)",
        "PCI_DSS",
        re.compile(r'\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b'),
    ),

    # ── GDPR / EU PII ─────────────────────────────────────────────────────────
    (
        "EU_NATIONAL_ID",
        "EU National ID / Passport Number",
        "GDPR",
        re.compile(
            r'\b(national\s+id|passport\s+(number|no\.?)|national\s+insurance\s+number|'
            r'BSN|CNI|NIE|DNI|CPF|CNPJ|NIF|NINO)\s*[:\-#]?\s*[\w\-]{6,15}\b',
            re.IGNORECASE,
        ),
    ),
    (
        "BIOMETRIC",
        "Biometric Data Reference",
        "GDPR",
        re.compile(
            r'\b(fingerprint|facial\s+recognition|retinal\s+scan|iris\s+scan|voice\s+print|biometric\s+(data|identifier|template))\b',
            re.IGNORECASE,
        ),
    ),
    (
        "GDPR_SPECIAL_CATEGORY",
        "GDPR Special Category Data (race/religion/politics)",
        "GDPR",
        re.compile(
            r'\b(racial\s+origin|ethnic\s+origin|political\s+opinion|religious\s+belief|'
            r'trade\s+union\s+membership|genetic\s+data|sexual\s+orientation)\b',
            re.IGNORECASE,
        ),
    ),

    # ── SOX ───────────────────────────────────────────────────────────────────
    (
        "SOX_CONTROL_OVERRIDE",
        "SOX Internal Control Override / Bypass",
        "SOX",
        re.compile(
            r'\b(material\s+weakness|control\s+override|audit\s+committee\s+override|'
            r'segregation\s+of\s+duties|SoD\s+violation|audit\s+log[s]?\s+(disabled|deleted|cleared|missing)|'
            r'dual\s+approval\s+(missing|not\s+obtained)|unauthorized\s+journal\s+entr)',
            re.IGNORECASE,
        ),
    ),
    (
        "SOX_WHISTLEBLOWER",
        "SOX Whistleblower Complaint / Retaliation",
        "SOX",
        re.compile(
            r'\b(whistleblower\s+(complaint|report|retaliation)|SOX\s+§?8(02|06)|'
            r'retaliatory\s+action|whistleblower\s+(protection\s+violation|reprisal))\b',
            re.IGNORECASE,
        ),
    ),
    (
        "SOX_FINANCIAL_IRREGULARITY",
        "SOX Financial Reporting Irregularity",
        "SOX",
        re.compile(
            r'\b(revenue.{0,40}(not\s+disclosed|improperly\s+recognized|without\s+support(?:ing\s+doc)?|'
            r'lacks?\s+dual\s+approval)|'
            r'related\s+party\s+transaction.{0,60}(not\s+disclosed|undisclosed|excluded|'
            r'intentionally\s+excluded|from\s+proxy)|'
            r'SOX\s+(Section\s+|§\s*)?(302|404|806)\s+(violation|non.compliance|breach)|'
            r'journal\s+entr\w+.{0,30}(NONE|missing\s+support|not\s+approved|without\s+approval))\b',
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "SOX_CERTIFICATION",
        "SOX CEO/CFO Certification Missing (§302/906)",
        "SOX",
        re.compile(
            r'\b(CEO|CFO|Chief\s+(Executive|Financial)\s+Officer).{0,120}'
            r'(has\s+NOT\s+signed|not\s+signed\s+off|certification\s+(missing|not\s+obtained)|'
            r'failed\s+to\s+certify)',
            re.IGNORECASE | re.DOTALL,
        ),
    ),

    # ── General PII ───────────────────────────────────────────────────────────
    (
        "SSN_GENERAL",
        "SSN / Tax ID Number",
        "PII",
        re.compile(
            r'\b(SSN|Social\s+Security|Tax\s+ID|TIN|EIN)\s*[:\-#]?\s*\d{3}[-\s]?\d{2}[-\s]?\d{4}\b',
            re.IGNORECASE,
        ),
    ),
    (
        "PASSPORT",
        "Passport Number",
        "PII",
        re.compile(
            r'\b(passport\s+(number|no\.?|#))\s*[:\-]?\s*[A-Z]{1,2}\d{6,9}\b',
            re.IGNORECASE,
        ),
    ),
    (
        "DRIVERS_LICENSE",
        "Driver's License Number",
        "PII",
        re.compile(
            r"\b(driver'?s?\s+licen[sc]e|DL\s+(number|no\.?|#))\s*[:\-]?\s*[A-Z0-9]{5,15}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "EMAIL_WITH_PII",
        "Email Address in Personal Record Context",
        "PII",
        re.compile(
            r'(?i)(name|patient|employee|customer|user|contact).{0,100}[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
            re.DOTALL,
        ),
    ),
    (
        "ADDRESS_WITH_PII",
        "Physical Address in Personal Record Context",
        "PII",
        re.compile(
            r'(?i)(address|home|residence|street).{0,10}\d{1,5}\s+[\w\s]+(?:street|st|avenue|ave|blvd|boulevard|road|rd|lane|ln|drive|dr|court|ct)\b',
            re.IGNORECASE,
        ),
    ),
]


# ---------------------------------------------------------------------------
# Custom rule registry (org-specific patterns)
# ---------------------------------------------------------------------------

_CUSTOM_PATTERNS: list[tuple[str, str, str, re.Pattern]] = []


def register_custom_rule(category: str, label: str, pattern: str | re.Pattern) -> None:
    """Register an org-specific compliance rule at runtime.

    Example::
        from src.core.phi_scanner import register_custom_rule
        register_custom_rule("EMPLOYEE_ID", "Internal Employee ID", r"\\bEMP-\\d{6}\\b")
    """
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
    _CUSTOM_PATTERNS.append((category, label, "CUSTOM", compiled))


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

_REDACTED_NEAR = re.compile(
    r'\[(?:REDACTED|REMOVED|ANONYMIZED|WITHHELD|N/?A)\]',
    re.IGNORECASE,
)


def _is_redacted_field(text: str, m: re.Match) -> bool:
    """True if the matched field label is on a line whose value is a [REDACTED] placeholder."""
    end = m.end()
    newline = text.find('\n', end)
    line_tail = text[end: newline if newline != -1 else end + 80]
    return bool(_REDACTED_NEAR.search(line_tail))


def _redact(match_text: str, max_len: int = 60) -> str:
    text = match_text.strip()
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return re.sub(r'\d', '*', text)


def scan(text: str) -> list[ComplianceViolation]:
    """Scan *text* for compliance violations across all frameworks.

    Returns a (possibly empty) list of ComplianceViolation objects.
    An empty list means the document passed all checks.
    """
    violations: dict[str, ComplianceViolation] = {}

    for category, label, framework, pattern in (_PATTERNS + _CUSTOM_PATTERNS):
        matches = [
            m for m in pattern.finditer(text)
            if not _is_redacted_field(text, m)
        ]
        if matches:
            sample = _redact(matches[0].group(0))
            if category in violations:
                violations[category].count += len(matches)
            else:
                violations[category] = ComplianceViolation(
                    category=category,
                    label=label,
                    framework=framework,
                    sample=sample,
                    count=len(matches),
                )

    return list(violations.values())


def extract_text_for_scan(file_bytes: bytes, file_type: str) -> str:
    """Best-effort text extraction from raw bytes for compliance scanning."""
    _TEXT_TYPES = {".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm"}

    if file_type.lower() in _TEXT_TYPES:
        try:
            return file_bytes.decode("utf-8", errors="replace")
        except Exception:
            return ""

    import tempfile, os
    suffix = file_type.lower()
    try:
        from src.ingestion.parser_factory import get_parser
        parser = get_parser(suffix)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            result = parser.parse(tmp_path)
            return result.text or ""
        finally:
            os.unlink(tmp_path)
    except Exception:
        return ""
