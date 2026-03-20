"""Seed script for Company Two (HealthFlow Systems) — Nexus Enterprise RAG.

Run phases incrementally:
  python scripts/seed_company_two.py             # Full seed
  python scripts/seed_company_two.py --skip-embeddings  # Skip RAG ingestion
  python scripts/seed_company_two.py --reset     # Wipe HealthFlow data and re-seed

Prerequisites:
  - Backend started at least once (tables must exist)
  - seed_company_one.py NOT required — this script is self-contained
"""

import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from src.config import get_settings
from src.core.security import hash_password
from src.db.session import get_async_engine, get_session_factory
from src.models.user import Permission, Role, User, role_permissions
from src.models.team import Team, TeamMembership
from src.models.document import Collection, Document, DocumentTeamAccess, VisibilityEnum, DocumentStatusEnum
from src.models.chat import Channel, ChannelMember, ChatMessage
from src.models.calendar import CalendarEvent, EventAttendee
from src.models.conversation import Conversation, ConversationMessage
from src.models.company import Company


# ── Company config ─────────────────────────────────────────────────────────────

COMPANY = {
    "name": "HealthFlow Systems",
    "slug": "healthflow",
    "domain": "healthflow.care",
    "admin_password": "HealthAdmin2024!",
    "user_password": "HealthUser2024!",
    "sentinel_username": "dr.emily.chen",   # idempotency check
}

# ── 30 users: (username, title, department, role) ─────────────────────────────

USERS = [
    # ── 2 admins ──────────────────────────────────────────────────────────────
    ("dr.emily.chen",      "Chief Medical Officer",        "Clinical",         "admin"),
    ("james.wright",       "VP Engineering",               "Engineering",      "admin"),

    # ── 15 analysts ───────────────────────────────────────────────────────────
    ("sarah.nguyen",       "Clinical Data Scientist",      "Analytics",        "analyst"),
    ("raj.kumar",          "Sr Backend Engineer",          "Engineering",      "analyst"),
    ("priya.sharma",       "Clinical Systems Analyst",     "Clinical",         "analyst"),
    ("tom.bradley",        "Product Manager",              "Product",          "analyst"),
    ("diana.okafor",       "Sr Data Engineer",             "Analytics",        "analyst"),
    ("kevin.walsh",        "HIPAA Compliance Officer",     "Compliance",       "analyst"),
    ("lisa.chen",          "Clinical Integration Lead",    "Engineering",      "analyst"),
    ("marcus.hayes",       "ML Engineer",                  "Analytics",        "analyst"),
    ("nina.patel",         "Product Manager — Patient UX", "Product",          "analyst"),
    ("alex.torres",        "DevOps Engineer",              "Engineering",      "analyst"),
    ("rachel.kim",         "Regulatory Affairs Manager",   "Compliance",       "analyst"),
    ("david.brooks",       "Sr Frontend Engineer",         "Engineering",      "analyst"),
    ("helen.ross",         "Clinical Data Analyst",        "Analytics",        "analyst"),
    ("omar.farid",         "Hospital Success Manager",     "Customer Success", "analyst"),
    ("jessica.lane",       "Security Engineer",            "Engineering",      "analyst"),

    # ── 13 viewers ────────────────────────────────────────────────────────────
    ("nurse.amy.park",     "RN — Cardiology",              "Clinical",         "viewer"),
    ("nurse.carlos.vega",  "RN — ICU",                     "Clinical",         "viewer"),
    ("nurse.linda.zhou",   "RN — Oncology",                "Clinical",         "viewer"),
    ("coord.ben.foster",   "Patient Care Coordinator",     "Clinical",         "viewer"),
    ("coord.mia.santos",   "Clinical Coordinator",         "Clinical",         "viewer"),
    ("coord.jack.wu",      "Operations Coordinator",       "Operations",       "viewer"),
    ("support.grace.lee",  "Customer Support Specialist",  "Customer Success", "viewer"),
    ("support.ryan.cole",  "Hospital Onboarding Specialist","Customer Success","viewer"),
    ("support.anna.beck",  "Technical Support Engineer",   "Engineering",      "viewer"),
    ("comp.dan.osei",      "Compliance Analyst",           "Compliance",       "viewer"),
    ("comp.sara.malik",    "Privacy Analyst",              "Compliance",       "viewer"),
    ("ops.mike.ford",      "IT Operations",                "Operations",       "viewer"),
    ("ops.tina.scott",     "Data Operations Analyst",      "Operations",       "viewer"),
]

# ── Permissions (resource:action) per role ────────────────────────────────────

ALL_PERMISSIONS = [
    # resource,       action,    description
    ("collection",  "read",     "View collections"),
    ("collection",  "write",    "Create and update collections"),
    ("collection",  "delete",   "Delete collections"),
    ("document",    "read",     "View documents"),
    ("document",    "write",    "Upload and update documents"),
    ("document",    "delete",   "Delete documents"),
    ("query",       "execute",  "Run RAG queries"),
    ("user",        "manage",   "Manage users and roles"),
    ("dl",          "manage",   "Manage distribution lists / teams"),
    ("compliance",  "manage",   "Manage compliance rules"),
]

ROLE_PERMISSION_MAP = {
    "admin":   {f"{r}:{a}" for r, a, _ in ALL_PERMISSIONS},  # all 10
    "analyst": {
        "collection:read", "collection:write",
        "document:read", "document:write",
        "query:execute", "dl:manage",
    },
    "viewer": {
        "collection:read",
        "document:read",
        "query:execute",
    },
}


# ── Teams: name, description, creator, members ────────────────────────────────

TEAMS = [
    {
        "name": "Clinical Engineering",
        "description": "Builds and maintains clinical-facing features including EHR integrations, HL7/FHIR APIs, and patient data pipelines. Partners closely with the Clinical team to validate workflows.",
        "created_by": "james.wright",
        "members": [
            "james.wright", "raj.kumar", "lisa.chen", "david.brooks",
            "alex.torres", "jessica.lane", "support.anna.beck",
        ],
    },
    {
        "name": "Data & Analytics",
        "description": "Owns clinical data warehousing, anonymization pipelines, ML model development, and reporting dashboards for hospital partners.",
        "created_by": "sarah.nguyen",
        "members": [
            "sarah.nguyen", "diana.okafor", "marcus.hayes", "helen.ross",
            "ops.tina.scott", "dr.emily.chen",
        ],
    },
    {
        "name": "Product — Patient Experience",
        "description": "Drives the patient-facing product roadmap including scheduling, messaging, and care plan features. Works cross-functionally with Clinical and Engineering.",
        "created_by": "tom.bradley",
        "members": [
            "tom.bradley", "nina.patel", "priya.sharma",
            "coord.ben.foster", "coord.mia.santos",
        ],
    },
    {
        "name": "Compliance & Regulatory",
        "description": "Ensures HIPAA compliance, manages FDA 510(k) submissions, oversees BAA processes, and conducts PHI audits. Works with all teams to maintain regulatory readiness.",
        "created_by": "kevin.walsh",
        "members": [
            "kevin.walsh", "rachel.kim", "comp.dan.osei", "comp.sara.malik",
            "dr.emily.chen", "jessica.lane",
        ],
    },
    {
        "name": "Customer Success — Hospitals",
        "description": "Manages hospital and health system customer relationships, onboarding, training, and expansion. Acts as the voice of the customer internally.",
        "created_by": "omar.farid",
        "members": [
            "omar.farid", "support.grace.lee", "support.ryan.cole",
            "coord.jack.wu", "ops.mike.ford",
        ],
    },
]


# ── Collections: name, description, owner, is_public ─────────────────────────

COLLECTIONS = [
    {
        "name": "Clinical Documentation",
        "description": "HIPAA policies, PHI handling procedures, clinical API references, and EHR integration guides for clinical and engineering staff.",
        "owner": "dr.emily.chen",
        "is_public": False,
    },
    {
        "name": "Engineering & Tech",
        "description": "Architecture references, onboarding guides, incident playbooks, security assessments, and on-call rotation docs for the engineering team.",
        "owner": "james.wright",
        "is_public": False,
    },
    {
        "name": "Compliance & HIPAA",
        "description": "HIPAA compliance policy, PHI audit procedures, FDA 510(k) preparation, BAA templates, and data anonymization standards.",
        "owner": "kevin.walsh",
        "is_public": False,
    },
]


# ── Documents: 15 docs across 3 collections ───────────────────────────────────

DOCUMENTS = [
    # ── Clinical Documentation (5) ───────────────────────────────────────────
    {"filename": "HIPAA_Compliance_Policy.md",       "collection": "Clinical Documentation",  "owner": "kevin.walsh",    "visibility": "public",       "status": "ready",   "team_access": []},
    {"filename": "Patient_Data_Handling_Guide.md",   "collection": "Clinical Documentation",  "owner": "dr.emily.chen",  "visibility": "public",       "status": "ready",   "team_access": []},
    {"filename": "Clinical_API_Documentation.md",    "collection": "Clinical Documentation",  "owner": "lisa.chen",      "visibility": "team",         "status": "ready",   "team_access": ["Clinical Engineering", "Data & Analytics"]},
    {"filename": "EHR_Integration_Guide.md",         "collection": "Clinical Documentation",  "owner": "lisa.chen",      "visibility": "team",         "status": "ready",   "team_access": ["Clinical Engineering"]},
    {"filename": "Nurse_User_Guide.md",              "collection": "Clinical Documentation",  "owner": "priya.sharma",   "visibility": "public",       "status": "ready",   "team_access": []},
    # ── Engineering & Tech (5) ────────────────────────────────────────────────
    {"filename": "Engineering_Onboarding.md",        "collection": "Engineering & Tech",      "owner": "james.wright",   "visibility": "public",       "status": "ready",   "team_access": []},
    {"filename": "Incident_Response_Playbook.md",    "collection": "Engineering & Tech",      "owner": "james.wright",   "visibility": "team",         "status": "ready",   "team_access": ["Clinical Engineering"]},
    {"filename": "Security_Risk_Assessment.md",      "collection": "Engineering & Tech",      "owner": "jessica.lane",   "visibility": "confidential", "status": "ready",   "team_access": []},
    {"filename": "On_Call_Rotation.md",              "collection": "Engineering & Tech",      "owner": "alex.torres",    "visibility": "team",         "status": "ready",   "team_access": ["Clinical Engineering"]},
    {"filename": "Product_Roadmap_Q1_2026.md",       "collection": "Engineering & Tech",      "owner": "tom.bradley",    "visibility": "team",         "status": "ready",   "team_access": ["Clinical Engineering", "Product — Patient Experience"]},
    # ── Compliance & HIPAA (5) ────────────────────────────────────────────────
    {"filename": "PHI_Audit_Procedures.md",          "collection": "Compliance & HIPAA",      "owner": "kevin.walsh",    "visibility": "team",         "status": "ready",   "team_access": ["Compliance & Regulatory"]},
    {"filename": "Data_Anonymization_Standards.md",  "collection": "Compliance & HIPAA",      "owner": "kevin.walsh",    "visibility": "team",         "status": "ready",   "team_access": ["Compliance & Regulatory", "Data & Analytics"]},
    {"filename": "FDA_510k_Preparation.md",          "collection": "Compliance & HIPAA",      "owner": "rachel.kim",     "visibility": "confidential", "status": "ready",   "team_access": []},
    {"filename": "BAA_Template.md",                  "collection": "Compliance & HIPAA",      "owner": "kevin.walsh",    "visibility": "team",         "status": "ready",   "team_access": ["Compliance & Regulatory", "Customer Success — Hospitals"]},
    {"filename": "Employee_Handbook_HealthFlow.md",  "collection": "Compliance & HIPAA",      "owner": "dr.emily.chen",  "visibility": "public",       "status": "ready",   "team_access": []},
]


# ── Document content (markdown) ───────────────────────────────────────────────

DOC_CONTENT: dict[str, str] = {

"HIPAA_Compliance_Policy.md": """# HIPAA Compliance Policy — HealthFlow Systems

## Purpose
HealthFlow Systems is a covered entity and business associate under the Health Insurance Portability and Accountability Act (HIPAA). This policy establishes the framework for protecting Protected Health Information (PHI) across all systems, processes, and personnel.

## Scope
This policy applies to all HealthFlow employees, contractors, and third-party vendors who access, process, transmit, or store PHI in any form — electronic (ePHI), paper, or verbal.

## Core HIPAA Rules

### Privacy Rule
The Privacy Rule governs the use and disclosure of PHI. PHI may only be used or disclosed for Treatment, Payment, or Healthcare Operations (TPO) without patient authorization. All other uses require written patient authorization or a documented exception (e.g., public health, law enforcement).

### Security Rule
The Security Rule requires administrative, physical, and technical safeguards to protect ePHI:
- **Administrative**: Workforce training, access management, contingency planning.
- **Physical**: Facility access controls, workstation security, device controls.
- **Technical**: Access controls, audit controls, integrity controls, transmission encryption.

### Breach Notification Rule
A breach of unsecured PHI must be reported to affected individuals within 60 days of discovery. Breaches affecting 500+ individuals must also be reported to HHS and prominent media in the affected state. Internal breach reports must be submitted to the Compliance team within 24 hours of discovery.

## Minimum Necessary Standard
All access to PHI must be limited to the minimum necessary to accomplish the intended purpose. This applies to disclosures, requests, and internal uses.

## Workforce Training
All workforce members who handle PHI must complete HIPAA training within 30 days of hire and annually thereafter. Completion is tracked in the LMS. Failure to complete training within deadlines triggers automated escalation to the Compliance Officer.

## Sanctions Policy
Violations of this policy may result in sanctions ranging from additional training to termination and referral to law enforcement. All sanctions are documented and reviewed by the Compliance Officer and CMO.

## Contact
Questions or concerns: compliance@healthflow.care
Breach reports: breach-hotline@healthflow.care (available 24/7)
""",

"Patient_Data_Handling_Guide.md": """# Patient Data Handling Guide

## Data Classification
HealthFlow classifies patient data into three tiers:
- **PHI (Protected Health Information)**: Any individually identifiable health information — name, DOB, MRN, diagnosis, treatment records, insurance IDs, geographic data smaller than a state, and 16 other HIPAA identifiers.
- **De-identified Data**: Data from which all 18 HIPAA identifiers have been removed per Safe Harbor or Expert Determination method. Not subject to HIPAA once de-identified.
- **Aggregate/Statistical Data**: Population-level summaries with no individual identifiers. May be used freely for analytics and reporting.

## Handling Rules

### Accessing PHI
PHI may only be accessed by workforce members with a documented treatment, payment, or operations purpose. All PHI access is logged. Access logs are reviewed monthly by the Compliance team.

### Transmitting PHI
All ePHI transmissions must use TLS 1.2 or higher. Email containing PHI is prohibited unless encrypted end-to-end. Use the HealthFlow Secure Messaging portal for all clinical communications.

### Storing PHI
PHI must only be stored in HealthFlow-approved systems (AWS HealthLake, our PostgreSQL clinical database). PHI must never be stored in personal devices, personal cloud storage (Dropbox, Google Drive), or unapproved SaaS tools.

### Disposing of PHI
Paper records containing PHI must be cross-cut shredded. Digital records are purged using DoD 5220.22-M standard or cryptographic erasure. Disposal is documented in the PHI Disposal Log.

## De-identification Workflow
To de-identify a dataset: (1) Submit a de-identification request to the Data team, (2) The Data team applies Safe Harbor removal of all 18 identifiers, (3) A Compliance reviewer certifies the output, (4) De-identified data may then be used for analytics or research.

## Breach Response
If you suspect a PHI breach — unauthorized access, lost device, misdirected fax — report immediately to compliance@healthflow.care and your manager. Do not attempt to investigate independently. Time-to-report is critical for HIPAA compliance.
""",

"Clinical_API_Documentation.md": """# Clinical API Documentation — HealthFlow Platform v2

## Overview
The HealthFlow Clinical API provides FHIR R4-compliant endpoints for exchanging patient and clinical data with EHR systems. All endpoints require mutual TLS and a valid Bearer token issued by our OAuth 2.0 authorization server.

## Base URL
Production: `https://api.healthflow.care/clinical/v2`
Sandbox: `https://sandbox.healthflow.care/clinical/v2`

## Authentication
```
POST /oauth/token
Body: { grant_type: "client_credentials", client_id: "...", client_secret: "..." }
Response: { access_token: "...", expires_in: 3600, token_type: "Bearer" }
```
Tokens expire after 1 hour. Rotate secrets every 90 days via the Developer Portal.

## Core FHIR Resources

### Patient
- `GET /Patient/{id}` — Retrieve patient by MRN
- `POST /Patient` — Create new patient record
- `PUT /Patient/{id}` — Update patient demographics

### Observation
- `GET /Observation?patient={id}&category=vital-signs` — Retrieve vitals
- `POST /Observation` — Submit new observation (vitals, lab results)

### Encounter
- `GET /Encounter?patient={id}&status=in-progress` — Active encounters
- `POST /Encounter` — Create encounter record

### DocumentReference
- `POST /DocumentReference` — Attach clinical document (CCD, PDF)
- `GET /DocumentReference?patient={id}` — List patient documents

## HL7 FHIR Compliance
All resources conform to HL7 FHIR R4. Validation errors return OperationOutcome resources. Terminology bindings use SNOMED CT, LOINC, and RxNorm.

## Rate Limits
100 requests/minute per client credential. Burst: 200 requests for up to 10 seconds. Rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

## Error Codes
- 400 Bad Request — Invalid FHIR resource or missing required fields
- 401 Unauthorized — Invalid or expired token
- 403 Forbidden — Insufficient scope for requested resource
- 422 Unprocessable Entity — FHIR validation failure
- 429 Rate Limited — Slow down requests
""",

"EHR_Integration_Guide.md": """# EHR Integration Guide

## Supported EHR Systems
HealthFlow supports native integrations with: Epic (MyChart), Cerner (PowerChart), Meditech Expanse, and Allscripts. Custom HL7 v2.x integrations are available for legacy systems.

## Epic Integration

### Setup
1. Register HealthFlow in Epic's App Orchard as a third-party application.
2. Configure your Epic instance to use Smart on FHIR (SMART App Launch Framework).
3. Provide HealthFlow with your Epic FHIR endpoint and client credentials.
4. HealthFlow will complete the Epic OAuth2 configuration within 3 business days.

### Data Flows
- **Inbound**: Patient demographics, encounter data, lab results, vital signs, medication lists.
- **Outbound**: Care plan updates, remote monitoring data, patient-reported outcomes.
- **Sync frequency**: Near-real-time (webhook) for encounter events; batch nightly for demographics refresh.

## Cerner Integration
Cerner uses the HL7 FHIR DSTU2 endpoint for data exchange. Configure the Cerner SMART App in the Cerner App Gallery. HealthFlow supports the CernerCare patient identity federation model.

## HL7 v2.x Integration (Legacy)
For EHRs without FHIR support, HealthFlow accepts HL7 v2.3–2.6 messages over MLLP:
- ADT (Admit/Discharge/Transfer): Patient registration and movement events
- ORU (Observation Result): Lab results and clinical observations
- ORM (Order Message): Orders and requisitions

Configure your EHR to forward HL7 messages to: `hl7.healthflow.care:2575` (TLS-wrapped MLLP).

## Testing
All integrations must be validated in the HealthFlow sandbox environment before production go-live. Use synthetic patient data only in sandbox. Provide a signed Data Use Agreement before accessing production data.

## Support
Integration support: integrations@healthflow.care
On-call integration engineer (P0 issues): +1-800-HFLOW-01
""",

"Nurse_User_Guide.md": """# HealthFlow Platform — Nurse User Guide

## Getting Started
Welcome to HealthFlow. This guide covers how to use the platform for your daily clinical workflows.

## Logging In
Navigate to `app.healthflow.care` and sign in with your hospital SSO credentials. If SSO is not configured, use your HealthFlow username (your work email) and the password set during onboarding. Enable MFA — it is required for all clinical users.

## Viewing Patient Information
1. From the Dashboard, select **Patients** in the left navigation.
2. Search by MRN, last name, or date of birth.
3. Click the patient card to open their longitudinal health record.
4. Tabs available: Summary, Vitals, Medications, Labs, Documents, Care Team.

## Documenting Vital Signs
1. Open the patient record and select the **Vitals** tab.
2. Click **+ Add Vitals**.
3. Enter values for blood pressure, heart rate, SpO2, temperature, and respiratory rate.
4. Select the observation date/time (defaults to now).
5. Click **Save** — the observation is submitted to the FHIR server in real time.

## Secure Messaging
Use the **Messages** tab to communicate with the care team. Do NOT use personal email or SMS for clinical communications — these are not HIPAA-compliant. HealthFlow messages are encrypted and logged.

## Accessing Clinical Documents
Documents such as discharge summaries and care plans are in the **Documents** tab. Search the HealthFlow knowledge base using the search bar at the top of any page.

## Reporting Issues
If you encounter a data discrepancy or technical issue, use the **Report Issue** button (flag icon, bottom right). For urgent patient safety issues, call the on-call clinical engineer directly: contact your charge nurse for the current on-call number.

## Privacy Reminder
You are authorized to access only the records of patients under your direct care. Do not access records out of personal curiosity — all access is logged and audited.
""",

"Engineering_Onboarding.md": """# Engineering Onboarding — HealthFlow Systems

## Welcome
Welcome to the HealthFlow engineering team. You are building software that clinicians and patients depend on. Security, reliability, and privacy are non-negotiable at every layer of the stack.

## Before Day 1 (IT Admin)
- [ ] Provision MacBook Pro with full-disk encryption (FileVault)
- [ ] Create accounts: GitHub (HealthFlow org), AWS, Okta SSO, Slack, Linear, 1Password
- [ ] Add to the on-call rotation wiki (view-only for first 30 days)
- [ ] Enroll in HIPAA workforce training (must complete by Day 14)

## Day 1 Checklist
- [ ] Complete HIPAA training in the LMS — mandatory before any PHI system access
- [ ] Set up 1Password and enable MFA on all accounts
- [ ] Clone the main repos: `healthflow-api`, `healthflow-frontend`, `healthflow-infra`
- [ ] Follow the local dev setup guide in the repo README
- [ ] Meet with your manager for 30-day plan alignment

## Week 1 Goals
- Understand the FHIR R4 data model and HealthFlow's clinical API
- Read: HIPAA Compliance Policy, Security Risk Assessment, Incident Response Playbook
- Complete security awareness training
- Ship one small bug fix or doc improvement to understand the deploy pipeline

## Tech Stack
- **Backend**: Python / FastAPI, SQLAlchemy (async), PostgreSQL, AWS HealthLake (FHIR store)
- **Frontend**: Next.js, TypeScript, Tailwind CSS
- **Infrastructure**: AWS (EKS, RDS, HealthLake, S3), Terraform, ArgoCD
- **Monitoring**: Datadog APM, PagerDuty, structured logging (JSON to CloudWatch)

## PHI in Development
Never use real patient data in local development or staging. Use the synthetic data generator: `make generate-synthetic-patients`. All staging data is synthetic and does not constitute PHI.

## Code Review Standards
All PRs require 2 approvals. PRs touching PHI-handling code require review from the Security Engineer (jessica.lane). Production deploys require VP Engineering approval on Fridays after 3pm.
""",

"Incident_Response_Playbook.md": """# Incident Response Playbook — HealthFlow Systems

## Severity Definitions
- **P0 (Critical)**: PHI breach, production clinical system down, patient safety risk. Page immediately.
- **P1 (High)**: EHR integration failure affecting active patients, >10% API error rate.
- **P2 (Medium)**: Degraded performance, non-critical feature outage, workaround available.
- **P3 (Low)**: Minor UI bug, non-urgent data discrepancy.

## P0 Response Procedure
1. **Detect**: Alert fires in Datadog or report received via clinical staff.
2. **Acknowledge**: On-call engineer acknowledges within 5 minutes via PagerDuty.
3. **Isolate**: If a PHI breach is suspected, immediately revoke affected credentials and isolate affected systems. Do NOT wait for root cause.
4. **Notify**: Post in #incidents Slack channel. Page the VP Engineering and CMO within 10 minutes.
5. **Compliance Notification**: If PHI exposure is confirmed, notify the Compliance Officer immediately. The 24-hour internal breach reporting clock starts now.
6. **Mitigate**: Rollback last deploy, disable affected integration, or route traffic to fallback. Mitigation before root cause analysis.
7. **Communicate**: Post status updates every 30 minutes in #incidents and to the Customer Success team.
8. **Resolve & Postmortem**: Complete within 48 hours using the postmortem template in Confluence.

## PHI Breach Response
Suspected PHI breach triggers additional obligations:
- Compliance Officer coordinates notification to affected patients (within 60 days).
- HHS notification required for breaches of 500+ individuals.
- Document everything: who discovered it, when, what data was involved, who was notified.

## On-Call Rotation
On-call schedule is maintained in PagerDuty. Two engineers are always on call: a primary and secondary. Escalation path: Primary → Secondary → VP Engineering → CMO (for clinical P0s only).

## Communication Templates
**Initial**: "We are investigating an issue with [system]. Clinical workflows may be affected. Status updates every 30 minutes."
**Resolved**: "Incident resolved at [time]. Impact duration: [X] minutes. Postmortem to follow within 48 hours."
""",

"Security_Risk_Assessment.md": """# Security Risk Assessment 2025 — CONFIDENTIAL

## Scope
This assessment covers HealthFlow Systems' technical infrastructure, PHI handling practices, and third-party integrations as of Q4 2025.

## Risk Summary
| Risk | Likelihood | Impact | Rating | Status |
|------|-----------|--------|--------|--------|
| PHI exposure via misconfigured S3 bucket | Low | Critical | High | Mitigated — bucket policies enforced |
| Credential theft via phishing | Medium | High | High | Mitigated — MFA mandatory, phishing sim quarterly |
| EHR integration credential compromise | Low | Critical | High | In progress — rotating to short-lived tokens |
| Insider threat — unauthorized PHI access | Low | High | Medium | Monitoring — audit logs reviewed monthly |
| Third-party vendor breach (sub-processor) | Medium | High | High | Mitigated — BAAs in place, annual vendor audits |
| Ransomware via unpatched dependency | Medium | Critical | High | Monitoring — Snyk in CI, patches within 72h |

## Critical Finding: EHR Integration Credentials
Current EHR integration credentials are long-lived API keys stored in AWS Secrets Manager. Recommendation: migrate to short-lived OAuth 2.0 client credentials with 1-hour expiry. Owner: jessica.lane. Target: Q1 2026.

## Encryption Standards
- Data at rest: AES-256 (AWS KMS-managed keys)
- Data in transit: TLS 1.2 minimum, TLS 1.3 preferred
- Database backups: Encrypted with separate KMS key, stored in isolated S3 bucket
- ePHI fields in PostgreSQL: Column-level encryption for SSN, DOB, MRN

## Penetration Test Results
Most recent pentest: October 2025 (conducted by CrowdStrike). Critical findings: 0. High findings: 1 (remediated — IDOR in patient document endpoint). Medium: 3 (2 remediated, 1 in progress).

## HIPAA Security Rule Compliance
Administrative safeguards: Compliant. Physical safeguards: Compliant. Technical safeguards: Mostly compliant — 1 open item (audit control gaps in legacy HL7 v2 pipeline, owner: alex.torres, due Q1 2026).
""",

"On_Call_Rotation.md": """# On-Call Rotation — HealthFlow Engineering

## Schedule
On-call rotations run Monday 9am to Monday 9am (UTC). The schedule is published 4 weeks in advance in PagerDuty and the #on-call Slack channel.

## Current Q1 2026 Rotation
| Week | Primary | Secondary |
|------|---------|-----------|
| Jan 20 – Jan 27 | raj.kumar | jessica.lane |
| Jan 27 – Feb 3 | alex.torres | david.brooks |
| Feb 3 – Feb 10 | lisa.chen | raj.kumar |
| Feb 10 – Feb 17 | jessica.lane | alex.torres |
| Feb 17 – Feb 24 | david.brooks | lisa.chen |
| Feb 24 – Mar 3 | raj.kumar | jessica.lane |
| Mar 3 – Mar 10 | alex.torres | david.brooks |
| Mar 10 – Mar 17 | lisa.chen | raj.kumar |

## Responsibilities
**Primary on-call**: Acknowledge PagerDuty alerts within 5 minutes. Lead incident response. Update #incidents channel.
**Secondary on-call**: Available as backup if primary does not acknowledge within 10 minutes. Assist on P0/P1 incidents.

## Escalation
If primary does not acknowledge within 10 minutes, PagerDuty auto-escalates to secondary. If secondary does not acknowledge within 5 more minutes, VP Engineering (james.wright) is paged.

## Compensation
On-call engineers receive $200/week while on primary rotation. Incident response beyond 1 hour outside business hours is compensated at 1.5× hourly rate.

## Swapping Rotations
Swap requests must be submitted in PagerDuty and confirmed by both parties and your manager at least 72 hours in advance.

## Clinical P0 Escalation
For P0 incidents with patient safety implications, the on-call engineer must also notify the CMO (dr.emily.chen) directly. Her emergency line is in the 1Password Engineering vault under "Clinical Escalation Contacts."
""",

"Product_Roadmap_Q1_2026.md": """# Product Roadmap Q1 2026 — HealthFlow Systems

## Theme: Clinical Depth + Hospital Scale

Q1 2026 is focused on deepening clinical workflow integrations and improving reliability for our largest hospital customers.

## January 2026
- **Epic SMART on FHIR Launch**: Full Epic integration using SMART App Launch. Enables single sign-on and embedded HealthFlow workflow in Epic's EHR UI. Priority: P0.
- **Vital Signs Dashboard v2**: Real-time vitals charting with trend analysis and configurable alert thresholds for nurses.
- **Performance**: API P95 latency target < 120ms. Database query optimization sprint.

## February 2026
- **Care Team Messaging**: Secure, HIPAA-compliant messaging between care team members within the patient context. Replaces ad-hoc SMS.
- **Patient Reported Outcomes (PRO) Module**: Digital PRO questionnaires sent to patients pre/post encounter. Results automatically populate FHIR Observation resources.
- **Cerner Integration Beta**: Pilot with 2 Cerner hospital customers. GA in Q2.

## March 2026
- **Anomaly Detection — Vitals**: ML model flags abnormal vital sign patterns for nurse review. First AI-assisted clinical feature.
- **Audit Log Dashboard**: Self-service PHI audit log viewer for Compliance Officers at hospital customers.
- **Mobile App — iOS**: Native iOS app for nurses: vitals entry, secure messaging, patient search.

## Not in Q1
- Android mobile app (Q2)
- Allscripts integration (Q3)
- Voice documentation features (under research)

## Success Metrics
- Epic integration live in 5 hospital customers by March 31
- Vitals Dashboard v2 adopted by 80% of active nurse users within 30 days of launch
- API uptime ≥ 99.95% for the quarter
""",

"PHI_Audit_Procedures.md": """# PHI Audit Procedures

## Purpose
HealthFlow conducts regular audits of PHI access to detect unauthorized access, verify minimum necessary compliance, and satisfy HIPAA audit control requirements.

## Audit Frequency
- **Automated daily**: System scans for anomalous access patterns (bulk downloads, off-hours access, access to patients not in provider's panel).
- **Manual monthly**: Compliance team reviews access logs for high-risk roles (admin users, integration accounts).
- **Triggered audits**: Any reported complaint, suspected breach, or anomaly flagged by the automated system triggers an immediate audit.

## Audit Log Sources
- AWS CloudTrail (API calls to HealthLake and S3)
- PostgreSQL audit log (pgaudit extension — logs all SELECTs on PHI tables)
- Application access log (user, patient MRN, action, timestamp, IP)
- FHIR server audit events (AuditEvent resources per FHIR spec)

## Audit Procedure — Monthly Manual Review
1. Export access logs for the month from the Compliance Dashboard.
2. Filter for: admin accounts, after-hours access (outside 7am–7pm local time), bulk exports (>50 records in a session), new employees within first 90 days.
3. For each flagged record, verify a legitimate clinical purpose exists in the patient's encounter record.
4. Document findings in the PHI Audit Log (Confluence).
5. For unexplained access: notify the individual's manager and open a compliance investigation.

## Audit Retention
PHI audit logs are retained for 6 years per HIPAA requirements. Logs are stored in an immutable S3 bucket with Object Lock enabled.

## Reporting
Audit findings are reported to the CMO and Board Compliance Committee quarterly. Material findings (unauthorized access, potential breach) are reported immediately.
""",

"Data_Anonymization_Standards.md": """# Data Anonymization Standards

## Overview
HealthFlow uses de-identified and anonymized data for product analytics, ML model training, and research partnerships. This document governs how PHI is de-identified and the standards that apply.

## HIPAA Safe Harbor Method
The Safe Harbor method requires removal of all 18 HIPAA identifiers:
1. Names, 2. Geographic subdivisions smaller than a state, 3. Dates (except year) for individuals ≥90 years old, 4. Phone numbers, 5. Fax numbers, 6. Email addresses, 7. Social security numbers, 8. Medical record numbers, 9. Health plan beneficiary numbers, 10. Account numbers, 11. Certificate/license numbers, 12. Vehicle identifiers, 13. Device identifiers, 14. Web URLs, 15. IP addresses, 16. Biometric identifiers, 17. Full-face photographs, 18. Any other unique identifying number or code.

## Expert Determination Method
For datasets where Safe Harbor removal would destroy analytical utility, HealthFlow's designated Expert may certify de-identification using statistical methods. The Expert must document the methods and results, and the probability of re-identification must be "very small."

## De-identification Pipeline
1. **Input**: Raw clinical dataset from PostgreSQL or HealthLake.
2. **PII scan**: Automated scan using Presidio (Microsoft) flags candidate PII fields.
3. **Removal/masking**: All 18 Safe Harbor identifiers are removed or replaced with synthetic equivalents.
4. **Date shifting**: Dates are shifted by a consistent random offset per patient (preserving intervals while removing absolute dates).
5. **Certification**: Compliance reviewer signs off on the output dataset.
6. **Output**: De-identified dataset tagged with schema version and certification date.

## Prohibited Uses of PHI
PHI must never be used for: ML model training without IRB approval or patient consent, marketing, benchmarking against competitors, or sharing with third parties without a BAA.

## Synthetic Data Generation
For development and testing, use `make generate-synthetic-patients` which generates FHIR-compliant synthetic patient bundles using Synthea. These data are not PHI.
""",

"FDA_510k_Preparation.md": """# FDA 510(k) Premarket Notification — Preparation Guide — CONFIDENTIAL

## Background
HealthFlow's Anomaly Detection — Vitals feature (planned Q1 2026) constitutes a Software as a Medical Device (SaMD) under FDA guidance. A 510(k) premarket notification is required before commercial distribution of this feature.

## Regulatory Classification
Device class: Class II (Special Controls). Predicate device: Masimo SafetyNet (K192919) — remote patient monitoring system. Intended use: To assist clinicians in identifying abnormal vital sign patterns for timely follow-up. It does not diagnose or treat.

## 510(k) Submission Requirements
The submission must include:
1. **Device description**: Software architecture, intended use, indications for use.
2. **Substantial equivalence**: Comparison to predicate device Masimo SafetyNet.
3. **Performance testing**: Algorithm validation on retrospective clinical dataset (minimum 1,000 patients, 3 clinical sites).
4. **Cybersecurity documentation**: Per FDA Cybersecurity Guidance (2023) — SBOM, threat modeling, vulnerability management plan.
5. **Labeling**: Instructions for use, warnings, contraindications.
6. **Quality system**: Evidence of FDA 21 CFR Part 11 compliance for electronic records.

## Timeline
- Q4 2025: Algorithm validation study (Owner: marcus.hayes, sarah.nguyen)
- Jan 2026: Draft 510(k) submission package (Owner: rachel.kim)
- Feb 2026: External regulatory counsel review (Firm: Hogan Lovells)
- Mar 2026: Submit to FDA Center for Devices and Radiological Health (CDRH)
- Expected FDA review: 90 days from submission

## Interim Restrictions
The Anomaly Detection feature must NOT be made available to customers as a decision-support tool until 510(k) clearance is received. It may be piloted as a "research mode" feature with explicit informed consent and IRB oversight.

## Contact
Regulatory Affairs: rachel.kim@healthflow.care
External Counsel: J. Peterson, Hogan Lovells (contact in 1Password Legal vault)
""",

"BAA_Template.md": """# Business Associate Agreement (BAA) Template

## HIPAA BUSINESS ASSOCIATE AGREEMENT

This Business Associate Agreement ("BAA") is entered into between **HealthFlow Systems, Inc.** ("Covered Entity") and [**VENDOR NAME**] ("Business Associate") as of [DATE].

## 1. Definitions
Terms used in this BAA shall have the same meaning as in the HIPAA Rules (45 CFR Parts 160 and 164). "PHI" means Protected Health Information as defined in 45 CFR § 160.103.

## 2. Permitted Uses and Disclosures
Business Associate may use or disclose PHI only: (a) as necessary to provide services described in the underlying Service Agreement; (b) as required by law; (c) as permitted by the Privacy Rule for Business Associates.

## 3. Obligations of Business Associate
Business Associate agrees to:
- Use appropriate safeguards (per HIPAA Security Rule) to prevent unauthorized use or disclosure of ePHI.
- Report any Security Incident or Breach to HealthFlow within **24 hours** of discovery.
- Ensure any subcontractors that handle PHI sign a BAA with equivalent protections.
- Make its facilities, books, and records available to HHS for compliance audits.
- Return or destroy all PHI upon termination of the Service Agreement within **30 days**.

## 4. HealthFlow Obligations
HealthFlow will: (a) notify Business Associate of any PHI use limitations that affect Business Associate's services; (b) obtain patient authorizations when required before disclosure.

## 5. Term and Termination
This BAA remains in effect for the duration of the Service Agreement. Either party may terminate if the other materially breaches and fails to cure within 30 days of written notice.

## 6. Governing Law
This BAA is governed by the laws of the State of Delaware and applicable federal HIPAA regulations.

---
*This template must be reviewed by Legal before execution. Contact legal@healthflow.care.*
""",

"Employee_Handbook_HealthFlow.md": """# HealthFlow Systems Employee Handbook

## Mission
HealthFlow Systems builds clinical software that helps nurses and physicians spend more time with patients and less time on paperwork. We are driven by the belief that better healthcare technology saves lives.

## Core Values
- **Patient First**: Every product decision, engineering trade-off, and process starts with patient safety and outcomes.
- **Privacy by Design**: We protect patient data as if it were our own family's records.
- **Clinical Humility**: We work alongside clinicians, not instead of them. We listen before we build.
- **Reliability**: In healthcare, downtime is not an inconvenience — it affects care. We build for 99.99%.

## HIPAA Obligations
All HealthFlow employees are workforce members under HIPAA. You must: (1) complete HIPAA training within 30 days of hire and annually, (2) access only the minimum PHI necessary for your role, (3) report any suspected breach immediately. Violations can result in personal civil and criminal penalties in addition to employment sanctions.

## Work Hours
Core hours are 9am–4pm in your local timezone. Clinical-facing teams should be reachable during hospital business hours (8am–6pm ET/PT). On-call engineers follow the rotation published in PagerDuty.

## Remote Work
HealthFlow is remote-first. You must use the company VPN whenever accessing production systems or PHI. Company devices only for production access — no personal devices. Home office stipend: $1,000 for new hires (first 60 days).

## Benefits
- Health insurance: 90% employer-paid premium (employee), 70% (dependents)
- Dental and vision included
- 401(k) with 5% employer match, immediate vesting
- 20 days PTO + 10 sick days per year
- $2,000 annual learning stipend (conferences, certifications, courses)
- Parental leave: 16 weeks primary, 8 weeks secondary caregiver

## Code of Conduct
Treat colleagues, patients, and partners with respect. Do not share confidential information — especially PHI — outside of authorized channels. Report concerns to compliance@healthflow.care or anonymously via our ethics hotline.
""",
}


# ── Public channel definitions ────────────────────────────────────────────────

PUBLIC_CHANNELS = [
    {"name": "general",            "dept_filter": "all",                                                       "msg_count": 80,  "pool": "GENERAL"},
    {"name": "engineering",        "dept_filter": ["Engineering", "Operations"],                               "msg_count": 60,  "pool": "ENG"},
    {"name": "clinical-ops",       "dept_filter": ["Clinical", "Analytics"],                                   "msg_count": 50,  "pool": "CLINICAL"},
    {"name": "compliance-updates", "dept_filter": "all",                                                       "msg_count": 30,  "pool": "COMPLIANCE"},
]

# ── DM pairs (10 cross-functional pairs) ──────────────────────────────────────

DM_PAIRS = [
    ("dr.emily.chen",   "james.wright"),
    ("dr.emily.chen",   "kevin.walsh"),
    ("james.wright",    "raj.kumar"),
    ("james.wright",    "jessica.lane"),
    ("kevin.walsh",     "rachel.kim"),
    ("kevin.walsh",     "dr.emily.chen"),
    ("sarah.nguyen",    "marcus.hayes"),
    ("priya.sharma",    "tom.bradley"),
    ("omar.farid",      "support.ryan.cole"),
    ("lisa.chen",       "raj.kumar"),
]

# ── Message pools ──────────────────────────────────────────────────────────────

MSGS: dict[str, list[str]] = {
"GENERAL": [
    "Good morning team! Reminder that weekly standups start at 9am today.",
    "Shoutout to the clinical engineering team for the flawless Epic go-live this morning!",
    "HIPAA training renewal reminder — everyone must complete by end of month.",
    "Welcome to our new compliance analyst! Glad to have you on board.",
    "Q1 roadmap is posted — check the Product Roadmap doc in Engineering & Tech.",
    "Reminder: never use personal devices to access patient data. Use company-issued hardware only.",
    "All hands is this Friday — add your questions to the shared doc.",
    "Congrats to the team — we just signed our 10th hospital system. Incredible milestone.",
    "PHI reminder: do not share patient information in Slack, even in DMs. Use secure messaging.",
    "Office VPN is required for all production system access. Please update your client.",
    "The new anomaly detection feature is in beta — nurses are loving the early results.",
    "Incident postmortem from last week is posted in the Engineering & Tech collection.",
    "Home office stipend reminder: submit receipts within 60 days of purchase.",
    "Epic integration is now live for three hospital customers. Smooth launch!",
    "Happy Friday! Reminder about the no-deploy window: Friday 4pm to Monday 9am.",
    "Annual security training completion is at 91% — last 9% please finish this week.",
    "New BAA template is in the Compliance & HIPAA collection. Use it for all new vendors.",
    "The FDA 510(k) submission timeline is on track. Big milestone for the team.",
    "Care team messaging feature is getting great reviews from our nursing staff.",
    "Quick reminder: all PHI access must have a documented clinical purpose.",
],
"ENG": [
    "PR #214 is up for review — FHIR R4 Patient endpoint refactor. Need 2 approvals.",
    "Epic sandbox integration is working in staging. Moving to production testing tomorrow.",
    "Heads up: HL7 v2 pipeline had a 20-minute delay last night. Root cause: Mirth Connect memory pressure. Fixed.",
    "Dependency update PR is up — 8 packages, all security patches. Critical CVE resolved.",
    "API P95 latency is down to 108ms this week. Approaching Q1 target of <120ms.",
    "No deploys to production Friday afternoon without VP approval. Clinical systems are too critical.",
    "New runbook added: how to handle HealthLake throttling during peak ingest hours.",
    "Postmortem for last Tuesday's EHR sync delay is in the Engineering & Tech collection.",
    "Reminder: all PHI-handling code changes require review from jessica.lane.",
    "The synthetic patient generator now outputs 500 patients in under 2 minutes. Much faster.",
    "PagerDuty schedule updated for Q1. Please check your on-call week.",
    "Column-level encryption is now live on PHI fields in PostgreSQL. ",
    "Care team messaging passed HIPAA technical safeguard review. Ready to ship.",
    "Staging is back up after the maintenance window. All smoke tests passing.",
    "Snyk scan flagged a high-severity CVE in a dependency — PR for patch in review now.",
],
"CLINICAL": [
    "Reminder to nursing staff: document vitals within 30 minutes of observation per hospital policy.",
    "New vital signs dashboard is live in staging — feedback welcome before production launch.",
    "Clinical API documentation has been updated. See the latest FHIR endpoint specs.",
    "Epic go-live at St. Catherine's Hospital is confirmed for January 28. Prep checklist posted.",
    "PHI audit for Q4 2025 is complete. No unauthorized access found. Great work, team.",
    "Patient reported outcomes questionnaires are showing 74% completion rate. Strong early signal.",
    "Reminder: use HealthFlow Secure Messaging for all clinical communications. Not email, not SMS.",
    "The anomaly detection pilot with Dr. Rodriguez's cardiology unit is showing promising sensitivity metrics.",
    "HL7 integration with Riverside Medical Center is complete. Smooth data flow.",
    "New nurse user guide is in the Clinical Documentation collection — share with hospital customers.",
    "Clinical data sync with Epic is now near-real-time. Latency dropped from 15 min to 45 seconds.",
    "Care plan module update: auto-population from encounter data is working correctly.",
    "FHIR validation errors in last week's batch: 3 records rejected due to missing required fields. Investigating.",
    "Cerner integration beta is progressing well. Pilot customers are engaged.",
    "Reminder: de-identify all datasets before sending to the Analytics team for modeling.",
],
"COMPLIANCE": [
    "HIPAA training completion deadline is March 31. Current rate: 91%.",
    "New BAA template has been approved by Legal. All new vendor agreements must use this version.",
    "PHI audit for Q4 2025 is complete — report in the Compliance & HIPAA collection.",
    "FDA 510(k) preparation is on track. Algorithm validation study wraps up end of January.",
    "Reminder: all third-party vendors handling PHI must have a signed BAA before receiving data access.",
    "HIPAA breach notification drill is scheduled for February 14. Details in the calendar.",
    "Annual risk assessment is underway. Provide your team's input to kevin.walsh by February 1.",
    "Reminder: the Minimum Necessary Standard applies to all PHI access. Request only what you need.",
    "New employee HIPAA acknowledgment forms are due to HR within 14 days of hire.",
    "Penetration test is scheduled for March. Engineering teams — please ensure test environments are ready.",
    "Data anonymization standards doc has been updated. Review before starting any analytics work involving PHI.",
    "Vendor BAA renewals due this quarter: 3 vendors. rachel.kim is coordinating.",
    "SOC 2 Type II audit prep is starting in Q2. All teams will need to provide evidence.",
    "Reminder: report any suspected PHI breach to compliance@healthflow.care within 24 hours.",
    "The compliance committee meets the first Thursday of each month. Agenda posted in shared calendar.",
],
"DM": [
    "Hey, do you have 15 minutes to sync on the Epic integration issue?",
    "Just flagging this — the PHI audit flagged an access pattern we should review.",
    "Can you take a look at this PR? It touches the FHIR Patient endpoint.",
    "Quick question — do we need a new BAA for this vendor before the demo?",
    "Thanks for covering standup yesterday, I was with a hospital customer.",
    "Are you joining the compliance committee meeting this Thursday?",
    "The hospital is asking about our HIPAA audit report — can we share the summary?",
    "I think the on-call rotation needs an update — can you check PagerDuty?",
    "Just a heads up: I'm taking Friday off. You'll need to cover the on-call handoff.",
    "Did you see the FDA feedback? They want more detail on the algorithm validation.",
    "Quick sync today at 2pm? Want to walk through the Epic go-live checklist.",
    "The customer is asking about our 510(k) timeline — what can I share?",
    "Can you review the BAA before we send it to the hospital's legal team?",
    "Are we still on for the weekly clinical sync tomorrow?",
    "The HL7 parser is throwing errors on a specific message type — logging a ticket now.",
    "Great catch on that PHI handling issue in the PR — almost missed it.",
    "Reminder about the HIPAA training deadline — only 3 days left.",
    "Can you pull the latest PHI access report for the compliance review?",
    "The anomaly detection model performance metrics look solid. Ready to share with CMO?",
    "Thanks for the introduction to the hospital CIO — really productive call.",
],
}

# ── DM pair message counts ─────────────────────────────────────────────────────
DM_MSG_COUNT = (10, 25)


# ── Phase 1: Foundation ────────────────────────────────────────────────────────

async def seed_permissions(session) -> dict[str, Permission]:
    """Ensure all Permission records exist. Returns name→Permission map."""
    perm_map: dict[str, Permission] = {}
    for resource, action, description in ALL_PERMISSIONS:
        name = f"{resource}:{action}"
        result = await session.execute(
            select(Permission).where(Permission.name == name)
        )
        perm = result.scalar_one_or_none()
        if not perm:
            perm = Permission(
                id=str(uuid.uuid4()),
                name=name,
                resource_type=resource,
                action=action,
            )
            session.add(perm)
        perm_map[name] = perm
    await session.flush()
    return perm_map


async def seed_role_permissions(session, perm_map: dict[str, Permission]) -> dict[str, Role]:
    """Ensure roles exist and link permissions to them. Returns name→Role map."""
    role_map: dict[str, Role] = {}
    for role_name, perm_names in ROLE_PERMISSION_MAP.items():
        result = await session.execute(select(Role).where(Role.name == role_name))
        role = result.scalar_one_or_none()
        if not role:
            role = Role(id=str(uuid.uuid4()), name=role_name, description=f"{role_name.capitalize()} role")
            session.add(role)
            await session.flush()
            print(f"  [roles]       created role '{role_name}'")

        existing_perm_names = {p.name for p in role.permissions}
        for pname in perm_names:
            if pname not in existing_perm_names and pname in perm_map:
                role.permissions.append(perm_map[pname])

        role_map[role_name] = role
    await session.flush()
    return role_map


async def seed_company(session) -> str:
    """Create or upsert the HealthFlow Systems Company record. Returns the company id."""
    existing = await session.execute(
        select(Company).where(Company.slug == COMPANY["slug"])
    )
    existing_company = existing.scalar_one_or_none()
    if existing_company:
        print(f"  [company]     skipped — already exists (id={existing_company.id})")
        return existing_company.id

    company = Company(
        id=str(uuid.uuid4()),
        name=COMPANY["name"],
        slug=COMPANY["slug"],
        plan="professional",
        max_users=150,
        max_storage_gb=250,
        owner_email=f"dr.emily.chen@{COMPANY['domain']}",
        brand_color="#10B981",
        notes="HealthFlow Systems — healthcare/health-tech company tenant",
    )
    session.add(company)
    await session.flush()
    print(f"  [company]     created '{company.name}' (id={company.id})")
    return company.id


async def seed_users(session, role_map: dict[str, Role], company_id: str) -> list[User]:
    """Create 30 HealthFlow users. Skips existing usernames."""
    created: list[User] = []
    admin_count = analyst_count = viewer_count = skipped = 0

    for username, title, dept, role_name in USERS:
        result = await session.execute(select(User).where(User.username == username))
        if result.scalar_one_or_none():
            skipped += 1
            continue

        is_admin_user = role_name == "admin"
        password = COMPANY["admin_password"] if is_admin_user else COMPANY["user_password"]
        email = f"{username}@{COMPANY['domain']}"

        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            hashed_password=hash_password(password),
            is_active=True,
            company_id=company_id,
        )
        role = role_map.get(role_name)
        if role:
            user.roles.append(role)

        session.add(user)
        created.append(user)

        if role_name == "admin":
            admin_count += 1
        elif role_name == "analyst":
            analyst_count += 1
        else:
            viewer_count += 1

    await session.flush()

    summary = f"{admin_count} admin, {analyst_count} analyst, {viewer_count} viewer"
    if skipped:
        summary += f" ({skipped} skipped — already exist)"
    print(f"  [users]       {len(created)} created  ({summary})")
    return created


# ── Phase 2: Teams ────────────────────────────────────────────────────────────

async def seed_teams(session, company_id: str) -> list[Team]:
    """Create 5 teams and their memberships. Skips existing team names."""
    result = await session.execute(select(User.username, User.id))
    user_id_map: dict[str, str] = {row[0]: row[1] for row in result.all()}

    if not user_id_map:
        print("  [warn] no users found — run Phase 1 first")
        return []

    base_ts = datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc)

    teams_created: list[Team] = []
    total_memberships = 0
    skipped_teams = 0

    for i, tdata in enumerate(TEAMS):
        existing = await session.execute(select(Team).where(Team.name == tdata["name"]))
        if existing.scalar_one_or_none():
            skipped_teams += 1
            continue

        creator_id = user_id_map.get(tdata["created_by"])
        if not creator_id:
            print(f"  [warn] creator '{tdata['created_by']}' not found, skipping team '{tdata['name']}'")
            continue

        team = Team(
            id=str(uuid.uuid4()),
            name=tdata["name"],
            description=tdata["description"],
            created_by=creator_id,
            company_id=company_id,
            created_at=base_ts + timedelta(hours=i),
            updated_at=base_ts + timedelta(hours=i),
        )
        session.add(team)
        await session.flush()

        seen: set[str] = set()
        for username in tdata["members"]:
            if username in seen:
                continue
            seen.add(username)

            member_id = user_id_map.get(username)
            if not member_id:
                continue

            membership = TeamMembership(
                id=str(uuid.uuid4()),
                team_id=team.id,
                user_id=member_id,
                joined_at=base_ts + timedelta(hours=i, minutes=total_memberships % 60),
            )
            session.add(membership)
            total_memberships += 1

        teams_created.append(team)

    await session.flush()

    summary = f"{len(teams_created)} teams, {total_memberships} memberships"
    if skipped_teams:
        summary += f" ({skipped_teams} teams skipped — already exist)"
    print(f"  [teams]       {summary}")
    return teams_created


# ── Phase 3: Collections ──────────────────────────────────────────────────────

async def seed_collections(session, company_id: str) -> dict[str, str]:
    """Create 3 collections. Returns name→id map for use by Phase 4."""
    result = await session.execute(select(User.username, User.id))
    user_id_map: dict[str, str] = {row[0]: row[1] for row in result.all()}

    base_ts = datetime(2025, 3, 15, 10, 0, tzinfo=timezone.utc)
    created = 0
    skipped = 0
    coll_id_map: dict[str, str] = {}

    for i, cdata in enumerate(COLLECTIONS):
        existing = await session.execute(
            select(Collection).where(Collection.name == cdata["name"])
        )
        existing_coll = existing.scalar_one_or_none()
        if existing_coll:
            coll_id_map[cdata["name"]] = existing_coll.id
            skipped += 1
            continue

        owner_id = user_id_map.get(cdata["owner"])
        if not owner_id:
            print(f"  [warn] owner '{cdata['owner']}' not found, skipping collection '{cdata['name']}'")
            continue

        coll = Collection(
            id=str(uuid.uuid4()),
            name=cdata["name"],
            description=cdata["description"],
            owner_id=owner_id,
            company_id=company_id,
            is_public=cdata["is_public"],
            created_at=base_ts + timedelta(days=i),
        )
        session.add(coll)
        coll_id_map[cdata["name"]] = coll.id
        created += 1

    await session.flush()

    summary = f"{created} created"
    if skipped:
        summary += f", {skipped} skipped"
    print(f"  [collections] {summary}")
    return coll_id_map


# ── Phase 4: Documents ────────────────────────────────────────────────────────

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads" / "company_two"


async def seed_documents(session) -> dict[str, str]:
    """Create 15 document records + write .md files. Returns filename→doc_id map."""
    from src.models.document import Document, DocumentTeamAccess, DocumentStatusEnum, VisibilityEnum

    user_res  = await session.execute(select(User.username, User.id))
    user_id_map: dict[str, str] = {r[0]: r[1] for r in user_res.all()}

    coll_res  = await session.execute(select(Collection.name, Collection.id))
    coll_id_map: dict[str, str] = {r[0]: r[1] for r in coll_res.all()}

    from src.models.team import Team
    team_res  = await session.execute(select(Team.name, Team.id))
    team_id_map: dict[str, str] = {r[0]: r[1] for r in team_res.all()}

    from src.models.document import Document as Doc
    existing_res = await session.execute(select(Doc.filename))
    existing_filenames: set[str] = {r[0] for r in existing_res.all()}

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    base_ts = datetime(2025, 4, 1, 9, 0, tzinfo=timezone.utc)
    created = skipped = 0
    doc_id_map: dict[str, str] = {}

    for i, ddata in enumerate(DOCUMENTS):
        fname = ddata["filename"]

        if fname in existing_filenames:
            skipped += 1
            ex = await session.execute(select(Doc.id).where(Doc.filename == fname))
            row = ex.scalar_one_or_none()
            if row:
                doc_id_map[fname] = row
            continue

        owner_id = user_id_map.get(ddata["owner"])
        coll_id  = coll_id_map.get(ddata["collection"])
        if not owner_id:
            print(f"  [warn] owner '{ddata['owner']}' missing, skipping '{fname}'")
            continue

        doc_id   = str(uuid.uuid4())
        dest_dir = UPLOAD_DIR / doc_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest     = dest_dir / fname
        content  = DOC_CONTENT.get(fname, f"# {fname}\n\nContent pending.\n")
        dest.write_text(content, encoding="utf-8")

        doc = Doc(
            id=doc_id,
            filename=fname,
            file_type=".md",
            file_size=len(content.encode("utf-8")),
            visibility=ddata["visibility"],
            collection_id=coll_id,
            owner_id=owner_id,
            chunk_count=0,
            chunking_strategy="hierarchical",
            file_path=str(dest),
            status=ddata["status"],
            created_at=base_ts + timedelta(days=i),
            updated_at=base_ts + timedelta(days=i),
        )
        session.add(doc)
        doc_id_map[fname] = doc_id

        for team_name in ddata["team_access"]:
            tid = team_id_map.get(team_name)
            if tid:
                dta = DocumentTeamAccess(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    team_id=tid,
                )
                session.add(dta)

        created += 1

    await session.flush()

    summary = f"{created} created"
    if skipped:
        summary += f", {skipped} skipped"
    print(f"  [documents]   {summary}  (files → {UPLOAD_DIR})")
    return doc_id_map


# ── Phase 5: RAG Ingestion ────────────────────────────────────────────────────

async def seed_ingestion(settings) -> None:
    """Chunk → embed → store all ready documents that haven't been ingested yet.

    Requires Ollama running with the configured embedding model pulled.
    Skip with --skip-embeddings flag.
    """
    from src.models.document import Document, DocumentTeamAccess
    from src.repositories.document_repository import DocumentRepository
    from src.repositories.audit_repository import AuditRepository
    from src.services.embedding_service import OllamaEmbeddingService
    from src.services.ingestion_service import IngestionService
    from src.vectorstore import get_vector_store
    from src.llm import get_llm
    from src.services.knowledge_graph_service import get_kg_service

    engine  = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    embedding_svc = OllamaEmbeddingService(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    vector_store = get_vector_store(settings)
    llm = get_llm(settings)
    kg_svc = get_kg_service(settings)

    needs_llm = (
        getattr(settings, "CONTEXTUAL_RETRIEVAL_ENABLED", False)
        or getattr(settings, "KNOWLEDGE_GRAPH_ENABLED", False)
        or getattr(settings, "AUTO_TAGGING_ENABLED", False)
    )

    try:
        await embedding_svc.embed_text("ping")
    except Exception as e:
        print(f"  [skip] Ollama not reachable ({e}). Run with --skip-embeddings to skip Phase 5.")
        await engine.dispose()
        return

    async with factory() as session:
        result = await session.execute(
            select(Document).where(
                Document.status == "ready",
                Document.chunk_count == 0,
                Document.file_path.is_not(None),
            )
        )
        docs = list(result.scalars().all())

        doc_team_ids: dict[str, list[str]] = {}
        for doc in docs:
            ta_result = await session.execute(
                select(DocumentTeamAccess.team_id).where(
                    DocumentTeamAccess.document_id == doc.id
                )
            )
            doc_team_ids[doc.id] = [r[0] for r in ta_result.all()]

    if not docs:
        print("  [ingestion]   nothing to ingest (all docs already embedded or not ready)")
        await engine.dispose()
        return

    print(f"  [ingestion]   {len(docs)} documents to ingest ...")

    success = failed = 0
    for i, doc in enumerate(docs, 1):
        async with factory() as session:
            doc_repo   = DocumentRepository(session)
            audit_repo = AuditRepository(session)
            svc = IngestionService(
                document_repo=doc_repo,
                audit_repo=audit_repo,
                embedding_service=embedding_svc,
                vector_store=vector_store,
                settings=settings,
                llm=llm if needs_llm else None,
                kg_service=kg_svc,
            )

            visibility_meta = {
                "owner_id":          doc.owner_id,
                "filename":          doc.filename,
                "visibility":        doc.visibility,
                "chunking_strategy": doc.chunking_strategy or "hierarchical",
                "collection_id":     doc.collection_id or "",
                "allowed_teams":     doc_team_ids.get(doc.id, []),
                "allowed_users":     [],
            }

            try:
                await svc.ingest_document(
                    document_id=doc.id,
                    file_path=doc.file_path,
                    file_type=doc.file_type,
                    visibility_metadata=visibility_meta,
                )
                await session.commit()
                success += 1
                print(f"  [{i:>2}/{len(docs)}] ✓  {doc.filename}")
            except Exception as e:
                await session.rollback()
                failed += 1
                print(f"  [{i:>2}/{len(docs)}] ✗  {doc.filename}  ({e})")

    await engine.dispose()
    print(f"  [ingestion]   done — {success} succeeded, {failed} failed")


# ── Phase 6: Channels & Messages ─────────────────────────────────────────────

def _rand_ts(days_back: int = 180) -> datetime:
    """Random UTC timestamp within the last N days."""
    offset = timedelta(
        days=random.randint(0, days_back),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    return datetime.now(timezone.utc) - offset


def _make_messages(channel_id: str, senders: list[tuple[str, str]], pool_key: str, count: int) -> list[ChatMessage]:
    """Generate `count` ChatMessage objects drawn from MSGS[pool_key]."""
    pool = MSGS.get(pool_key, MSGS["GENERAL"])
    msgs = []
    for _ in range(count):
        sender_id, sender_username = random.choice(senders)
        msgs.append(ChatMessage(
            id=str(uuid.uuid4()),
            channel_id=channel_id,
            sender_id=sender_id,
            sender_username=sender_username,
            content=random.choice(pool),
            created_at=_rand_ts(),
        ))
    return msgs


async def seed_channels_messages(session) -> None:
    """Create public, group, and DM channels with members and messages."""
    user_res  = await session.execute(select(User.username, User.id))
    user_rows = user_res.all()
    uid_map: dict[str, str] = {r[0]: r[1] for r in user_rows}

    dept_map: dict[str, list[tuple[str, str]]] = {}
    for username, _title, dept, _role in USERS:
        uid = uid_map.get(username)
        if not uid:
            continue
        dept_map.setdefault(dept, []).append((uid, username))
        dept_map.setdefault("all", []).append((uid, username))

    team_res = await session.execute(select(Team.name, Team.id))
    team_id_map: dict[str, str] = {r[0]: r[1] for r in team_res.all()}

    from src.models.team import TeamMembership as TM
    tm_res = await session.execute(select(TM.team_id, TM.user_id))
    team_members: dict[str, list[tuple[str, str]]] = {}
    for team_id, user_id in tm_res.all():
        uname = next((u for u, i in uid_map.items() if i == user_id), user_id)
        team_members.setdefault(team_id, []).append((user_id, uname))

    existing_res = await session.execute(select(Channel.name))
    existing_names: set[str] = {r[0] for r in existing_res.all()}

    total_channels = total_members = total_messages = 0

    # ── 1. Public channels ─────────────────────────────────────────────────────
    for cdata in PUBLIC_CHANNELS:
        if cdata["name"] in existing_names:
            continue

        filter_ = cdata["dept_filter"]
        if filter_ == "all":
            members = dept_map.get("all", [])
        else:
            members = []
            seen_uids: set[str] = set()
            for dept in filter_:
                for pair in dept_map.get(dept, []):
                    if pair[0] not in seen_uids:
                        members.append(pair)
                        seen_uids.add(pair[0])

        creator_id = members[0][0] if members else None
        ch = Channel(
            id=str(uuid.uuid4()),
            name=cdata["name"],
            type="public",
            created_by=creator_id,
            created_at=datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc),
        )
        session.add(ch)
        await session.flush()

        for uid, _ in members:
            session.add(ChannelMember(channel_id=ch.id, user_id=uid,
                                      joined_at=datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc)))

        for msg in _make_messages(ch.id, members, cdata["pool"], cdata["msg_count"]):
            session.add(msg)

        total_channels += 1
        total_members  += len(members)
        total_messages += cdata["msg_count"]

    # ── 2. Group channels (one per team) ──────────────────────────────────────
    team_channel_names = {
        "Clinical Engineering":         "clinical-engineering-team",
        "Data & Analytics":             "data-analytics-team",
        "Product — Patient Experience": "product-patient-exp",
        "Compliance & Regulatory":      "compliance-team",
        "Customer Success — Hospitals": "hospital-success-team",
    }
    group_pool_map = {
        "clinical-engineering-team": "ENG",
        "data-analytics-team":       "CLINICAL",
        "product-patient-exp":       "GENERAL",
        "compliance-team":           "COMPLIANCE",
        "hospital-success-team":     "GENERAL",
    }

    for team_name, ch_name in team_channel_names.items():
        if ch_name in existing_names:
            continue
        tid = team_id_map.get(team_name)
        if not tid:
            continue
        members = team_members.get(tid, [])
        if not members:
            continue

        ch = Channel(
            id=str(uuid.uuid4()),
            name=ch_name,
            type="group",
            team_id=tid,
            created_by=members[0][0],
            created_at=datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc),
        )
        session.add(ch)
        await session.flush()

        for uid, _ in members:
            session.add(ChannelMember(channel_id=ch.id, user_id=uid,
                                      joined_at=datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)))

        msg_count = random.randint(40, 80)
        for msg in _make_messages(ch.id, members, group_pool_map[ch_name], msg_count):
            session.add(msg)

        total_channels += 1
        total_members  += len(members)
        total_messages += msg_count

    # ── 3. DM channels ────────────────────────────────────────────────────────
    for u1, u2 in DM_PAIRS:
        dm_name = "-".join(sorted([u1, u2]))
        if dm_name in existing_names:
            continue
        uid1 = uid_map.get(u1)
        uid2 = uid_map.get(u2)
        if not uid1 or not uid2:
            continue

        ch = Channel(
            id=str(uuid.uuid4()),
            name=dm_name,
            type="dm",
            created_by=uid1,
            created_at=_rand_ts(days_back=180),
        )
        session.add(ch)
        await session.flush()

        session.add(ChannelMember(channel_id=ch.id, user_id=uid1, joined_at=ch.created_at))
        session.add(ChannelMember(channel_id=ch.id, user_id=uid2, joined_at=ch.created_at))

        msg_count = random.randint(*DM_MSG_COUNT)
        senders = [(uid1, u1), (uid2, u2)]
        for msg in _make_messages(ch.id, senders, "DM", msg_count):
            session.add(msg)

        total_channels += 1
        total_members  += 2
        total_messages += msg_count

    await session.flush()
    print(f"  [channels]    {total_channels} channels ({len(PUBLIC_CHANNELS)} public, {len(team_channel_names)} group, {len(DM_PAIRS)} DM)")
    print(f"  [members]     {total_members} channel memberships")
    print(f"  [messages]    ~{total_messages} chat messages")


# ── Phase 7: Calendar ────────────────────────────────────────────────────────

_DAILY_STANDUP_ATTENDEES = [
    "james.wright", "raj.kumar", "lisa.chen", "david.brooks",
    "alex.torres", "jessica.lane", "sarah.nguyen", "diana.okafor",
    "marcus.hayes",
]
_CLINICAL_SYNC_ATTENDEES = [
    "dr.emily.chen", "priya.sharma", "kevin.walsh", "rachel.kim",
    "nurse.amy.park", "nurse.carlos.vega", "coord.ben.foster",
    "coord.mia.santos", "omar.farid",
]
_ENG_SYNC_ATTENDEES = [
    "james.wright", "raj.kumar", "lisa.chen", "david.brooks",
    "alex.torres", "jessica.lane", "support.anna.beck",
]
_SPRINT_ATTENDEES = list({
    *_DAILY_STANDUP_ATTENDEES,
    "tom.bradley", "nina.patel",
})
_ALL_HANDS_ATTENDEES = [u for u, *_ in USERS]

RECURRING_EVENTS = [
    {
        "title": "Engineering Daily Standup",
        "description": "15-minute daily sync: what shipped yesterday, today's focus, and any blockers. PHI systems status included.",
        "organizer": "james.wright",
        "cadence": "daily_weekday",
        "hour": 9, "minute": 0, "duration_mins": 15,
        "attendees": _DAILY_STANDUP_ATTENDEES,
        "room_name_prefix": None,
    },
    {
        "title": "Weekly Clinical Sync",
        "description": "Weekly review of clinical workflows, EHR integration status, patient safety concerns, and product feedback from nursing staff.",
        "organizer": "dr.emily.chen",
        "cadence": "weekly", "weekday": 1,
        "hour": 10, "minute": 0, "duration_mins": 60,
        "attendees": _CLINICAL_SYNC_ATTENDEES,
        "room_name_prefix": None,
    },
    {
        "title": "Weekly Engineering Sync",
        "description": "Weekly engineering deep-dive: PR reviews, architecture decisions, on-call debrief, and security updates.",
        "organizer": "james.wright",
        "cadence": "weekly", "weekday": 3,
        "hour": 11, "minute": 0, "duration_mins": 60,
        "attendees": _ENG_SYNC_ATTENDEES,
        "room_name_prefix": None,
    },
    {
        "title": "Bi-Weekly Sprint Planning",
        "description": "Sprint planning: pull issues from backlog, estimate, assign owners, and commit to sprint goals for the next two weeks.",
        "organizer": "james.wright",
        "cadence": "biweekly", "weekday": 0, "week_parity": 0,
        "hour": 13, "minute": 0, "duration_mins": 90,
        "attendees": _SPRINT_ATTENDEES,
        "room_name_prefix": None,
    },
    {
        "title": "Monthly All-Hands — HealthFlow",
        "description": "Company all-hands: product updates, clinical metrics, compliance status, customer wins, and Q&A with leadership.",
        "organizer": "dr.emily.chen",
        "cadence": "monthly_first_friday",
        "hour": 14, "minute": 0, "duration_mins": 90,
        "attendees": _ALL_HANDS_ATTENDEES,
        "room_name_prefix": "all-hands-healthflow",
    },
]


def _rsvp_status(username: str, organizer: str) -> str:
    """Organizer always accepted; others weighted random."""
    if username == organizer:
        return "accepted"
    r = random.random()
    if r < 0.70:
        return "accepted"
    if r < 0.85:
        return "pending"
    return "declined"


def _expand_recurring(edef: dict, window_start: datetime, window_end: datetime) -> list[dict]:
    """Expand a recurring event definition into a list of (start, end) datetime pairs."""
    instances = []
    cadence = edef["cadence"]
    h, m   = edef["hour"], edef["minute"]
    dur    = timedelta(minutes=edef["duration_mins"])
    cursor = window_start

    if cadence == "daily_weekday":
        while cursor <= window_end:
            if cursor.weekday() < 5:
                start = cursor.replace(hour=h, minute=m, second=0, microsecond=0)
                instances.append((start, start + dur))
            cursor += timedelta(days=1)

    elif cadence == "weekly":
        wd = edef["weekday"]
        days_ahead = (wd - cursor.weekday()) % 7
        cursor += timedelta(days=days_ahead)
        while cursor <= window_end:
            start = cursor.replace(hour=h, minute=m, second=0, microsecond=0)
            instances.append((start, start + dur))
            cursor += timedelta(weeks=1)

    elif cadence == "biweekly":
        wd = edef["weekday"]
        parity = edef.get("week_parity", 0)
        days_ahead = (wd - cursor.weekday()) % 7
        cursor += timedelta(days=days_ahead)
        week_num = 0
        while cursor <= window_end:
            if week_num % 2 == parity:
                start = cursor.replace(hour=h, minute=m, second=0, microsecond=0)
                instances.append((start, start + dur))
            cursor += timedelta(weeks=1)
            week_num += 1

    elif cadence == "monthly_first_friday":
        y, mo = window_start.year, window_start.month
        while True:
            d = datetime(y, mo, 1, h, m, tzinfo=timezone.utc)
            while d.weekday() != 4:
                d += timedelta(days=1)
            if d > window_end:
                break
            if d >= window_start:
                instances.append((d, d + dur))
            mo += 1
            if mo > 12:
                mo = 1
                y += 1

    return instances


async def seed_calendar(session) -> None:
    """Create recurring calendar events with attendees."""
    user_res = await session.execute(select(User.username, User.id))
    uid_map: dict[str, str] = {r[0]: r[1] for r in user_res.all()}

    existing_res = await session.execute(
        select(CalendarEvent.title, CalendarEvent.start_time)
    )
    existing_keys: set[tuple] = {(r[0], r[1]) for r in existing_res.all()}

    WINDOW_START = datetime(2026, 1, 20, tzinfo=timezone.utc)
    WINDOW_END   = datetime(2026, 3, 28, tzinfo=timezone.utc)

    total_events = total_attendees = 0

    def _add_event(title, desc, organizer_uname, start, end, attendee_names, room=None):
        nonlocal total_events, total_attendees
        key = (title, start)
        if key in existing_keys:
            return
        oid = uid_map.get(organizer_uname)
        if not oid:
            return
        ev = CalendarEvent(
            id=str(uuid.uuid4()),
            title=title,
            description=desc,
            start_time=start,
            end_time=end,
            created_by=oid,
            creator_username=organizer_uname,
            room_name=room,
            created_at=start - timedelta(days=random.randint(1, 7)),
        )
        session.add(ev)
        seen: set[str] = set()
        for uname in attendee_names:
            if uname in seen:
                continue
            seen.add(uname)
            auid = uid_map.get(uname)
            if not auid:
                continue
            session.add(EventAttendee(
                event_id=ev.id,
                user_id=auid,
                username=uname,
                status=_rsvp_status(uname, organizer_uname),
            ))
            total_attendees += 1
        total_events += 1

    for edef in RECURRING_EVENTS:
        room_prefix = edef.get("room_name_prefix")
        for start, end in _expand_recurring(edef, WINDOW_START, WINDOW_END):
            room = f"{room_prefix}-{start.strftime('%Y-%m-%d')}" if room_prefix else None
            _add_event(
                edef["title"], edef["description"],
                edef["organizer"], start, end,
                edef["attendees"], room,
            )

    await session.flush()
    print(f"  [calendar]    {total_events} events, {total_attendees} attendee rows")


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    settings = get_settings()
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    async with factory() as session:
        # Idempotency check
        result = await session.execute(
            select(User).where(User.username == COMPANY["sentinel_username"])
        )
        if result.scalar_one_or_none():
            print(f"[seed] Already seeded (found '{COMPANY['sentinel_username']}'). Use --reset to re-seed.")
            await engine.dispose()
            return

        print(f"[seed] Seeding {COMPANY['name']}")

        # Phase 0 — Company record
        print("[seed] Phase 0: Company")
        company_id = await seed_company(session)
        await session.commit()

        # Phase 1 — Foundation
        print("[seed] Phase 1: Foundation")
        perm_map = await seed_permissions(session)
        print(f"  [permissions] {len(perm_map)} permissions ensured")
        role_map = await seed_role_permissions(session, perm_map)
        print(f"  [roles]       {len(role_map)} roles linked to permissions")
        await seed_users(session, role_map, company_id)
        await session.commit()

        # Phase 2 — Teams
        print("[seed] Phase 2: Teams & memberships")
        await seed_teams(session, company_id)
        await session.commit()

        # Phase 3 — Collections
        print("[seed] Phase 3: Collections")
        await seed_collections(session, company_id)
        await session.commit()

        # Phase 4 — Documents
        print("[seed] Phase 4: Documents")
        await seed_documents(session)
        await session.commit()

    await engine.dispose()

    # Phase 5 — RAG Ingestion (outside the main session — opens per-doc sessions)
    if "--skip-embeddings" in sys.argv:
        print("[seed] Phase 5: Skipped (--skip-embeddings)")
    else:
        print("[seed] Phase 5: RAG Ingestion")
        await seed_ingestion(settings)

    # Phase 6 — Channels & Messages (new session after ingestion)
    engine2  = get_async_engine(settings.DATABASE_URL)
    factory2 = get_session_factory(engine2)
    async with factory2() as session:
        print("[seed] Phase 6: Channels & messages")
        await seed_channels_messages(session)
        await session.commit()

        print("[seed] Phase 7: Calendar events")
        await seed_calendar(session)
        await session.commit()

    await engine2.dispose()

    print()
    print("[seed] All phases complete (0–7).")
    print(f"       Admin login:  dr.emily.chen@{COMPANY['domain']} / {COMPANY['admin_password']}")
    print(f"       Admin login:  james.wright@{COMPANY['domain']} / {COMPANY['admin_password']}")
    print(f"       All users:    <username>@{COMPANY['domain']} / {COMPANY['user_password']}")


async def reset_data(settings) -> None:
    """Wipe all HealthFlow tenant data so the script can be re-run cleanly.

    Deletes rows in dependency order (children before parents) to avoid FK
    constraint violations. Roles and permissions are left intact — they are
    global and not tenant-specific.
    """
    from sqlalchemy import text

    engine = get_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        tables_ordered = [
            # Calendar
            "event_attendees",
            "calendar_events",
            # Chat
            "chat_messages",
            "channel_reads",
            "channel_members",
            "channels",
            # Documents / collections
            "document_team_access",
            "documents",
            "collections",
            # Teams
            "team_memberships",
            "teams",
            # Users (last — everything else refs users)
            "users",
        ]

        deleted_totals = {}
        for table in tables_ordered:
            try:
                result = await conn.execute(text(f"DELETE FROM {table}"))
                deleted_totals[table] = result.rowcount
            except Exception as exc:
                print(f"  [reset] WARNING: could not clear {table}: {exc}")

    await engine.dispose()

    total = sum(deleted_totals.values())
    print(f"[reset] Wiped {total} rows across {len(tables_ordered)} tables.")

    upload_dir = Path(__file__).resolve().parent.parent / "data" / "uploads" / "company_two"
    if upload_dir.exists():
        import shutil
        shutil.rmtree(upload_dir)
        print(f"[reset] Removed {upload_dir}")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        async def _do_reset():
            settings = get_settings()
            print(f"[reset] Wiping all HealthFlow data from {settings.DATABASE_URL} ...")
            await reset_data(settings)
            print("[reset] Done. Run the script again (without --reset) to re-seed.")
        asyncio.run(_do_reset())
    else:
        asyncio.run(main())
