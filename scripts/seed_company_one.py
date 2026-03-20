"""Seed script for Company One (TechCorp Inc.) — Nexus Enterprise RAG.

Run phases incrementally:
  python scripts/seed_company_one.py             # Phase 1 only (current)
  python scripts/seed_company_one.py --reset     # Wipe TechCorp users and re-seed

Prerequisites:
  - Backend started at least once (tables must exist)
  - python scripts/seed_users.py NOT required — this script is self-contained
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
    "name": "TechCorp Inc.",
    "slug": "techcorp",
    "domain": "techcorp.io",
    "admin_password": "TechCorp2026!",
    "user_password": "TechCorp2026!",
    "sentinel_username": "alex.foster",   # idempotency check
}

# ── 100 users: (username, title, department, role) ────────────────────────────

USERS = [
    # ── 3 admins ──────────────────────────────────────────────────────────────
    ("alex.foster",      "CEO",                    "Executive",        "admin"),
    ("sarah.chen",       "VP Engineering",         "Engineering",      "admin"),
    ("it.admin",         "IT Admin",               "IT",               "admin"),

    # ── 45 analysts ───────────────────────────────────────────────────────────
    # Executive
    ("marcus.williams",  "CPO",                    "Product",          "analyst"),
    ("diana.rodriguez",  "VP Sales",               "Sales",            "analyst"),
    ("james.park",       "CMO",                    "Marketing",        "analyst"),
    ("priya.patel",      "VP Customer Success",    "Customer Success", "analyst"),
    ("rachel.thompson",  "CHRO",                   "HR",               "analyst"),
    ("kevin.obrien",     "CFO",                    "Finance",          "analyst"),
    # Engineering
    ("aisha.johnson",    "Head of Data",           "Analytics",        "analyst"),
    ("nina.kowalski",    "Design Lead",            "Design",           "analyst"),
    ("liam.nguyen",      "Staff Engineer",         "Engineering",      "analyst"),
    ("elena.kovar",      "Sr Backend Engineer",    "Engineering",      "analyst"),
    ("mia.carter",       "Sr Frontend Engineer",   "Engineering",      "analyst"),
    ("josh.banks",       "DevOps Engineer",        "Engineering",      "analyst"),
    ("priya.mehta",      "Sr Engineer",            "Engineering",      "analyst"),
    ("oscar.lindqvist",  "Staff Engineer",         "Engineering",      "analyst"),
    ("tara.okafor",      "Backend Engineer",       "Engineering",      "analyst"),
    ("felix.braun",      "DevOps Lead",            "Engineering",      "analyst"),
    ("zoe.harper",       "Frontend Engineer",      "Engineering",      "analyst"),
    ("ryan.oconnell",    "Backend Engineer",       "Engineering",      "analyst"),
    ("alex.wu",          "Tech Lead",              "Engineering",      "analyst"),
    # Product
    ("emily.davis",      "Sr Product Manager",     "Product",          "analyst"),
    ("chloe.martin",     "Product Manager",        "Product",          "analyst"),
    ("nat.turner",       "Growth PM",              "Product",          "analyst"),
    # Sales
    ("carlos.martinez",  "Account Executive",      "Sales",            "analyst"),
    ("fiona.brooks",     "Sr Account Executive",   "Sales",            "analyst"),
    ("hassan.ali",       "Account Executive",      "Sales",            "analyst"),
    ("ingrid.berg",      "Account Executive",      "Sales",            "analyst"),
    ("javier.luna",      "Enterprise AE",          "Sales",            "analyst"),
    ("kate.young",       "SDR",                    "Sales",            "analyst"),
    ("lucas.ford",       "Solutions Engineer",     "Sales",            "analyst"),
    # Marketing
    ("julia.smith",      "Content Manager",        "Marketing",        "analyst"),
    ("ivan.petrov",      "Growth Marketer",        "Marketing",        "analyst"),
    ("helen.zhao",       "Brand Manager",          "Marketing",        "analyst"),
    # Customer Success
    ("david.kim",        "CS Manager",             "Customer Success", "analyst"),
    ("elsa.moore",       "CS Specialist",          "Customer Success", "analyst"),
    ("fred.jackson",     "CS Engineer",            "Customer Success", "analyst"),
    # HR
    ("sam.davies",       "HR Business Partner",    "HR",               "analyst"),
    # Finance
    ("wendy.foster",     "Financial Analyst",      "Finance",          "analyst"),
    # Analytics
    ("raj.patel",        "Data Engineer",          "Analytics",        "analyst"),
    ("boris.petrov",     "Data Scientist",         "Analytics",        "analyst"),
    ("carmen.silva",     "Sr Data Analyst",        "Analytics",        "analyst"),
    ("derek.hunt",       "ML Engineer",            "Analytics",        "analyst"),
    # Design
    ("abby.foster",      "Sr Designer",            "Design",           "analyst"),
    ("ben.santos",       "UX Designer",            "Design",           "analyst"),

    # ── 52 viewers ────────────────────────────────────────────────────────────
    # Engineering
    ("jade.harris",      "Jr Engineer",            "Engineering",      "viewer"),
    ("noah.kim",         "Jr Engineer",            "Engineering",      "viewer"),
    ("lily.zhang",       "Jr Frontend Engineer",   "Engineering",      "viewer"),
    ("sam.petrov",       "Jr Engineer",            "Engineering",      "viewer"),
    ("chris.moore",      "Jr DevOps",              "Engineering",      "viewer"),
    ("dana.walsh",       "Jr Engineer",            "Engineering",      "viewer"),
    ("leo.santos",       "Jr Backend Engineer",    "Engineering",      "viewer"),
    ("bella.ross",       "Jr Frontend Engineer",   "Engineering",      "viewer"),
    ("theo.patel",       "QA Engineer",            "Engineering",      "viewer"),
    ("mike.chen",        "Jr Engineer",            "Engineering",      "viewer"),
    ("paul.reed",        "Jr DevOps",              "Engineering",      "viewer"),
    # Product
    ("leo.nguyen",       "Jr Product Manager",     "Product",          "viewer"),
    ("iris.schmidt",     "Business Analyst",       "Product",          "viewer"),
    ("ben.wright",       "Product Analyst",        "Product",          "viewer"),
    ("amy.liu",          "UX Researcher",          "Design",           "viewer"),
    ("jake.cooper",      "Product Coordinator",    "Product",          "viewer"),
    # Sales
    ("mia.johnson",      "SDR",                    "Sales",            "viewer"),
    ("nadia.petrov",     "Sales Coordinator",      "Sales",            "viewer"),
    ("omar.farouk",      "Sales Analyst",          "Sales",            "viewer"),
    ("penny.shaw",       "Sales Ops",              "Sales",            "viewer"),
    ("quinn.taylor",     "BDR",                    "Sales",            "viewer"),
    ("rick.vasquez",     "Sales Engineer",         "Sales",            "viewer"),
    # Marketing
    ("sofia.lee",        "Content Writer",         "Marketing",        "viewer"),
    ("sue.chen",         "Marketing Coordinator",  "Marketing",        "viewer"),
    ("tim.davidson",     "Marketing Analyst",      "Marketing",        "viewer"),
    ("uma.patel",        "Social Media Manager",   "Marketing",        "viewer"),
    ("val.brooks",       "SEO Specialist",         "Marketing",        "viewer"),
    ("ken.brown",        "Marketing Ops",          "Marketing",        "viewer"),
    # Customer Success
    ("linda.garcia",     "CS Coordinator",         "Customer Success", "viewer"),
    ("mary.wilson",      "Support Specialist",     "Customer Success", "viewer"),
    ("ned.jones",        "Customer Onboarding",    "Customer Success", "viewer"),
    ("olivia.taylor",    "Account Manager",        "Customer Success", "viewer"),
    ("paul.adams",       "Renewals Specialist",    "Customer Success", "viewer"),
    ("gwen.lewis",       "CS Representative",      "Customer Success", "viewer"),
    ("jan.white",        "CS Representative",      "Customer Success", "viewer"),
    ("kyle.thomas",      "CS Representative",      "Customer Success", "viewer"),
    # HR
    ("jessica.white",    "Recruiter",              "HR",               "viewer"),
    ("hank.miller",      "Talent Acquisition",     "HR",               "viewer"),
    ("iris.johnson",     "HR Generalist",          "HR",               "viewer"),
    # Finance
    ("tom.harris",       "Controller",             "Finance",          "viewer"),
    ("xavier.hall",      "Accounts Payable",       "Finance",          "viewer"),
    ("yvonne.king",      "Legal Counsel",          "Finance",          "viewer"),
    ("zach.scott",       "Financial Analyst",      "Finance",          "viewer"),
    # Analytics
    ("eve.morgan",       "Data Analyst",           "Analytics",        "viewer"),
    ("frank.zhang",      "BI Analyst",             "Analytics",        "viewer"),
    ("gabby.harris",     "Data Coordinator",       "Analytics",        "viewer"),
    ("harry.chen",       "Data Ops",               "Analytics",        "viewer"),
    # Design
    ("anna.schmidt",     "Sr Designer",            "Design",           "viewer"),
    ("cate.williams",    "Jr Designer",            "Design",           "viewer"),
    ("dan.murphy",       "Visual Designer",        "Design",           "viewer"),
    ("ella.park",        "Design Coordinator",     "Design",           "viewer"),
    ("finn.turner",      "Graphic Designer",       "Design",           "viewer"),
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
# Every user appears in at least one team (no orphans).

TEAMS = [
    {
        "name": "Engineering — Backend",
        "description": "Owns Python/FastAPI services, database design, and backend infrastructure. Responsible for API reliability, performance, and security.",
        "created_by": "sarah.chen",
        "members": [
            "sarah.chen", "liam.nguyen", "elena.kovar", "priya.mehta",
            "oscar.lindqvist", "tara.okafor", "ryan.oconnell", "alex.wu",
            "mike.chen", "dana.walsh", "it.admin",
        ],
    },
    {
        "name": "Engineering — Frontend",
        "description": "Owns the Next.js frontend, design system, and browser performance. Partners closely with Design and Product.",
        "created_by": "sarah.chen",
        "members": [
            "sarah.chen", "mia.carter", "zoe.harper", "lily.zhang",
            "jade.harris", "noah.kim", "bella.ross", "theo.patel",
            "anna.schmidt", "cate.williams", "ella.park",
        ],
    },
    {
        "name": "Engineering — DevOps",
        "description": "Manages CI/CD pipelines, Kubernetes clusters, and monitoring infrastructure. On-call for infrastructure incidents.",
        "created_by": "sarah.chen",
        "members": [
            "sarah.chen", "josh.banks", "felix.braun", "chris.moore",
            "sam.petrov", "paul.reed", "leo.santos",
        ],
    },
    {
        "name": "Product — Core",
        "description": "Drives the core product roadmap, prioritization, and feature specs. Works cross-functionally with Engineering, Design, and Sales.",
        "created_by": "marcus.williams",
        "members": [
            "marcus.williams", "emily.davis", "chloe.martin",
            "leo.nguyen", "iris.schmidt", "nina.kowalski",
            "abby.foster", "ben.santos", "ethan.bailey",
            "raj.patel", "aisha.johnson",
        ],
    },
    {
        "name": "Product — Growth",
        "description": "Owns user onboarding, activation, and retention metrics. Runs A/B tests and growth experiments.",
        "created_by": "marcus.williams",
        "members": [
            "marcus.williams", "nat.turner", "jake.cooper",
            "helen.zhao", "amy.liu", "ben.wright",
        ],
    },
    {
        "name": "Sales — Enterprise",
        "description": "Manages enterprise accounts ($100K+ ACV). Owns the full deal cycle from discovery to close.",
        "created_by": "diana.rodriguez",
        "members": [
            "diana.rodriguez", "fiona.brooks", "javier.luna", "lucas.ford",
            "hassan.ali", "rick.vasquez", "ingrid.berg", "omar.farouk",
        ],
    },
    {
        "name": "Sales — SMB",
        "description": "High-velocity SMB sales (<$50K ACV). Manages pipeline volume, trial conversions, and renewals.",
        "created_by": "diana.rodriguez",
        "members": [
            "diana.rodriguez", "carlos.martinez", "kate.young", "ingrid.berg",
            "mia.johnson", "nadia.petrov", "penny.shaw", "quinn.taylor",
            "hassan.ali", "carlos.martinez",
        ],
    },
    {
        "name": "Marketing — Content",
        "description": "Produces blog posts, documentation, case studies, and SEO content. Manages the company content calendar.",
        "created_by": "james.park",
        "members": [
            "james.park", "julia.smith", "sofia.lee", "sue.chen",
            "tim.davidson", "uma.patel", "val.brooks",
        ],
    },
    {
        "name": "Marketing — Demand Gen",
        "description": "Runs paid campaigns, events, and pipeline generation. Owns MQL targets and marketing attribution.",
        "created_by": "james.park",
        "members": [
            "james.park", "ivan.petrov", "helen.zhao", "val.brooks",
            "ken.brown", "tim.davidson",
        ],
    },
    {
        "name": "Customer Success",
        "description": "Owns customer onboarding, health scores, renewals, and expansion. Bridges product and customers.",
        "created_by": "priya.patel",
        "members": [
            "priya.patel", "david.kim", "elsa.moore", "fred.jackson",
            "linda.garcia", "mary.wilson", "ned.jones", "olivia.taylor",
            "paul.adams", "gwen.lewis", "jan.white", "kyle.thomas",
        ],
    },
    {
        "name": "Finance & Legal",
        "description": "Manages budget planning, financial reporting, vendor contracts, and legal compliance.",
        "created_by": "kevin.obrien",
        "members": [
            "kevin.obrien", "wendy.foster", "tom.harris", "xavier.hall",
            "yvonne.king", "zach.scott",
            "rachel.thompson", "sam.davies", "jessica.white",
            "hank.miller", "iris.johnson",
        ],
    },
    {
        "name": "Executive Leadership",
        "description": "C-suite and senior leadership. Sets company strategy, OKRs, and cross-functional priorities.",
        "created_by": "alex.foster",
        "members": [
            "alex.foster", "sarah.chen", "marcus.williams", "diana.rodriguez",
            "kevin.obrien", "james.park", "priya.patel", "rachel.thompson",
            "aisha.johnson",
            # Analytics team members — report to aisha.johnson
            "boris.petrov", "carmen.silva", "derek.hunt",
            "eve.morgan", "frank.zhang", "gabby.harris", "harry.chen",
            # Design members not already covered
            "dan.murphy", "finn.turner",
        ],
    },
]


# ── Collections: name, description, owner, is_public ─────────────────────────

COLLECTIONS = [
    {
        "name": "HR & People Ops",
        "description": "All HR policies, employee guides, onboarding templates, and people operations documents.",
        "owner": "rachel.thompson",
        "is_public": False,
    },
    {
        "name": "Engineering Docs",
        "description": "Technical specifications, architecture runbooks, incident postmortems, and infrastructure guides.",
        "owner": "sarah.chen",
        "is_public": False,
    },
    {
        "name": "Product & Design",
        "description": "Product roadmaps, feature specs, user research reports, and design system guidelines.",
        "owner": "marcus.williams",
        "is_public": False,
    },
    {
        "name": "Sales & Marketing",
        "description": "Sales playbooks, campaign briefs, brand guidelines, proposal templates, and competitive analysis.",
        "owner": "diana.rodriguez",
        "is_public": False,
    },
    {
        "name": "Finance & Legal",
        "description": "Budget reports, vendor contracts, compliance checklists, and legal policy documents.",
        "owner": "kevin.obrien",
        "is_public": False,
    },
]


# ── Documents: 50 docs across 5 collections ──────────────────────────────────
# All written as .md files (StructuralChunker) for Phase 5 ingestion.
# visibility: public | team | confidential
# team_access: list of team names (used when visibility != public)

DOCUMENTS = [
    # ── HR & People Ops (10) ─────────────────────────────────────────────────
    {"filename": "Employee_Handbook_2026.md",         "collection": "HR & People Ops",   "owner": "rachel.thompson", "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Code_of_Conduct.md",                "collection": "HR & People Ops",   "owner": "rachel.thompson", "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Benefits_Guide_2026.md",            "collection": "HR & People Ops",   "owner": "rachel.thompson", "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Performance_Review_Template.md",    "collection": "HR & People Ops",   "owner": "rachel.thompson", "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Onboarding_Checklist.md",           "collection": "HR & People Ops",   "owner": "rachel.thompson", "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Remote_Work_Policy.md",             "collection": "HR & People Ops",   "owner": "rachel.thompson", "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "PTO_and_Leave_Policy.md",           "collection": "HR & People Ops",   "owner": "rachel.thompson", "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Compensation_Bands_2026.md",        "collection": "HR & People Ops",   "owner": "rachel.thompson", "visibility": "confidential",  "status": "flagged", "team_access": []},
    {"filename": "Hiring_Plan_Q1_2026.md",            "collection": "HR & People Ops",   "owner": "rachel.thompson", "visibility": "confidential",  "status": "flagged", "team_access": []},
    {"filename": "Exit_Interview_Template.md",        "collection": "HR & People Ops",   "owner": "rachel.thompson", "visibility": "team",          "status": "ready",   "team_access": ["Finance & Legal"]},
    # ── Engineering Docs (12) ────────────────────────────────────────────────
    {"filename": "System_Architecture_Overview.md",   "collection": "Engineering Docs",  "owner": "sarah.chen",      "visibility": "team",          "status": "ready",   "team_access": ["Engineering — Backend", "Engineering — DevOps"]},
    {"filename": "API_Documentation_v3.md",           "collection": "Engineering Docs",  "owner": "sarah.chen",      "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Database_Schema_Reference.md",      "collection": "Engineering Docs",  "owner": "sarah.chen",      "visibility": "team",          "status": "ready",   "team_access": ["Engineering — Backend"]},
    {"filename": "Security_Policy_and_Procedures.md", "collection": "Engineering Docs",  "owner": "sarah.chen",      "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Incident_Response_Playbook.md",     "collection": "Engineering Docs",  "owner": "sarah.chen",      "visibility": "team",          "status": "ready",   "team_access": ["Engineering — Backend", "Engineering — DevOps"]},
    {"filename": "CI_CD_Pipeline_Guide.md",           "collection": "Engineering Docs",  "owner": "josh.banks",      "visibility": "team",          "status": "ready",   "team_access": ["Engineering — DevOps"]},
    {"filename": "Code_Review_Standards.md",          "collection": "Engineering Docs",  "owner": "sarah.chen",      "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Tech_Debt_Backlog_Q1_2026.md",      "collection": "Engineering Docs",  "owner": "liam.nguyen",     "visibility": "team",          "status": "ready",   "team_access": ["Engineering — Backend"]},
    {"filename": "Infrastructure_Cost_Analysis.md",   "collection": "Engineering Docs",  "owner": "sarah.chen",      "visibility": "confidential",  "status": "ready",   "team_access": []},
    {"filename": "Engineering_OKRs_2026.md",          "collection": "Engineering Docs",  "owner": "sarah.chen",      "visibility": "team",          "status": "ready",   "team_access": ["Engineering — Backend", "Engineering — Frontend", "Engineering — DevOps"]},
    {"filename": "Postmortem_Dec2025_Auth_Outage.md", "collection": "Engineering Docs",  "owner": "sarah.chen",      "visibility": "team",          "status": "ready",   "team_access": ["Engineering — Backend", "Executive Leadership"]},
    {"filename": "Data_Privacy_Compliance_Guide.md",  "collection": "Engineering Docs",  "owner": "sarah.chen",      "visibility": "public",        "status": "ready",   "team_access": []},
    # ── Product & Design (8) ─────────────────────────────────────────────────
    {"filename": "Product_Roadmap_2026.md",           "collection": "Product & Design",  "owner": "marcus.williams", "visibility": "team",          "status": "ready",   "team_access": ["Product — Core", "Executive Leadership"]},
    {"filename": "Q4_2025_Product_Review.md",         "collection": "Product & Design",  "owner": "marcus.williams", "visibility": "team",          "status": "ready",   "team_access": ["Product — Core", "Executive Leadership"]},
    {"filename": "Feature_Spec_DashboardV2.md",       "collection": "Product & Design",  "owner": "emily.davis",     "visibility": "team",          "status": "ready",   "team_access": ["Product — Core", "Engineering — Backend"]},
    {"filename": "User_Research_Report_Jan2026.md",   "collection": "Product & Design",  "owner": "emily.davis",     "visibility": "team",          "status": "ready",   "team_access": ["Product — Core", "Product — Growth"]},
    {"filename": "Design_System_Guidelines.md",       "collection": "Product & Design",  "owner": "nina.kowalski",   "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "AB_Test_Results_Q4_2025.md",        "collection": "Product & Design",  "owner": "nat.turner",      "visibility": "team",          "status": "ready",   "team_access": ["Product — Growth"]},
    {"filename": "Competitive_Analysis_2026.md",      "collection": "Product & Design",  "owner": "marcus.williams", "visibility": "confidential",  "status": "ready",   "team_access": []},
    {"filename": "PRD_NextGen_Analytics.md",          "collection": "Product & Design",  "owner": "emily.davis",     "visibility": "team",          "status": "ready",   "team_access": ["Product — Core", "Engineering — Backend"]},
    # ── Sales & Marketing (12) ───────────────────────────────────────────────
    {"filename": "Sales_Playbook_2026.md",            "collection": "Sales & Marketing", "owner": "diana.rodriguez", "visibility": "team",          "status": "ready",   "team_access": ["Sales — Enterprise", "Sales — SMB"]},
    {"filename": "Ideal_Customer_Profile.md",         "collection": "Sales & Marketing", "owner": "diana.rodriguez", "visibility": "team",          "status": "ready",   "team_access": ["Sales — Enterprise", "Marketing — Demand Gen"]},
    {"filename": "Pricing_Guide_2026.md",             "collection": "Sales & Marketing", "owner": "diana.rodriguez", "visibility": "confidential",  "status": "flagged", "team_access": []},
    {"filename": "Enterprise_Proposal_Template.md",   "collection": "Sales & Marketing", "owner": "fiona.brooks",    "visibility": "team",          "status": "ready",   "team_access": ["Sales — Enterprise"]},
    {"filename": "Objection_Handling_Guide.md",       "collection": "Sales & Marketing", "owner": "diana.rodriguez", "visibility": "team",          "status": "ready",   "team_access": ["Sales — Enterprise", "Sales — SMB"]},
    {"filename": "Q4_2025_Sales_Report.md",           "collection": "Sales & Marketing", "owner": "diana.rodriguez", "visibility": "team",          "status": "ready",   "team_access": ["Sales — Enterprise", "Executive Leadership"]},
    {"filename": "Marketing_Campaign_H1_2026.md",     "collection": "Sales & Marketing", "owner": "james.park",      "visibility": "team",          "status": "ready",   "team_access": ["Marketing — Content", "Marketing — Demand Gen"]},
    {"filename": "Brand_Guidelines_v2.md",            "collection": "Sales & Marketing", "owner": "james.park",      "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "SEO_Content_Strategy_2026.md",      "collection": "Sales & Marketing", "owner": "julia.smith",     "visibility": "team",          "status": "ready",   "team_access": ["Marketing — Content"]},
    {"filename": "Customer_Case_Studies.md",          "collection": "Sales & Marketing", "owner": "james.park",      "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Event_Sponsorship_Plan_2026.md",    "collection": "Sales & Marketing", "owner": "ivan.petrov",     "visibility": "team",          "status": "ready",   "team_access": ["Marketing — Demand Gen"]},
    {"filename": "Lead_Scoring_Model.md",             "collection": "Sales & Marketing", "owner": "aisha.johnson",   "visibility": "team",          "status": "pending", "team_access": ["Sales — SMB"]},
    # ── Finance & Legal (8) ──────────────────────────────────────────────────
    {"filename": "Budget_2026.md",                    "collection": "Finance & Legal",   "owner": "kevin.obrien",    "visibility": "confidential",  "status": "pending", "team_access": []},
    {"filename": "Q4_2025_Financial_Report.md",       "collection": "Finance & Legal",   "owner": "kevin.obrien",    "visibility": "confidential",  "status": "ready",   "team_access": []},
    {"filename": "Vendor_Contracts_Summary.md",       "collection": "Finance & Legal",   "owner": "kevin.obrien",    "visibility": "confidential",  "status": "ready",   "team_access": []},
    {"filename": "Compliance_Checklist_SOC2.md",      "collection": "Finance & Legal",   "owner": "kevin.obrien",    "visibility": "team",          "status": "ready",   "team_access": ["Finance & Legal", "Engineering — Backend", "Executive Leadership"]},
    {"filename": "Data_Processing_Agreement.md",      "collection": "Finance & Legal",   "owner": "yvonne.king",     "visibility": "team",          "status": "ready",   "team_access": ["Finance & Legal", "Sales — Enterprise"]},
    {"filename": "IP_and_Confidentiality_Policy.md",  "collection": "Finance & Legal",   "owner": "yvonne.king",     "visibility": "public",        "status": "ready",   "team_access": []},
    {"filename": "Equity_Vesting_Guide.md",           "collection": "Finance & Legal",   "owner": "kevin.obrien",    "visibility": "confidential",  "status": "pending", "team_access": []},
    {"filename": "Invoice_and_Expense_Policy.md",     "collection": "Finance & Legal",   "owner": "kevin.obrien",    "visibility": "public",        "status": "ready",   "team_access": []},
]

# ── Document content (markdown) ───────────────────────────────────────────────

DOC_CONTENT: dict[str, str] = {

"Employee_Handbook_2026.md": """# TechCorp Employee Handbook 2026

## Mission & Values
TechCorp builds project management software that helps teams ship faster. Our values are Transparency, Customer Obsession, Ownership, and Continuous Learning.

## Work Hours
Core hours are 10am–3pm in your local timezone. Outside core hours, employees manage their own schedules. The standard workweek is 40 hours.

## Code of Conduct Summary
All employees must act with integrity, treat colleagues respectfully, and avoid conflicts of interest. Full details are in the Code of Conduct document.

## Compensation & Benefits
Salaries are reviewed annually each February. All full-time employees receive equity grants, health insurance, dental, vision, 401k with 4% match, and a $1,500 annual learning stipend.

## PTO Summary
Full-time employees receive 20 days PTO per year, accruing at 1.67 days/month from day one. Unused PTO rolls over up to 5 days. See PTO_and_Leave_Policy.md for full details.

## Remote Work
TechCorp is remote-first. All employees are eligible to work remotely full-time. A $750 home office stipend is provided in the first 90 days. See Remote_Work_Policy.md for full details.

## Performance Reviews
Reviews are conducted twice yearly: in February (annual) and August (mid-year check-in). Employees are rated on a 1–5 scale across four dimensions: Impact, Collaboration, Growth, and Execution.

## Onboarding
New employees complete a 30-day onboarding checklist covering tool access, team introductions, and first project assignment. See Onboarding_Checklist.md.
""",

"Code_of_Conduct.md": """# TechCorp Code of Conduct

## Our Standards
TechCorp is committed to providing a professional, inclusive environment. All employees, contractors, and partners are expected to uphold these standards.

## Respectful Workplace
Harassment, discrimination, bullying, or retaliation of any kind is not tolerated. This applies to all work settings including Slack, video calls, and in-person events.

## Conflicts of Interest
Employees must disclose any personal financial interest in a vendor, customer, or competitor. Outside employment must be approved by your manager and HR.

## Confidentiality
Employees have access to confidential information about TechCorp's products, customers, and finances. This must not be shared outside the company or used for personal gain.

## Use of Company Resources
Company systems, software, and data are for business use. Limited personal use of communication tools is acceptable, but company data must never be stored on personal devices.

## Reporting Violations
Report concerns to your HR business partner, your manager, or through the anonymous ethics hotline at ethics@techcorp.io. Retaliation against anyone who reports in good faith is strictly prohibited.

## Consequences
Violations of this Code may result in disciplinary action up to and including termination. Serious violations may be referred to law enforcement.
""",

"Benefits_Guide_2026.md": """# TechCorp Benefits Guide 2026

## Health Insurance
TechCorp covers 90% of premiums for employees and 75% for dependents. Plans available: Blue Shield PPO (preferred), Kaiser HMO, and a High-Deductible HSA-eligible plan. Enrollment opens annually in November.

## Dental & Vision
Delta Dental covers 100% of preventive care and 80% of basic restorative. VSP Vision covers annual exams and $200 toward frames or contacts.

## 401(k) Retirement Plan
TechCorp matches 100% of contributions up to 4% of salary. Matching contributions vest over 3 years: 33% at year 1, 66% at year 2, 100% at year 3.

## Equity
All full-time employees receive stock options with a 4-year vesting schedule and 1-year cliff. Refresh grants are awarded annually based on performance.

## Learning & Development
Employees receive a $1,500 annual stipend for courses, conferences, books, and certifications. Requests are submitted through the L&D portal and approved by managers.

## Wellness
A $600 annual wellness stipend covers gym memberships, fitness equipment, or mental health apps. TechCorp also offers 8 free sessions per year with licensed therapists through our EAP.

## Parental Leave
Primary caregivers receive 16 weeks paid leave. Secondary caregivers receive 6 weeks. Leave can be taken any time within the first year after birth or adoption.

## Life Insurance
TechCorp provides life insurance equal to 2x annual salary at no cost. Supplemental coverage is available for purchase.
""",

"Performance_Review_Template.md": """# Performance Review Template

## Review Cycle
Annual reviews are completed in February. Mid-year check-ins occur in August. Managers submit reviews two weeks before the review meeting.

## Rating Scale
1 - Below Expectations: Performance does not meet role requirements.
2 - Developing: Partially meets expectations; growth areas identified.
3 - Meets Expectations: Consistently delivers on all role responsibilities.
4 - Exceeds Expectations: Regularly exceeds goals; demonstrates leadership.
5 - Outstanding: Exceptional impact; top performer in peer group.

## Review Dimensions
**Impact**: Measurable outcomes delivered relative to goals and OKRs.
**Collaboration**: Effectiveness in working across teams and supporting colleagues.
**Growth**: Proactive skill development and openness to feedback.
**Execution**: Quality of work, reliability, and ability to meet deadlines.

## Employee Self-Assessment
1. What are your top 3 accomplishments this review period?
2. Where did you fall short of your goals, and why?
3. What skills did you develop, and what would you like to develop next?
4. How can your manager or team better support you?

## Manager Assessment
Complete each dimension with a rating and 2–4 sentences of specific, behavioral evidence. Reference concrete examples over opinions.

## Calibration
Reviews are calibrated across teams by HR and senior leadership before being shared with employees. Ratings may be adjusted to maintain consistency across the organization.
""",

"Onboarding_Checklist.md": """# New Employee Onboarding Checklist

## Before Day 1 (IT Admin tasks)
- [ ] Provision laptop and ship to employee address
- [ ] Create accounts: Google Workspace, GitHub, Slack, Linear, Notion, 1Password, AWS
- [ ] Add to org chart and team channels in Slack
- [ ] Send welcome email with first-day instructions

## Day 1
- [ ] Complete I-9 and W-4 tax forms in Rippling
- [ ] Set up 1Password and enable MFA on all accounts
- [ ] Join #general, #announcements, and department Slack channels
- [ ] 1:1 welcome meeting with manager (30 min)
- [ ] Meet with HR for benefits enrollment walkthrough

## Week 1
- [ ] Read: Employee Handbook, Code of Conduct, Security Policy
- [ ] Complete security awareness training (mandatory, 2 hours)
- [ ] Shadow two team members on their daily work
- [ ] Set up local development environment (Engineering only)
- [ ] Attend team standup and weekly sync

## Days 8–30
- [ ] Complete 30-60-90 day plan with manager
- [ ] Schedule intro 1:1s with all direct teammates
- [ ] Attend your first All Hands meeting
- [ ] Submit first expense report (home office stipend)
- [ ] Enroll in benefits within 30-day window

## Day 30 Check-in
Manager and employee complete a 30-day retrospective: what's going well, what's confusing, and what support is needed for the next 60 days.
""",

"Remote_Work_Policy.md": """# Remote Work Policy

## Eligibility
All full-time TechCorp employees are eligible for full-time remote work from day one. Contractors may work remotely at their manager's discretion.

## Core Hours
Employees must be available and responsive from 10am–3pm in their local timezone. Meetings will generally be scheduled within these hours.

## Home Office Stipend
New hires receive a one-time $750 stipend within the first 90 days to set up a productive home workspace. Eligible purchases: monitor, keyboard, webcam, desk, chair. Submit receipts through Expensify.

## Internet & Equipment
TechCorp does not reimburse ongoing internet costs. Company-issued laptops must be used for all work. Personal devices must not be used to access company systems or store company data.

## Security Requirements
All remote employees must use the VPN when accessing internal systems. Laptops must use full-disk encryption and screen lock activates after 5 minutes of inactivity.

## In-Person Requirements
Teams may be asked to travel for quarterly offsites, annual company kickoffs, and key customer meetings. Travel costs are fully covered by TechCorp. Approximately 2–4 trips per year should be expected.

## Co-working Spaces
Employees may expense up to $200/month for a co-working space membership with manager approval, submitted through Expensify.
""",

"PTO_and_Leave_Policy.md": """# PTO and Leave Policy

## Paid Time Off (PTO)
Full-time employees receive 20 days (160 hours) of PTO per year. PTO accrues at 1.67 days per month starting from the first day of employment. Part-time employees accrue PTO proportionally.

## PTO Rollover
Unused PTO rolls over to the next calendar year, up to a maximum of 5 days (40 hours). Accrued PTO above the cap is forfeited on January 1.

## Requesting PTO
Submit PTO requests in Rippling at least 5 business days in advance for durations of 3+ days. For same-day or next-day requests, notify your manager directly via Slack.

## Company Holidays
TechCorp observes 11 federal holidays plus a company-wide winter break from December 24 through January 1 (approximately 6 additional days, confirmed annually in November).

## Sick Leave
Employees receive 10 days of sick leave per year (separate from PTO). Sick leave does not roll over. You do not need to provide a doctor's note for absences of 3 days or fewer.

## Parental Leave
Primary caregivers: 16 weeks fully paid. Secondary caregivers: 6 weeks fully paid. Leave can be taken any time within the 12 months following birth, adoption, or foster placement.

## Bereavement Leave
5 days paid leave for the death of an immediate family member (spouse, child, parent, sibling). 3 days for extended family (grandparent, in-law). Additional unpaid leave may be approved.

## Jury Duty
TechCorp provides paid leave for jury duty for up to 4 weeks. Show your summons to HR and notify your manager immediately.
""",

"Compensation_Bands_2026.md": """# Compensation Bands 2026 — CONFIDENTIAL

This document is confidential and restricted to HR and Executive Leadership.

## Engineering
- L1 (Junior Engineer): $95,000–$115,000
- L2 (Engineer): $120,000–$145,000
- L3 (Senior Engineer): $150,000–$180,000
- L4 (Staff Engineer): $185,000–$220,000
- L5 (Principal Engineer): $225,000–$270,000

## Product Management
- PM I: $110,000–$130,000
- PM II (Senior PM): $135,000–$160,000
- Director of Product: $165,000–$200,000

## Sales
- SDR / BDR: $55,000 base + variable (OTE $85,000–$100,000)
- Account Executive (SMB): $75,000 base + variable (OTE $130,000–$150,000)
- Account Executive (Enterprise): $90,000 base + variable (OTE $180,000–$220,000)
- Solutions Engineer: $110,000 base + variable (OTE $150,000–$170,000)

## Marketing
- Marketing Coordinator: $65,000–$75,000
- Marketing Manager: $90,000–$115,000
- Director of Marketing: $140,000–$170,000

## Customer Success
- CS Coordinator: $60,000–$70,000
- CS Manager: $85,000–$105,000
- Director of CS: $130,000–$155,000

## Equity Refresh
Annual equity refreshes are granted in March based on performance rating. Outstanding (5): 100% of initial grant. Exceeds (4): 75%. Meets (3): 50%.
""",

"Hiring_Plan_Q1_2026.md": """# Hiring Plan Q1 2026 — CONFIDENTIAL

## Summary
TechCorp plans to add 18 net new employees in Q1 2026, increasing headcount from 100 to 118.

## Engineering (8 hires)
- 3× Backend Engineer (L2–L3): Replace 1 departure + growth
- 2× Frontend Engineer (L2): Frontend team expansion
- 1× DevOps Engineer (L3): Infrastructure scaling
- 1× ML Engineer (L3): AI features roadmap
- 1× QA Engineer (L2): Test coverage initiative

## Sales (5 hires)
- 2× SDR: Pipeline generation for H1 push
- 2× Account Executive (Enterprise): Enterprise segment growth
- 1× Sales Engineer: Enterprise technical support

## Customer Success (2 hires)
- 2× CS Manager: Expansion of CS capacity ahead of new customer cohort

## Product (2 hires)
- 1× Senior PM: NextGen Analytics ownership
- 1× Product Designer: Dashboard V2 and design system

## Marketing (1 hire)
- 1× Demand Gen Manager: Paid channel ownership

## Budget
Total Q1 recruiting budget: $180,000 (agency fees, sourcing tools, interview travel). Target cost-per-hire: $10,000.
""",

"Exit_Interview_Template.md": """# Exit Interview Template

## Purpose
Exit interviews help TechCorp understand why employees leave and identify opportunities to improve the employee experience.

## Standard Questions
1. What is your primary reason for leaving TechCorp?
2. What did you enjoy most about working here?
3. What could TechCorp do better to retain employees like you?
4. How would you describe the culture at TechCorp?
5. Did you feel you had the resources and support to do your job well?
6. How would you rate your relationship with your manager?
7. Did you feel your contributions were recognized and valued?
8. Would you consider returning to TechCorp in the future?
9. Would you recommend TechCorp as a place to work to others?

## Role-Specific Questions
**Engineering**: Were you satisfied with the technical challenge level? Were code review and deployment processes efficient?
**Sales**: Did you feel you had the right tools, pricing flexibility, and support to hit your quota?
**Customer Success**: Did you have adequate product knowledge and escalation support?

## Confidentiality
Responses are shared with HR and the relevant VP in anonymized summaries only. Individual responses are not shared with direct managers without consent.
""",

"System_Architecture_Overview.md": """# System Architecture Overview

## High-Level Design
TechCorp's platform is a cloud-native, microservices-based system deployed on Google Cloud Platform (GCP). All services communicate over internal gRPC, with an API gateway handling external REST traffic.

## Core Services
**Auth Service**: Issues JWT access tokens (30-minute expiry) and refresh tokens (7-day expiry) using HS256. MFA is enforced for all admin and finance accounts.
**Project Service**: Manages projects, tasks, milestones, and file attachments.
**Notification Service**: Dispatches in-app, email, and webhook notifications. Uses a Redis-backed queue.
**Analytics Service**: Aggregates usage events in BigQuery. Runs batch jobs nightly.
**Search Service**: ElasticSearch-backed full-text search across projects and documents.

## Database
Production uses Cloud SQL (PostgreSQL 15). Development uses SQLite. Migrations are managed with Alembic. Connection pooling via PgBouncer (pool size: 20 per service).

## Authentication Flow
1. Client POSTs credentials to /auth/login
2. Auth service validates, returns access_token + refresh_token
3. All subsequent requests include Authorization: Bearer {access_token}
4. Tokens expire after 30 minutes; clients use refresh_token to obtain new access_token

## Infrastructure
GKE clusters in us-central1 (primary) and us-east1 (failover). Terraform manages all infrastructure. CloudFlare handles DNS and DDoS protection. Uptime SLA: 99.9%.

## Monitoring
Grafana + Prometheus for metrics. Structured logging via Cloud Logging. PagerDuty for on-call alerts. P0 incidents trigger automatic page within 2 minutes.
""",

"API_Documentation_v3.md": """# API Documentation v3

## Base URL
Production: https://api.techcorp.io/v3
Staging: https://api-staging.techcorp.io/v3

## Authentication
All endpoints require a Bearer token in the Authorization header.
```
Authorization: Bearer <access_token>
```
Obtain tokens via POST /auth/login. Tokens expire after 30 minutes. Use POST /auth/refresh with a valid refresh_token to obtain a new access_token.

## Rate Limiting
100 requests/minute per API key for standard plans. 1,000 requests/minute for enterprise plans. Rate limit headers: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset.

## Core Endpoints
**Projects**
- GET /projects — List all projects (paginated, max 100 per page)
- POST /projects — Create a project
- GET /projects/{id} — Get project details
- PATCH /projects/{id} — Update project
- DELETE /projects/{id} — Archive project

**Tasks**
- GET /projects/{id}/tasks — List tasks
- POST /projects/{id}/tasks — Create task
- PATCH /tasks/{id} — Update task status, assignee, due date

**Users**
- GET /users/me — Get current user profile
- GET /users/{id} — Get user by ID (admin only)

## Pagination
Use cursor-based pagination: pass `cursor` param from the `next_cursor` field in responses.

## Error Codes
400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 429 Rate Limited, 500 Internal Server Error.
""",

"Database_Schema_Reference.md": """# Database Schema Reference

## Core Tables

### users
- id (UUID, PK), email (VARCHAR 255, UNIQUE), username (VARCHAR 255, UNIQUE)
- hashed_password (VARCHAR), is_active (BOOLEAN), created_at, updated_at

### projects
- id (UUID, PK), name (VARCHAR 255), description (TEXT), owner_id (FK users.id)
- status (ENUM: active, archived, completed), created_at, updated_at

### tasks
- id (UUID, PK), project_id (FK projects.id), title (VARCHAR 500), description (TEXT)
- assignee_id (FK users.id), status (ENUM: backlog, in_progress, done, cancelled)
- priority (ENUM: low, medium, high, urgent), due_date (TIMESTAMPTZ)
- created_at, updated_at

### comments
- id, task_id (FK), author_id (FK users.id), body (TEXT), created_at

## Indexes
- users: idx_users_email, idx_users_username
- tasks: idx_tasks_project_id, idx_tasks_assignee_id, idx_tasks_status, idx_tasks_due_date
- projects: idx_projects_owner_id, idx_projects_status

## Migrations
All schema changes use Alembic. Run `alembic upgrade head` to apply pending migrations.
Never use raw DDL in production. All migration files must be reviewed by a senior engineer before merging.

## Connection Pooling
PgBouncer is deployed between services and the database. Pool mode: transaction. Max connections: 100 per primary, 20 per replica.
""",

"Security_Policy_and_Procedures.md": """# Security Policy and Procedures

## Access Control
All systems use role-based access control (RBAC). Principle of least privilege is enforced. Access is reviewed quarterly by IT.

## Password Policy
Minimum 12 characters, must include uppercase, lowercase, digit, and symbol. Passwords must not be reused within the last 10 cycles. MFA is mandatory for all employees.

## Data Classification
- Public: Marketing content, documentation, public API
- Internal: Employee data, source code, internal tools
- Confidential: Customer PII, financial data, salary information, contracts
- Restricted: Authentication secrets, encryption keys, compliance reports

## Encryption
All data at rest is encrypted using AES-256. All data in transit uses TLS 1.3 minimum. Database backups are encrypted and stored in a separate GCP project.

## Vulnerability Management
Critical vulnerabilities (CVSS 9.0+) must be patched within 24 hours. High (CVSS 7.0–8.9) within 7 days. Medium within 30 days. Dependency scanning runs in CI on every PR.

## Incident Response
See Incident_Response_Playbook.md for step-by-step procedures. All P0/P1 incidents must be reported to the Security team and CISO within 1 hour of detection.

## Acceptable Use
Company systems are for business use only. Accessing illegal content, running cryptocurrency miners, or circumventing security controls are grounds for immediate termination.
""",

"Incident_Response_Playbook.md": """# Incident Response Playbook

## Severity Levels
- **P0 (Critical)**: Production down, data breach, security compromise. On-call paged immediately.
- **P1 (High)**: Major feature degraded, affecting >10% of users.
- **P2 (Medium)**: Feature degraded, workaround available.
- **P3 (Low)**: Minor issue, minimal user impact.

## P0 Response Steps
1. **Detect**: Alert fires in PagerDuty or user report received.
2. **Acknowledge**: On-call engineer acknowledges within 5 minutes.
3. **Communicate**: Post in #ops-alerts and #general: "We are investigating an issue with [service]."
4. **Mitigate**: Rollback last deploy or enable feature flag off. Do not wait for root cause.
5. **Escalate**: If not resolved in 30 minutes, page engineering manager and CTO.
6. **Resolve**: Confirm resolution and post update in #general.
7. **Postmortem**: Complete within 48 hours using the postmortem template.

## Communication Templates
Initial: "We are aware of an issue affecting [feature]. Our team is investigating."
Update: "The issue is identified as [cause]. We expect resolution by [time]."
Resolved: "The incident is resolved. Impact duration: [X] minutes. Full postmortem to follow."

## Runbooks
- API latency: Check Cloud SQL connections, PgBouncer pool exhaustion, slow query log.
- Auth failures: Check Auth Service logs, JWT secret rotation, Redis connectivity.
- Data loss: Contact oncall DBA immediately, do not run any writes until assessed.
""",

"CI_CD_Pipeline_Guide.md": """# CI/CD Pipeline Guide

## Overview
TechCorp uses GitHub Actions for CI and ArgoCD for continuous deployment to GKE.

## Pipeline Stages
1. **Lint**: ESLint (frontend), Ruff (backend). Fails fast on errors.
2. **Test**: Unit tests (pytest for Python, Jest for TypeScript). Coverage minimum: 80%.
3. **Build**: Docker image built and pushed to GCR.
4. **Security Scan**: Trivy scans the Docker image for CVEs. Critical vulnerabilities block the pipeline.
5. **Deploy to Staging**: Automatic on merge to `main`. ArgoCD syncs within 2 minutes.
6. **Integration Tests**: Playwright E2E suite runs against staging.
7. **Deploy to Production**: Manual approval required from team lead. Single-click in ArgoCD UI.

## Branch Strategy
- `main`: Production-ready code. Protected — requires 2 approvals.
- `staging`: Auto-deploys to staging environment.
- `feature/*`: Developer branches. PRs merge into `main`.

## Rollback
To rollback: navigate to ArgoCD, select the service, click "History", and select the previous revision. Rollback completes in under 90 seconds.

## Environment Variables
Secrets are stored in Google Secret Manager. Never commit secrets to Git. Use the `gcloud secrets` CLI to access secrets locally during development.

## On-Call Deployment Freeze
No deployments between 5pm Friday and 9am Monday without explicit VP Engineering approval.
""",

"Code_Review_Standards.md": """# Code Review Standards

## Purpose
Code review ensures correctness, maintainability, and knowledge sharing. Every change to `main` must be reviewed.

## Requirements
- Minimum 2 approvals for production code changes.
- At least 1 approval from a senior engineer (L3+) for architecture changes.
- PR must pass all CI checks before merging.
- PRs should be <400 lines of change. Larger PRs require prior discussion in Linear.

## What Reviewers Should Check
1. **Correctness**: Does the code do what the description says?
2. **Edge cases**: Are error paths and null cases handled?
3. **Security**: No SQL injection, no hardcoded secrets, input validation at boundaries.
4. **Performance**: No N+1 queries, appropriate indexing, no unbounded loops.
5. **Tests**: New logic has unit tests. Critical paths have integration tests.
6. **Readability**: Variable names are clear, complex logic has comments.

## PR Description Template
- **What**: One sentence summary.
- **Why**: Motivation and context.
- **How**: Key technical decisions made.
- **Testing**: How it was tested.
- **Screenshots** (for UI changes).

## Response Time
Reviewers should respond within 1 business day. If a reviewer cannot review in time, they should reassign.
""",

"Tech_Debt_Backlog_Q1_2026.md": """# Tech Debt Backlog Q1 2026

## Priority 1 — Must Address This Quarter
| Item | Owner | Effort | Impact |
|------|-------|--------|--------|
| Replace synchronous ORM queries with async in Project Service | liam.nguyen | L | High — blocking horizontal scaling |
| Upgrade PostgreSQL 13 → 15 (security + performance) | felix.braun | M | High — unsupported version |
| Remove deprecated /v1 API endpoints | alex.wu | S | Medium — confuses SDK users |

## Priority 2 — Target Q2
| Item | Owner | Effort | Impact |
|------|-------|--------|--------|
| Consolidate 3 notification code paths into 1 | ryan.oconnell | M | Medium — reduces bug surface |
| Add structured logging to Auth Service | elena.kovar | S | Medium — improves incident response |
| Replace bespoke feature-flag system with LaunchDarkly | oscar.lindqvist | L | Medium — current system has no audit log |

## Priority 3 — Backlog
- Migrate from REST to GraphQL for mobile clients
- Refactor monolithic Project Service into sub-services
- Add OpenTelemetry tracing across all services

## Definition of Effort
S = 1–3 days, M = 1–2 weeks, L = 2–4 weeks
""",

"Infrastructure_Cost_Analysis.md": """# Infrastructure Cost Analysis 2025 — CONFIDENTIAL

## Total Cloud Spend
2025 total GCP spend: $1,240,000 (up 28% from 2024's $968,000).

## Breakdown by Service
| Service | Monthly Avg | Annual | % of Total |
|---------|------------|--------|------------|
| GKE Compute | $42,000 | $504,000 | 41% |
| Cloud SQL | $18,500 | $222,000 | 18% |
| BigQuery | $12,000 | $144,000 | 12% |
| Cloud Storage | $6,200 | $74,400 | 6% |
| CloudFlare | $3,800 | $45,600 | 4% |
| ElasticSearch (Elastic Cloud) | $14,000 | $168,000 | 14% |
| Other | $6,800 | $81,600 | 7% |

## Top Cost Drivers
1. GKE: Over-provisioned node pools. Rightsizing analysis shows 30% reduction possible.
2. ElasticSearch: Managed service is expensive. Evaluate self-hosted on GKE.
3. BigQuery: Slot reservations underutilized during off-peak hours.

## 2026 Cost Reduction Targets
- Implement GKE autoscaling and spot node pools: target -$80K/year
- Migrate ElasticSearch to self-hosted: target -$100K/year
- BigQuery reservations optimization: target -$30K/year
- Total target savings: $210,000 (17% reduction)
""",

"Engineering_OKRs_2026.md": """# Engineering OKRs 2026

## Objective 1: Achieve 99.99% Uptime
- KR1: Reduce P0 incidents from 8 (2025) to 2 or fewer
- KR2: All critical services have runbooks reviewed and tested
- KR3: Mean time to recovery (MTTR) < 15 minutes for P0/P1

## Objective 2: Ship Faster
- KR1: Reduce PR cycle time from 3.2 days to 1.5 days average
- KR2: Deploy to production 5× per week (up from 2.1× in 2025)
- KR3: Test coverage across all services ≥ 85%

## Objective 3: Scale to 10× Current Load
- KR1: GKE autoscaling handles 10× traffic spikes without manual intervention
- KR2: Database query P95 latency < 50ms at 10× load
- KR3: Complete async migration for Project Service and Auth Service

## Objective 4: Zero Critical Security Vulnerabilities
- KR1: All critical CVEs patched within 24 hours of detection
- KR2: 100% of services pass OWASP Top 10 audit by Q2
- KR3: SOC 2 Type II certification achieved by Q3

## Tracking
OKRs are tracked weekly in the Engineering team Linear project. Progress is reviewed monthly by VP Engineering and updated in the Exec Leadership Sync.
""",

"Postmortem_Dec2025_Auth_Outage.md": """# Postmortem: Auth Service Outage — December 14, 2025

## Summary
The Auth Service was unavailable for 47 minutes on December 14, 2025 from 14:23 to 15:10 PST. Approximately 8,400 users were unable to log in. No data loss occurred.

## Timeline
- 14:23: Automated deploy of auth-service v2.14.1 to production.
- 14:26: PagerDuty alert fires — Auth Service returning 500 errors.
- 14:28: On-call engineer (ryan.oconnell) acknowledges alert.
- 14:35: Root cause identified: JWT secret key rotation script ran during deploy, invalidating all active sessions.
- 14:40: Rollback to v2.14.0 initiated.
- 15:10: Service fully restored. Active sessions re-established.

## Root Cause
The JWT secret key rotation script was incorrectly included in the deploy pipeline for v2.14.1. When deployed, the script rotated the secret, invalidating all issued tokens. The rotation was not designed to run during active traffic.

## Contributing Factors
- No canary deployment for Auth Service (deploy went 0% → 100%).
- Secret rotation script lacked a guard against running in production during peak hours.
- Runbook did not include rollback steps for token invalidation scenarios.

## Action Items
1. Add canary deployment stage for Auth Service (Owner: felix.braun, Due: Jan 15)
2. Add pre-deploy check: rotation scripts blocked during active deployments (Owner: elena.kovar, Due: Jan 10)
3. Update incident runbook with token invalidation recovery steps (Owner: ryan.oconnell, Due: Dec 20)
""",

"Data_Privacy_Compliance_Guide.md": """# Data Privacy Compliance Guide

## Applicable Regulations
TechCorp operates under GDPR (EU customers), CCPA (California customers), and SOC 2 Type II certification requirements.

## Data Inventory
Customer data is classified as:
- Account Data: name, email, billing info
- Usage Data: feature usage, session logs (anonymized after 90 days)
- Content Data: project and task content created by users

## GDPR Requirements
- Data Processing Agreements (DPAs) are required with all sub-processors.
- Data subject requests (access, deletion, portability) must be fulfilled within 30 days.
- Privacy policy must be updated within 7 days of any material change.
- Data breach notification to supervisory authority required within 72 hours.

## CCPA Requirements
- California residents have the right to know, delete, and opt out of sale of personal information.
- Do Not Sell opt-out must be honored within 15 business days.
- Annual data inventory update required.

## Data Retention
- Customer content: Retained for 60 days after account deletion.
- Usage logs: Anonymized after 90 days, deleted after 2 years.
- Financial records: Retained for 7 years per IRS requirements.
- Employee records: Retained for 3 years post-employment.

## Sub-processors
Key sub-processors: Google Cloud Platform (infrastructure), Stripe (payments), Intercom (support), Segment (analytics). DPAs are on file in the Finance & Legal collection.
""",

"Product_Roadmap_2026.md": """# Product Roadmap 2026

## Theme: Intelligence + Scale
2026 is focused on making TechCorp the most intelligent project management platform, while scaling to 10× our current user base.

## Q1 2026 (Jan–Mar)
- **Mobile App Launch**: Native iOS and Android apps. Feature parity with web for task management.
- **Auth Improvements**: SSO support (Okta, Azure AD), MFA enforcement for enterprise plans.
- **Performance**: P95 API latency < 100ms. Dashboard load time < 1.5 seconds.

## Q2 2026 (Apr–Jun)
- **Dashboard V2**: Fully customizable dashboards with drag-and-drop widgets.
- **Custom Reporting**: Build and share custom reports across projects and teams.
- **API v4**: Breaking changes: cursor pagination, richer filtering, webhook improvements.

## Q3 2026 (Jul–Sep)
- **AI-Powered Insights**: Automatic risk detection, deadline prediction, blocker identification.
- **Integrations Marketplace**: Native integrations with Slack, GitHub, Figma, Salesforce.
- **Advanced Search**: Full-text search with filters across all content.

## Q4 2026 (Oct–Dec)
- **Enterprise Compliance**: Audit logs, data residency options, HIPAA-ready mode.
- **Admin Console v2**: Centralized user management, SSO config, billing, and usage analytics.

## Not in 2026
- Video calling / collaboration features
- White-labeling / OEM capabilities
- Desktop native app
""",

"Q4_2025_Product_Review.md": """# Q4 2025 Product Review

## Summary
Q4 2025 was the strongest product quarter to date. We shipped 12 major features, improved API reliability to 99.96%, and grew MAU by 34%.

## Features Shipped
- **Recurring Tasks**: 67% of enterprise users enabled within 2 weeks of launch.
- **Guest Access**: Allows external stakeholders to view (not edit) projects. 3,200 guest accounts created in first month.
- **Notification Digest**: Daily/weekly email summaries. Reduced notification-related churn by 18%.
- **CSV Import/Export**: Top-requested feature. Resolved 12 customer escalations immediately after launch.
- **Keyboard Shortcuts**: 45% of power users adopted within first week.

## Metrics
- MAU: 42,000 (up 34% from Q3's 31,300)
- NPS: 52 (up from 44 in Q3)
- Feature adoption rate (new features, 30-day): 41%
- API P99 latency: 380ms (down from 620ms in Q3)

## What Didn't Ship
- **Dashboard V2**: Moved to Q1 2026 due to scope creep. Design iterations took 3 extra weeks.
- **SSO**: Delayed to Q1 2026 due to Auth Service stability work being prioritized.

## Key Learnings
Scope creep on Dashboard V2 cost us 3 weeks. In 2026 we are implementing strict spec freeze 2 weeks before engineering kickoff.
""",

"Feature_Spec_DashboardV2.md": """# Feature Spec: Dashboard V2

## Problem Statement
Current dashboards are static and not customizable. 68% of enterprise users in Jan 2026 user research said "I can't get the view I need without exporting to a spreadsheet."

## Goals
- Allow users to create fully customized dashboards with their own widget layout.
- Ship to 100% of users in Q2 2026.
- Achieve 50% adoption within 60 days of launch.

## User Stories
1. As a project manager, I can add a "Tasks by Assignee" widget to see workload distribution.
2. As a team lead, I can share a dashboard with my team so everyone has the same view.
3. As an executive, I can view a portfolio dashboard with KPIs from all projects.

## Widget Types (MVP)
- Task list (filterable, sortable)
- Chart: tasks by status, tasks by assignee, tasks by priority
- Progress bar: project completion %
- Calendar: upcoming due dates
- Text: free-form notes widget

## Technical Approach
Dashboards stored as JSON configuration in PostgreSQL. Each widget definition includes type, filters, and display options. Frontend renders via a drag-and-drop grid (react-grid-layout).

## Success Metrics
- 50% of active users create at least 1 custom dashboard within 60 days.
- NPS improvement of +5 points in dashboard satisfaction survey.
- Zero P0 incidents related to Dashboard V2 within first 30 days.
""",

"User_Research_Report_Jan2026.md": """# User Research Report — January 2026

## Methodology
20 user interviews conducted across 4 customer segments: SMB (5), Mid-Market (7), Enterprise (5), and Power Users (3). Sessions were 45 minutes each. Moderated by the Product team with Design observers.

## Top Pain Points
1. **No customization** (mentioned by 17/20): "I can't build the view I actually need."
2. **Mobile experience** (15/20): "I manage tasks from my phone constantly but the mobile web is unusable."
3. **Notifications overload** (14/20): "I get 50 Slack notifications a day and miss the important ones."
4. **Reporting limitations** (12/20): "I have to export to Excel for every executive report."
5. **Search quality** (10/20): "Search doesn't find tasks by description, only by title."

## Top Loved Features
1. Recurring tasks (released Q4 2025): "Finally, this was a blocker for us."
2. Guest access: "We use it for client-facing projects every day."
3. Keyboard shortcuts: "I live in keyboard shortcuts."

## Quotes
> "If you add dashboard customization, we'll expand our seat count from 25 to 100." — VP Operations, Series B startup

> "The mobile app is our biggest barrier to full team adoption." — CTO, 200-person company

## Implications for Roadmap
These findings validate Dashboard V2 and Mobile App as Q1-Q2 priorities. The notifications overload finding supports the planned notification filtering feature for Q3.
""",

"Design_System_Guidelines.md": """# TechCorp Design System Guidelines

## Foundations

### Colors
- Primary: #1B55E2 (TechBlue) — buttons, links, active states
- Primary Dark: #1240B8 — hover states
- Success: #16A34A
- Warning: #D97706
- Danger: #DC2626
- Neutral 900: #111827 — primary text
- Neutral 500: #6B7280 — secondary text
- Neutral 100: #F3F4F6 — backgrounds

### Typography
Font family: Inter (sans-serif). Sizes: 12px, 14px, 16px, 20px, 24px, 32px.
Line heights: 1.4 for body, 1.2 for headings. Weight: 400 regular, 500 medium, 600 semibold.

### Spacing
Base unit: 4px. Scale: 4, 8, 12, 16, 24, 32, 48, 64. Use Tailwind spacing classes.

## Components
**Button**: Primary (solid blue), Secondary (outlined), Danger (solid red), Ghost (text only).
**Input**: 40px height, 4px border radius, focus ring: 2px #1B55E2.
**Modal**: Max-width 560px, backdrop: black at 50% opacity, escape to dismiss.
**Toast**: Bottom-right, auto-dismiss after 4 seconds. Success: green, Error: red.
**Badge**: Pill shape, 6px padding horizontal, use for status labels.

## Accessibility
All interactive elements must have a visible focus state. Color must not be the only differentiator (add icons or labels). Minimum contrast ratio: 4.5:1 for normal text, 3:1 for large text.

## Do's and Don'ts
Do: Use system components before building custom ones. Don't: Use custom colors outside the palette. Don't: Mix button variants in the same action group.
""",

"AB_Test_Results_Q4_2025.md": """# A/B Test Results Q4 2025

## Test 1: Onboarding Checklist Redesign
**Hypothesis**: A step-by-step checklist during onboarding will increase 7-day activation.
**Result**: Variant (checklist) showed 23% improvement in 7-day activation rate (control: 41%, variant: 50.4%). Statistically significant (p < 0.01, n=3,200). **Decision: Ship variant.**

## Test 2: Pricing Page CTA Copy
**Hypothesis**: "Start Free Trial" will convert better than "Get Started."
**Result**: No statistically significant difference (control: 4.2%, variant: 4.4%). **Decision: Keep control, close test.**

## Test 3: Notification Digest Default Setting
**Hypothesis**: Defaulting to daily digest (vs. real-time) will reduce churn.
**Result**: Digest default group had 12% lower 30-day churn (control: 8.1%, variant: 7.1%). Statistically significant (p < 0.05, n=5,100). **Decision: Ship digest-default for new signups.**

## Test 4: Task Priority Color Coding
**Hypothesis**: Color-coding task priority badges increases feature adoption.
**Result**: 31% increase in priority-field usage in variant group. NPS impact: +3 points among variant group. **Decision: Ship.**

## Ongoing Tests in Q1 2026
- Email subject line personalization (expected conclusion: Feb 15)
- In-app upsell prompt timing (expected conclusion: Mar 1)
""",

"Competitive_Analysis_2026.md": """# Competitive Analysis 2026 — CONFIDENTIAL

## Market Overview
The project management software market is estimated at $7.3B in 2026, growing at 13% CAGR. Top competitors: Asana, Monday.com, Linear, Notion, Jira.

## Competitor Profiles

### Asana
Strengths: Brand recognition, enterprise features (admin console, reporting), 200+ integrations.
Weaknesses: Complex UX, slow innovation cadence, expensive enterprise tier.
Win rate vs Asana: 38%. We win on UX simplicity and price.

### Linear
Strengths: Developer-focused, fast UI, opinionated workflow, strong GitHub integration.
Weaknesses: Limited reporting, no mobile app, poor non-technical user experience.
Win rate vs Linear: 54%. We win with broader team support (not just engineering).

### Monday.com
Strengths: Highly customizable, marketing-heavy, strong in operations and marketing use cases.
Weaknesses: Performance at scale, complex pricing, steep learning curve.
Win rate vs Monday.com: 42%.

### Notion
Strengths: Flexible, AI features (Notion AI), strong for documentation + PM hybrid use cases.
Weaknesses: Not purpose-built for task management, weak reporting.
Win rate vs Notion: 61% when competing on PM use case.

## Our Differentiators
1. Best-in-class UX for mixed technical and non-technical teams.
2. Fastest time to value (< 10 minutes to first project).
3. Most transparent pricing: no hidden add-ons.
4. AI roadmap (Q3 2026) will differentiate on intelligence.
""",

"PRD_NextGen_Analytics.md": """# Product Requirements: Next-Gen Analytics Module

## Problem
Current analytics are limited to basic project status reports. Enterprise customers (42% of ARR) consistently cite analytics as a top-3 reason for churn consideration. Competitors Asana and Monday.com both offer advanced analytics suites.

## Goals
- Reduce enterprise churn risk attributed to analytics from 42% to <15%.
- Achieve 60% adoption of the new analytics module within 90 days of launch.
- Enable customers to eliminate their reliance on manual Excel exports.

## Requirements

### Must Have (Q3 2026 Launch)
- Cross-project reporting with custom date ranges
- Velocity charts (tasks completed per sprint/week)
- Team workload heatmap by assignee
- Goal/OKR tracking with progress visualization
- Export to PDF and CSV
- Saved report templates, shareable by link

### Nice to Have (Q4 2026)
- AI-generated insights ("This project is 2 weeks behind pace based on historical velocity")
- Scheduled report delivery via email
- Embedded dashboard in external tools (e.g., Salesforce, Notion)

## Technical Approach
BigQuery as the data warehouse. Analytics queries served by a read-only replica to avoid impacting production performance. Frontend visualization library: Recharts.

## Success Metrics
- 60% adoption (≥1 custom report created per account) within 90 days
- NPS for analytics feature ≥ 45
- Reduction in "analytics" churn reasons by 60%
""",

"Sales_Playbook_2026.md": """# Sales Playbook 2026

## Sales Methodology: MEDDIC
TechCorp's enterprise sales process follows MEDDIC: Metrics, Economic Buyer, Decision Criteria, Decision Process, Identify Pain, Champion.

## Discovery Framework
**Opening question**: "Walk me through how your team manages projects today."
**Pain questions**: "Where do things fall through the cracks?", "How do you currently track whether the team is on schedule?"
**Impact questions**: "What does a missed deadline cost you?", "How much time does your team spend on status updates each week?"
**Vision questions**: "If you had a magic wand, what would your ideal project view look like?"

## Qualification (BANT)
Budget: Confirm a budget exists or can be created. Min deal size for enterprise process: $30K ARR.
Authority: Are we speaking with the Economic Buyer? If not, who is?
Need: Is there a compelling event or pain driving this evaluation?
Timeline: When do they need to be live? Work backwards from their go-live date.

## Deal Stages
1. Discovery (0%): Initial meeting, qualify BANT.
2. Demo (20%): Tailored demo aligned to their use case.
3. Technical Evaluation (40%): POC or trial, technical sign-off.
4. Proposal (60%): Formal proposal sent.
5. Negotiation (80%): Commercial terms agreed, legal review.
6. Closed Won (100%) / Closed Lost.

## Pricing Authority
- AE can discount up to 10% without approval.
- 11–20% requires Director of Sales approval.
- >20% requires VP Sales and CFO approval.
""",

"Ideal_Customer_Profile.md": """# Ideal Customer Profile (ICP)

## Primary ICP: Mid-Market Technology Company
**Company size**: 50–500 employees
**Industry**: Technology (SaaS, fintech, healthtech), Digital Agencies, Professional Services
**Revenue**: $10M–$200M ARR
**Team structure**: Cross-functional teams with Engineering, Product, and Operations
**Pain trigger**: Outgrowing spreadsheets or a point solution like Trello/Asana

## Persona 1: VP of Engineering / CTO
**Goals**: Ship faster, reduce context-switching, improve cross-team visibility.
**Frustrations**: Engineers waste time in status meetings. No single source of truth for sprint progress.
**Buying role**: Technical champion, often Economic Buyer at companies <200 employees.

## Persona 2: VP of Operations / COO
**Goals**: Operational efficiency, cross-department coordination, executive reporting.
**Frustrations**: Every team uses a different tool. Getting a company-wide status update takes a day.
**Buying role**: Economic Buyer or strong influencer at 100–500 person companies.

## Negative ICP (Avoid)
- Pure engineering teams who prefer Linear or GitHub Issues
- Enterprises requiring on-premise deployment
- Companies with <10 employees (will churn)
- Companies in highly regulated industries requiring HIPAA/FedRAMP (not yet certified)

## Signals That a Prospect is a Strong Fit
- Series A–C funded tech startup
- Using Slack + Notion + spreadsheets (common before TechCorp)
- Team size 20–150 active in the product
- Executive sponsor engaged in the sales process
""",

"Pricing_Guide_2026.md": """# Pricing Guide 2026 — FLAGGED: CONFIDENTIAL

## Public Pricing
**Starter**: Free, up to 5 users, unlimited projects, 2GB storage.
**Business**: $12/user/month (billed annually), unlimited users, 100GB storage, reporting, priority support.
**Enterprise**: Custom pricing, SSO, audit logs, dedicated CSM, SLA.

## Internal Discount Guidelines
Standard enterprise deal minimum: $30K ARR. Below this, direct to Business plan self-serve.

**Volume discounts**:
- 51–200 seats: 10% off list
- 201–500 seats: 20% off list
- 500+ seats: Negotiate; floor is 30% off list (requires CFO approval)

**Commitment discounts**:
- 2-year: additional 10% off
- 3-year: additional 15% off

**Competitive displacement**: Up to 20% additional discount for documented proof of active Asana, Monday.com, or Jira renewal within 90 days.

## ACV Targets by Segment
- SMB self-serve: $1,500–$8,000 ACV
- Mid-market: $15,000–$80,000 ACV
- Enterprise: $80,000–$500,000+ ACV

## Do Not Discount Below
- Business plan: never below $9/user/month
- Enterprise: never below $7/user/month all-in (floor approved by CFO)

Never share this document with customers or prospects.
""",

"Enterprise_Proposal_Template.md": """# Enterprise Proposal Template

## Section 1: Executive Summary
[2–3 sentences] TechCorp is pleased to present this proposal for [Company Name]. Based on our discovery conversations, we understand your primary challenges are [pain point 1] and [pain point 2]. TechCorp's platform will [outcome 1] and [outcome 2].

## Section 2: Understanding Your Challenges
Summarize the pain points discovered in discovery. Use their words. Reference specific examples they gave. Example: "Your team spends an estimated 5 hours per week on manual status reporting."

## Section 3: Proposed Solution
Describe the TechCorp configuration recommended for this customer. Which modules, integrations, and workflows will be set up. Why this configuration addresses their specific needs.

## Section 4: Implementation Plan
- Week 1: Account setup, SSO configuration, admin training
- Week 2: Team onboarding and data migration support
- Week 3: First sprint / workflow live
- Week 4: Review session with sponsor

## Section 5: Investment Summary
| Component | Seats | Unit Price | Annual Total |
|-----------|-------|------------|--------------|
| Enterprise Platform | [N] | $[X]/user/yr | $[Total] |
| Implementation Support | Included | — | $0 |
| **Total Year 1** | | | **$[Total]** |

## Section 6: Why TechCorp
Reference 1–2 relevant customer case studies. Include G2 or Gartner review quotes.

## Section 7: Next Steps
1. Legal review of MSA (standard, 2–3 business days)
2. Sign and countersign order form
3. Kickoff call scheduled within 3 business days of signature
""",

"Objection_Handling_Guide.md": """# Objection Handling Guide

## "We already use Asana/Jira/Monday"
"That makes sense — those are great tools. Most of our customers came from those platforms. The most common reason they switched was [customize: UX simplicity / better reporting / faster onboarding]. Would it make sense to do a quick comparison on the specific use case that's most important to you?"

## "It's too expensive"
"I hear you. Can I ask — what budget are you working with? Often we can structure a deal that works within your current budget, especially if you're on an annual plan or replacing an existing tool." [If still stuck, offer a 2-week paid pilot at 50% off first month.]

## "We need to evaluate 3 other tools"
"Totally reasonable. To make sure this is the best use of your time, can I ask what your top 2 evaluation criteria are? I want to make sure we're the right fit before you invest more time." [Then tailor the demo or offer a structured POC.]

## "We need on-premise / our data can't leave our servers"
"Understood. That's not something we offer today, but it's on our roadmap. If data residency is a hard requirement, we do offer dedicated cloud deployments in specific regions. Would that address the concern?"

## "Your integrations list is too limited"
"Which integration is most critical for your workflow? We have a growing library of native integrations and a public API that your team can use to connect almost anything. Let me show you what's available."

## "We need HIPAA / SOC 2 / FedRAMP compliance"
"We're SOC 2 Type II certified as of Q3 2026. HIPAA is on our Q4 2026 roadmap. FedRAMP is not currently planned. What's driving the compliance requirement?"
""",

"Q4_2025_Sales_Report.md": """# Q4 2025 Sales Report

## Summary
Q4 2025 was our best quarter in company history. New ARR: $3.2M (vs. target $2.8M, 114% attainment). Total ARR reached $18.4M, up from $15.2M at end of Q3.

## New ARR by Segment
| Segment | Target | Actual | Attainment |
|---------|--------|--------|------------|
| Enterprise | $1.5M | $1.9M | 127% |
| Mid-Market | $0.9M | $0.85M | 94% |
| SMB (self-serve) | $0.4M | $0.45M | 113% |

## Top Deals Closed
- Apex Dynamics: $240K ARR (3-year, Enterprise)
- Meridian Health Partners: $185K ARR (2-year, Enterprise — first healthcare customer)
- Brightline Digital: $95K ARR (1-year, Mid-Market)

## Win/Loss Analysis
Win rate vs Asana: 44% (up from 38% in Q3). Win rate vs Linear: 57%.
Top win reasons: UX simplicity (42%), price (31%), onboarding speed (27%).
Top loss reasons: Missing integrations (38%), no mobile app (29%), enterprise features (23%).

## Pipeline Entering Q1 2026
Total qualified pipeline: $9.4M ARR. Q1 2026 target: $3.5M new ARR.

## Headcount
Team at end of Q4: 18 sellers. Q1 2026: adding 5 (2 SDR, 2 Enterprise AE, 1 SE).
""",

"Marketing_Campaign_H1_2026.md": """# Marketing Campaign Plan H1 2026

## Theme: "Ship Together"
All H1 campaigns reinforce TechCorp's positioning as the platform for cross-functional teams to ship faster, together.

## Q1 Campaign: Mobile App Launch
**Goal**: 10,000 mobile app downloads in first 30 days.
**Channels**: App Store optimization, Product Hunt launch, email to existing users, LinkedIn ads.
**Budget**: $120,000.
**Key Message**: "Your projects, everywhere you go."

## Q2 Campaign: Dashboard V2 Launch
**Goal**: 40% of existing users create a custom dashboard within 60 days.
**Channels**: In-app announcement, email sequence (3-touch), webinar, customer success outreach.
**Budget**: $80,000 (primarily in-product and email — low paid spend).
**Key Message**: "Finally, a dashboard that works the way you do."

## Demand Generation Targets H1
- MQLs: 2,400 (1,200 per quarter)
- SQLs: 480 (20% MQL → SQL conversion)
- Pipeline generated: $4.8M ARR
- CPL target: $180

## Content Calendar Themes
- January: "2026 Project Management Trends" (thought leadership)
- February: "Mobile-first work" (Mobile App launch)
- March: "Remote team collaboration" (case studies)
- April: "Dashboard best practices" (Dashboard V2 build-up)
- May: "Dashboard V2 launch" (product launch)
- June: "Mid-year review templates" (lifecycle)
""",

"Brand_Guidelines_v2.md": """# TechCorp Brand Guidelines v2

## Brand Positioning
TechCorp is the project management platform for teams that move fast. We are clear, confident, and human — never corporate or jargony.

## Logo
The TechCorp logo is a stylized "T" mark with the wordmark "TechCorp" in Inter SemiBold. Minimum size: 120px wide (digital), 1 inch (print).
Clear space: equal to the height of the "T" mark on all sides. Do not stretch, rotate, or recolor the logo.

## Color Palette
Primary: TechBlue #1B55E2. Use for CTAs, links, and key UI elements.
Black: #111827. Primary text. White: #FFFFFF. Backgrounds and reversed text.
Accent Green: #16A34A. Success, positive metrics.
Accent Red: #DC2626. Errors, alerts, negative metrics.
Mid Gray: #6B7280. Secondary text, captions.

## Typography
Headlines: Inter SemiBold (600). Body: Inter Regular (400). Code: JetBrains Mono.
Avoid: System fonts, serif fonts, decorative fonts.

## Voice & Tone
Clear: Say what you mean in as few words as possible.
Confident: We know our product is excellent — no hedging.
Human: Write like a smart colleague, not a press release.
Avoid: Buzzwords ("synergy", "leverage", "paradigm"), passive voice, jargon.

## Photography Style
Real people, real work settings. Diverse representation required. No stock-photo clichés (people high-fiving, pointing at whiteboards). Prefer candid, in-context work photos.
""",

"SEO_Content_Strategy_2026.md": """# SEO Content Strategy 2026

## Goals
- Organic traffic: 150,000 monthly visitors by end of 2026 (up from 82,000 in Dec 2025).
- Organic-sourced signups: 1,800/month by Q4 (up from 900/month).
- Domain Rating: 62 (up from 54).

## Pillar Topics
1. **Project Management** (primary) — target 40% of organic traffic
2. **Team Collaboration** — 20%
3. **Remote Work Productivity** — 15%
4. **Engineering Leadership** — 10% (developer-focused ICP)
5. **Comparisons** (vs. Asana, vs. Jira, etc.) — 15%

## High-Priority Keywords
| Keyword | Volume | Difficulty | Current Rank |
|---------|--------|------------|--------------|
| project management software | 90,000 | 85 | #14 |
| task management tool | 22,000 | 72 | #7 |
| team project tracker | 8,500 | 58 | #4 |
| asana alternative | 12,000 | 68 | #6 |
| jira alternative | 18,000 | 74 | #9 |

## Content Calendar Q1
- Jan: "The 2026 Guide to Project Management Software" (update existing pillar)
- Feb: "10 Signs Your Team Has Outgrown Spreadsheets"
- Mar: "TechCorp vs Asana: An Honest Comparison (2026)"

## Link Building
Target: 40 new referring domains/month via digital PR, guest posts, and tool directories.
""",

"Customer_Case_Studies.md": """# Customer Case Studies

## Case Study 1: Apex Dynamics
**Company**: Apex Dynamics, 280 employees, Series C fintech startup.
**Challenge**: 4 different project tools across departments, no cross-team visibility, executives spent 3 hours/week gathering status updates.
**Solution**: TechCorp deployed org-wide in 3 weeks. Custom dashboards for each VP. Slack integration for task updates.
**Results**: 3 hours/week saved per executive on status reporting. 22% reduction in missed deadlines in first quarter. NPS from their team: 72.
**Quote**: "TechCorp is the first tool all of our teams actually use." — COO, Apex Dynamics

## Case Study 2: Brightline Digital
**Company**: Brightline Digital, 95 employees, digital agency.
**Challenge**: Client projects tracked in Trello; internal projects in Notion; no unified view.
**Solution**: Migrated all client and internal projects to TechCorp in 2 weeks using CSV import.
**Results**: Project delivery on-time rate improved from 61% to 79% in first 6 months. Client reporting time cut by 60% using shared read-only dashboards.
**Quote**: "Our clients love the shared dashboard — it's replaced our weekly status call." — CEO, Brightline Digital

## Case Study 3: Meridian Health Partners
**Company**: Meridian Health Partners, 450 employees, digital health company.
**Challenge**: Compliance-heavy environment, needed audit trail of all task changes.
**Solution**: Enterprise plan with audit logs. Custom workflow for compliance review steps.
**Results**: SOC 2 audit preparation time reduced by 40%. Team adoption: 89% within 30 days.
""",

"Event_Sponsorship_Plan_2026.md": """# Event Sponsorship Plan 2026

## Goals
- Generate 600 qualified leads from events in 2026
- Increase brand awareness in engineering and product management communities
- Support 2 customer co-speaking opportunities

## Tier 1 Events (Title/Platinum Sponsor)
| Event | Date | Location | Budget | Expected Leads |
|-------|------|----------|--------|----------------|
| SaaStr Annual | May 2026 | SF, CA | $75,000 | 200 |
| ProductCon | Sep 2026 | NY, NY | $40,000 | 120 |

## Tier 2 Events (Gold/Silver Sponsor)
| Event | Date | Budget | Expected Leads |
|-------|------|--------|----------------|
| Lenny's Podcast Summit | Mar 2026 | $15,000 | 60 |
| LeadDev (Engineering Leadership) | Jun 2026 | $20,000 | 80 |
| GrowthHackers Conference | Aug 2026 | $12,000 | 50 |

## Speaking Opportunities
Submit CFPs for: SaaStr (CEO keynote), ProductCon (CPO session on AI roadmap), LeadDev (VP Engineering on scaling culture).

## Total Events Budget 2026: $220,000
Includes booth build ($30K one-time), travel and staff ($25K), swag ($15K), and sponsorship fees ($150K).

## Lead Routing
Event leads are uploaded to HubSpot within 24 hours post-event. SDRs follow up within 1 business day. Minimum 3-touch outreach before marking cold.
""",

"Lead_Scoring_Model.md": """# Lead Scoring Model — PENDING REVIEW

This document is pending final review by the Data and Sales teams.

## Scoring Framework
Leads are scored on two dimensions: Fit (company characteristics) and Intent (behavioral signals). Max score: 100. Threshold for MQL: 60.

## Fit Score (max 50 points)
| Attribute | Points |
|-----------|--------|
| Company size 50–500 | 20 |
| Industry: Tech/SaaS/Agency | 15 |
| Funding: Series A–C | 10 |
| US/Canada/UK/EU geography | 5 |

## Intent Score (max 50 points)
| Behavior | Points |
|----------|--------|
| Visited pricing page | 15 |
| Started free trial | 20 |
| Invited a teammate | 10 |
| Viewed case studies | 8 |
| Opened 3+ emails in 30 days | 5 |
| Attended webinar | 7 |

## Score Interpretation
60–74: MQL — SDR outreach within 3 business days.
75–89: Hot MQL — SDR outreach within 1 business day.
90+: SQL — AE direct outreach same day.
<60: Nurture — add to email drip sequence.

## Review Status
Pending validation against Q4 2025 closed-won data. Sales Ops to confirm scoring weights with aisha.johnson by Feb 28, 2026.
""",

"Budget_2026.md": """# 2026 Annual Budget — CONFIDENTIAL — PENDING FINAL APPROVAL

## Total Revenue Target
ARR entering 2026: $18.4M. Target ARR end of 2026: $32M. New ARR target: $13.6M.

## Revenue by Segment
- Enterprise: $7.5M new ARR
- Mid-Market: $4.1M new ARR
- SMB self-serve: $2.0M new ARR

## Operating Budget: $28.5M
| Department | Budget | % of Total |
|------------|--------|------------|
| Engineering | $9.2M | 32% |
| Sales | $7.1M | 25% |
| Marketing | $3.4M | 12% |
| Customer Success | $2.8M | 10% |
| G&A (Finance, HR, Legal) | $2.5M | 9% |
| Product & Design | $2.3M | 8% |
| Data & Analytics | $1.2M | 4% |

## Headcount Plan
Total headcount: 100 (start) → 118 (Q1) → 132 (Q2) → 145 (Q3) → 155 (EOY).

## Key Investment Areas
1. Engineering: 8 hires, GKE scaling, ElasticSearch migration.
2. Sales: 5 hires, new CRM (Salesforce), sales enablement platform.
3. Marketing: SaaStr sponsorship, SEO content program, paid acquisition.

## Cash Runway
Current cash: $22M. Burn rate target: $2.1M/month average. Runway: 10.5 months at target burn.
""",

"Q4_2025_Financial_Report.md": """# Q4 2025 Financial Report — CONFIDENTIAL

## Revenue
Q4 2025 ARR: $18.4M (up from $15.2M in Q3 2025, +21%).
Q4 2025 MRR: $1.53M. Q4 recognized revenue: $4.2M.

## Key Metrics
- Net Revenue Retention (NRR): 118%
- Gross Revenue Retention (GRR): 94%
- Customer Count: 1,240 (up from 1,050 in Q3)
- ARPU: $14,840/year
- CAC (blended): $8,200
- LTV/CAC: 7.4×
- Gross Margin: 78%

## P&L Summary (Q4 2025)
| Item | Amount |
|------|--------|
| Revenue | $4,200,000 |
| COGS (hosting, support) | $924,000 |
| **Gross Profit** | **$3,276,000** |
| S&M Expense | $1,890,000 |
| R&D Expense | $2,100,000 |
| G&A Expense | $630,000 |
| **Operating Loss** | **($1,344,000)** |

## Cash Position
Cash and equivalents at end of Q4 2025: $22.1M. Q4 net cash burn: $1.8M (improved from $2.3M in Q3).

## 2025 Full Year
Full-year revenue: $14.8M (up 67% from 2024's $8.9M). Full-year operating loss: $6.2M.
""",

"Vendor_Contracts_Summary.md": """# Vendor Contracts Summary — CONFIDENTIAL

## Critical Vendors (Annual Spend >$100K)

| Vendor | Category | Annual Spend | Renewal Date | Owner |
|--------|----------|-------------|--------------|-------|
| Google Cloud Platform | Infrastructure | $1,240,000 | Rolling | sarah.chen |
| Elastic Cloud | Search | $168,000 | Mar 2026 | oscar.lindqvist |
| Salesforce | CRM | $142,000 | Jul 2026 | diana.rodriguez |
| Stripe | Payments | $128,000 | Rolling | kevin.obrien |
| Intercom | Support | $96,000 | May 2026 | priya.patel |

## Upcoming Renewals (Next 90 Days)
- **Elastic Cloud** (Mar 15, 2026): Evaluate migration to self-hosted. Potential $100K/year savings. Owner: oscar.lindqvist.
- **Notion** (Feb 28, 2026): Assess usage — multiple teams have migrated away. May downgrade.

## Key Contract Terms
- GCP: No minimum commitment. 1-year committed use discounts in place (15% off compute).
- Salesforce: Enterprise agreement. 3-year term, annual payments. Exit penalty if cancelled before term.
- Stripe: 2.7% + $0.05 per transaction for US cards. Custom rates negotiated annually.

## Vendor Risk Assessment
- Elastic: High risk (only provider for search). Mitigation: self-hosted migration in progress.
- Stripe: Medium risk. Evaluate Braintree as backup processor.
""",

"Compliance_Checklist_SOC2.md": """# SOC 2 Type II Compliance Checklist

## Status: In Progress — Target Certification Q3 2026

## Trust Service Criteria

### Security
- [x] Logical access controls implemented (RBAC, MFA)
- [x] Network security: firewall rules, VPN required for internal access
- [x] Vulnerability management program — scans weekly, critical patches <24h
- [ ] Penetration test scheduled for Q2 2026 (Owner: felix.braun)
- [x] Incident response policy documented and tested
- [x] Security awareness training — all employees annually

### Availability
- [x] 99.9% uptime SLA defined and monitored
- [x] Disaster recovery plan documented
- [ ] DR test conducted (Owner: josh.banks, Due: Q1 2026)
- [x] Redundant infrastructure in 2 GCP regions

### Confidentiality
- [x] Data classification policy in place
- [x] Encryption at rest (AES-256) and in transit (TLS 1.3)
- [x] Customer data access restricted to authorized personnel only
- [ ] Annual access review completed for all systems (Due: Feb 28, 2026)

### Processing Integrity
- [x] Input validation in all public API endpoints
- [x] Data validation on all financial transactions
- [x] Audit logs for all admin actions

### Privacy
- [x] Privacy policy updated and published
- [x] GDPR DPAs in place with all sub-processors
- [ ] CCPA opt-out mechanism tested (Owner: yvonne.king, Due: Mar 1, 2026)
""",

"Data_Processing_Agreement.md": """# Data Processing Agreement Template

## Parties
This Data Processing Agreement ("DPA") is entered into between TechCorp Inc. ("Controller") and [Vendor Name] ("Processor").

## Definitions
"Personal Data" means any data relating to an identified or identifiable natural person.
"Processing" means any operation performed on Personal Data.
"Sub-processor" means any third party engaged by Processor to process Personal Data.

## Scope of Processing
Processor shall process Personal Data only for the purposes described in the Master Services Agreement and only on documented instructions from Controller.

## Security Measures
Processor shall implement appropriate technical and organizational measures to protect Personal Data, including: encryption, access controls, regular security testing, and incident response procedures.

## Sub-processors
Processor may engage sub-processors with prior written consent of Controller. Processor remains fully liable for sub-processor compliance. Current approved sub-processors are listed in Exhibit A.

## Data Subject Rights
Processor shall assist Controller in responding to data subject requests (access, deletion, portability, restriction) within 5 business days.

## Data Breach Notification
Processor shall notify Controller of a Personal Data breach without undue delay and no later than 48 hours of becoming aware.

## Return and Deletion
Upon termination, Processor shall return all Personal Data to Controller and delete all copies within 30 days, unless retention is required by law.

## Governing Law
This DPA is governed by the laws of the State of California, USA.
""",

"IP_and_Confidentiality_Policy.md": """# Intellectual Property and Confidentiality Policy

## Ownership of Work Product
All inventions, software, designs, processes, and other work product created by employees during their employment at TechCorp, or using TechCorp resources, are the exclusive property of TechCorp Inc.

## Pre-Existing IP
If an employee believes they have pre-existing IP relevant to their role, they must disclose it in writing to Legal before their start date. Failure to disclose may result in disputes over ownership.

## Confidentiality Obligations
Employees must protect TechCorp's confidential information, including: source code, product plans, customer lists, financial data, pricing, strategic plans, and personnel information. These obligations survive termination of employment.

## NDA Requirements
All employees sign a Non-Disclosure Agreement (NDA) as part of their offer letter. Contractors and vendors must sign an NDA before receiving access to confidential information.

## Open Source Contributions
Employees may contribute to open source projects unrelated to TechCorp's business with manager approval. Contributions of any TechCorp code require explicit written approval from the CTO.

## Violations
Unauthorized disclosure of confidential information or misappropriation of IP may result in immediate termination and legal action. Report suspected violations to Legal at legal@techcorp.io.
""",

"Equity_Vesting_Guide.md": """# Equity Vesting Guide — CONFIDENTIAL — PENDING LEGAL REVIEW

## Equity Program Overview
TechCorp grants Incentive Stock Options (ISOs) and Non-Qualified Stock Options (NSOs) under the 2021 Equity Incentive Plan. All new employees receive an initial option grant.

## Vesting Schedule
Standard vesting: 4-year vesting with a 1-year cliff.
- At 12 months (cliff): 25% of options vest.
- Months 13–48: 1/48th of remaining options vest each month.

## Strike Price
Options are granted at the Fair Market Value (FMV) on the grant date, determined by the most recent 409A valuation.

## Exercise Window
Employees may exercise vested options during employment. Upon termination: standard exercise window is 90 days for ISOs, 10 years for NSOs.
Early exercise: Available for all new grants (83(b) election must be filed within 30 days of exercise).

## Annual Refresh Grants
Performance-based refresh grants are awarded annually in March:
- Outstanding rating: 100% of initial grant, 4-year vest
- Exceeds Expectations: 75% of initial grant
- Meets Expectations: 50% of initial grant

## Liquidity Events
Options become exercisable at an IPO or acquisition. In a change of control, standard double-trigger acceleration applies: 50% vest on acquisition, remaining 50% vest over 12 months if employee is retained.

*Document pending review by legal counsel and board approval.*
""",

"Invoice_and_Expense_Policy.md": """# Invoice and Expense Policy

## Expense Reimbursement
TechCorp reimburses all reasonable, pre-approved business expenses. Submit expenses within 30 days of incurring them through Expensify.

## Approval Limits
- Up to $500: Manager approval only.
- $501–$5,000: Manager + Finance approval.
- Over $5,000: Manager + Finance + VP approval.

## Eligible Expenses
- Travel: Economy class flights, hotels up to $250/night, ground transport.
- Meals: Up to $60/person for client meals, $30/person for internal team meals.
- Software/Tools: Manager pre-approval required. No SaaS tools outside the approved vendor list.
- Home Office (new hire only): Up to $750 for equipment. See Remote Work Policy.
- Co-working Space: Up to $200/month with manager approval.
- Conferences & Training: Covered under the $1,500 annual L&D stipend.

## Ineligible Expenses
Alcohol (except approved client entertainment), personal travel extensions, luxury upgrades (business class without pre-approval), parking tickets, personal subscriptions.

## Receipt Requirements
Original receipts required for all expenses over $25. Credit card statements do not substitute for receipts.

## Reimbursement Timeline
Approved expenses are reimbursed in the next payroll cycle (bi-monthly, 1st and 15th of each month).
""",
}


# ── Public channel definitions ────────────────────────────────────────────────
# dept_filter: "all" | list of dept strings from USERS

PUBLIC_CHANNELS = [
    {"name": "general",          "dept_filter": "all",                                                    "msg_count": 200, "pool": "GENERAL"},
    {"name": "announcements",    "dept_filter": "all",                                                    "msg_count": 30,  "pool": "ANNOUNCE"},
    {"name": "random",           "dept_filter": "all",                                                    "msg_count": 180, "pool": "RANDOM"},
    {"name": "hr-updates",       "dept_filter": "all",                                                    "msg_count": 60,  "pool": "HR"},
    {"name": "engineering",      "dept_filter": ["Engineering", "IT"],                                    "msg_count": 150, "pool": "ENG"},
    {"name": "product",          "dept_filter": ["Product", "Design", "Engineering"],                     "msg_count": 120, "pool": "PRODUCT"},
    {"name": "sales",            "dept_filter": ["Sales"],                                                "msg_count": 100, "pool": "SALES"},
    {"name": "marketing",        "dept_filter": ["Marketing"],                                            "msg_count": 80,  "pool": "MARKETING"},
    {"name": "customer-success", "dept_filter": ["Customer Success"],                                     "msg_count": 80,  "pool": "CS"},
    {"name": "data-analytics",   "dept_filter": ["Analytics", "Product"],                                 "msg_count": 70,  "pool": "ANALYTICS"},
    {"name": "ops-alerts",       "dept_filter": ["Engineering", "IT"],                                    "msg_count": 60,  "pool": "DEVOPS"},
    {"name": "design-feedback",  "dept_filter": ["Design", "Product"],                                    "msg_count": 60,  "pool": "DESIGN"},
]

# ── DM pairs (50 meaningful pairs) ────────────────────────────────────────────

DM_PAIRS = [
    # CEO ↔ VPs
    ("alex.foster",     "sarah.chen"),
    ("alex.foster",     "marcus.williams"),
    ("alex.foster",     "diana.rodriguez"),
    ("alex.foster",     "kevin.obrien"),
    ("alex.foster",     "james.park"),
    # VP cross-functional
    ("sarah.chen",      "marcus.williams"),
    ("sarah.chen",      "kevin.obrien"),
    ("sarah.chen",      "rachel.thompson"),
    ("marcus.williams", "diana.rodriguez"),
    ("marcus.williams", "aisha.johnson"),
    ("diana.rodriguez", "james.park"),
    ("priya.patel",     "marcus.williams"),
    ("priya.patel",     "diana.rodriguez"),
    ("kevin.obrien",    "rachel.thompson"),
    ("kevin.obrien",    "yvonne.king"),
    # Manager ↔ direct report
    ("sarah.chen",      "liam.nguyen"),
    ("sarah.chen",      "felix.braun"),
    ("sarah.chen",      "alex.wu"),
    ("marcus.williams", "emily.davis"),
    ("marcus.williams", "chloe.martin"),
    ("diana.rodriguez", "fiona.brooks"),
    ("diana.rodriguez", "carlos.martinez"),
    ("james.park",      "julia.smith"),
    ("james.park",      "ivan.petrov"),
    ("priya.patel",     "david.kim"),
    ("priya.patel",     "fred.jackson"),
    ("rachel.thompson", "sam.davies"),
    ("aisha.johnson",   "raj.patel"),
    ("aisha.johnson",   "derek.hunt"),
    ("kevin.obrien",    "wendy.foster"),
    ("nina.kowalski",   "abby.foster"),
    # Cross-functional peers
    ("liam.nguyen",     "emily.davis"),
    ("liam.nguyen",     "elena.kovar"),
    ("emily.davis",     "nina.kowalski"),
    ("emily.davis",     "chloe.martin"),
    ("fiona.brooks",    "javier.luna"),
    ("fiona.brooks",    "lucas.ford"),
    ("raj.patel",       "boris.petrov"),
    ("boris.petrov",    "carmen.silva"),
    ("abby.foster",     "ben.santos"),
    ("julia.smith",     "helen.zhao"),
    ("fred.jackson",    "elsa.moore"),
    ("sam.davies",      "jessica.white"),
    ("oscar.lindqvist", "ryan.oconnell"),
    ("tara.okafor",     "elena.kovar"),
    ("zoe.harper",      "lily.zhang"),
    ("felix.braun",     "josh.banks"),
    ("nat.turner",      "helen.zhao"),
    ("ivan.petrov",     "val.brooks"),
    ("derek.hunt",      "boris.petrov"),
]

# ── Message pools ──────────────────────────────────────────────────────────────

MSGS: dict[str, list[str]] = {
"GENERAL": [
    "Good morning everyone! 👋",
    "Congrats to the team on another great quarter!",
    "Reminder: All-hands is this Friday at 2pm. Add your questions to the doc.",
    "Just a heads up — the office in SF will be closed next Monday for the holiday.",
    "Welcome to the team, everyone who joined this month! Excited to work with you all.",
    "Quick reminder to submit your performance self-review by EOD Friday.",
    "Shoutout to @sarah.chen and the engineering team for the flawless deploy yesterday 🚀",
    "The updated expense policy is now live — link in the pinned message.",
    "Don't forget: benefits enrollment closes this Friday. Check your email for the link.",
    "Happy to share that we hit our Q4 ARR target! Amazing work everyone.",
    "Parking reminder: the lot on 3rd St is reserved for visitors on Thursday.",
    "Company swag is available to order — link in #announcements.",
    "Team lunch this Thursday at noon — details in calendar.",
    "Anyone have a recommendation for a good project management book?",
    "Quick PSA: please keep Slack statuses updated when you're out or in deep work.",
    "Great demo day yesterday! So proud of what this team has built.",
    "Our NPS just hit 52 — highest ever. Customers are loving the product.",
    "Reminder that the company handbook has been updated. Worth a skim.",
    "Is anyone else's VPN acting up today? Filed a ticket with IT.",
    "The Q1 roadmap is posted — check #product for details.",
    "Happy Friday everyone! 🎉 Great week.",
    "We're hiring! If you know someone great for the open roles, please refer them.",
    "Today marks 2 years since our Series A. Time flies — thanks for being part of this.",
    "Small wins matter. Every closed deal, every shipped feature, every happy customer. Keep going.",
    "Reminder: all team offsites need to be submitted for budget approval by end of month.",
],
"ANNOUNCE": [
    "📢 We've officially closed our Series B — $45M raised. Thank you to everyone who made this possible.",
    "📢 Q4 results: $3.2M new ARR, 114% of target. Best quarter in company history.",
    "📢 New hire announcement: please welcome our new VP of Engineering joining February 1.",
    "📢 Product update: Dashboard V2 is now live for all users. Check it out!",
    "📢 Company-wide security training is mandatory by January 31. Link in email.",
    "📢 We're moving to a new HRIS system (Rippling) starting March 1. More details to follow.",
    "📢 TechCorp is now SOC 2 Type I certified. Big milestone for the team.",
    "📢 2026 company kickoff is January 6 — attendance is required for all employees.",
    "📢 Announcing our new company values, refined from employee feedback. See attached.",
    "📢 Updated PTO policy now in effect — 20 days annually starting from day 1.",
    "📢 New sales commission plan is live for Q1. Please review with your manager.",
    "📢 Open enrollment for benefits is now open. Deadline: November 30.",
    "📢 TechCorp named to G2's Best Software Companies 2026 list! 🏆",
    "📢 All employees: complete your I-9 re-verification before March 15.",
    "📢 Office hours with the CEO every second Friday at 3pm — open to all.",
],
"RANDOM": [
    "Anyone catch the game last night?",
    "Highly recommend the new ramen place on Market St. Life-changing broth.",
    "It is unacceptable that there are no good bagels in this city.",
    "Who else has been stress-baking during sprint week?",
    "Hot take: standing desks are overrated and I will not be taking questions.",
    "My cat just walked across my keyboard and sent an email to the whole engineering list.",
    "The coffee in the office kitchen is categorically better than the coffee shop downstairs.",
    "Finished the book from last month's book club. 10/10 recommend.",
    "Anyone doing Wordle today? My streak is at risk and I need moral support.",
    "Friday afternoon energy is a different animal.",
    "Confession: I have 47 browser tabs open right now and I'm not closing any.",
    "Does anyone else have a meeting right before lunch every single day?",
    "Just found out you can use ⌘+K in our app to jump anywhere. Game changer.",
    "If anyone needs me I'll be outside touching grass for exactly 15 minutes.",
    "The espresso machine is back in service. Crisis averted.",
    "Long weekend incoming 🙌 Who's got plans?",
    "Working from a coffee shop today. Productivity: questionable. Vibes: immaculate.",
    "Reminder that the #random channel exists for a reason and it is this.",
    "My 2-year-old just joined my standup and gave a more coherent update than I did.",
    "Genuine question: at what point does a work playlist become a full DJ set?",
    "October is the best working-from-home season. Fight me.",
    "New personal rule: no Slack after 8pm. Let's see how long it lasts.",
    "Anyone else feel like Mondays hit different after a long sprint?",
    "Team building activity suggestion: competitive napping.",
    "PSA: the mute button is your friend and you should use it.",
],
"HR": [
    "Reminder: Q1 performance reviews are due by February 28.",
    "Open enrollment for benefits closes this Friday. Don't miss it!",
    "New hire orientation is next Tuesday — managers please ensure your new joiners are registered.",
    "Updated parental leave policy is now in the handbook. 16 weeks for primary caregivers.",
    "The anonymous employee engagement survey is live. It takes 5 minutes and really helps us.",
    "Reminder to submit timesheets by EOD Friday if you're on an hourly or contractor arrangement.",
    "The L&D stipend ($1,500) resets on January 1 — use it or lose it!",
    "Security awareness training completion rate is at 87%. Please complete if you haven't!",
    "New expense policy is live. Key change: receipts required for anything over $25.",
    "Hiring reminder: employee referral bonuses are $2,500 for any role filled through referral.",
    "Just a note that mental health days are part of your sick leave — please use them.",
    "Reminder to update your emergency contact info in Rippling.",
    "Career development conversations should happen with your manager at the mid-year check-in.",
    "New: TechCorp now offers a co-working stipend of $200/month. See the remote work policy.",
    "Happy work anniversary to everyone who hit their 1-year mark this month! 🎂",
],
"ENG": [
    "PR #482 is up for review — auth refactor. Need 2 approvals before EOD.",
    "Heads up: staging is down for maintenance from 6-8pm tonight.",
    "Just merged the async migration for the Project Service. Latency is looking great.",
    "Reminder: no deploys to production after 3pm on Fridays without VP approval.",
    "The load test for 10x traffic passed. We're good for the Q2 launch.",
    "Anyone know why the CI is flaky on the notification service tests? Third time this week.",
    "Dependency update PR is up — upgrades 14 packages, all security patches.",
    "P95 API latency is down to 87ms this week. Sprint goal achieved 🎉",
    "The tech debt sprint starts next Monday. Please add your top items to the Linear board.",
    "Postmortem for last week's incident is posted in the Engineering Docs collection.",
    "New ADR (Architecture Decision Record) posted: migrating from REST to gRPC internally.",
    "Quick reminder: all PRs need a test coverage note in the description.",
    "Database indexes added to tasks table. Query time went from 340ms to 12ms.",
    "Please don't push directly to main — even for tiny fixes. The CI catches things.",
    "Sprint velocity for last sprint: 47 points. Best sprint all quarter.",
    "Production deploy complete — v2.15.0 is live. No issues reported.",
    "Code review turnaround is averaging 2.1 days. Goal is 1.5 — let's keep improving.",
    "New runbook added: how to handle PgBouncer pool exhaustion.",
    "The ElasticSearch migration to self-hosted is kicking off next sprint.",
    "Reminder: vulnerability scan flagged 2 medium CVEs. PRs for patches are in review.",
],
"PRODUCT": [
    "Dashboard V2 spec is finalized — engineering kickoff is Monday.",
    "User research session yesterday surfaced a huge insight about how PMs actually use the dashboard.",
    "Q2 roadmap is locked. See the Product Roadmap doc in the collection for details.",
    "NPS hit 52 this quarter — up 8 points from last quarter. The notification digest clearly helped.",
    "The A/B test on onboarding checklist is showing 23% improvement. Shipping it.",
    "Mobile app soft launch is set for Feb 14. All hands on deck for UAT next week.",
    "Competitive analysis updated — Linear just shipped a mobile app. Noted and monitoring.",
    "Feature flag for Dashboard V2 is live in staging. Please test and share feedback.",
    "Sprint review is Thursday at 3pm. All PMs please have your demo ready.",
    "Roadmap thread: should we move SSO to Q1 or keep it in Q2? Eng says it's 2 weeks of work.",
    "PRD for NextGen Analytics is ready for engineering review.",
    "Product weekly notes are posted in Notion. Key decisions: ship CSV export, delay guest roles.",
    "Just synced with 3 enterprise customers — all confirmed Dashboard V2 is their top ask.",
    "The design system handoff for Dashboard V2 components is complete. Thanks @nina.kowalski!",
    "Reminder: feature freeze for the mobile launch is in 10 days. No new scope.",
],
"SALES": [
    "Closed Apex Dynamics — $240K ARR, 3-year deal. Big win for the enterprise team! 🎊",
    "Pipeline review is Monday at 9am. Please update your deals in Salesforce before then.",
    "New objection handling guide is in the Sales & Marketing collection — required reading.",
    "Anyone else getting objections about the mobile app? Pointing them to the Q1 roadmap.",
    "Lost Veridian Corp to Linear. Reason: they're a pure engineering team. Noted in Salesforce.",
    "Reminder: discount requests over 15% need director approval. Please don't promise before asking.",
    "SaaStr sponsorship confirmed for May. We'll need 4 people to staff the booth.",
    "Trial-to-paid conversion is at 31% this month. Company record!",
    "New case study posted: Brightline Digital. Use it for agency prospects.",
    "Q4 forecast is looking strong — 108% of target with 3 weeks left in the quarter.",
    "Heads up: Acme Corp's renewal is up in 60 days. @david.kim let's sync on their health.",
    "New champion at Meridian — the old contact left. Need to multi-thread immediately.",
    "Sales kickoff dates confirmed: January 20-22. Block your calendars.",
    "Reminder to log all customer calls in Salesforce within 24 hours.",
    "Big shoutout to @fiona.brooks for the largest deal in company history! 🥇",
    "Win/loss tracker updated: we're beating Asana at 44% win rate now.",
    "Proposal template has been updated with the new pricing. Please use v2 going forward.",
    "Enterprise pipeline for Q1: $9.4M. Looking good.",
],
"MARKETING": [
    "Blog post 'The 2026 Guide to PM Software' is live. Please share on LinkedIn!",
    "SaaStr confirmed our sponsorship. Booth design brief goes out this week.",
    "Q1 campaign kickoff deck is ready — review before Thursday's meeting.",
    "Organic traffic hit 82K MAUs last month. New record!",
    "Email open rate on the onboarding sequence is up to 47%. Drip is working.",
    "PR agency sent the first draft of the Series B press release. Review needed by COB.",
    "New case study published: Apex Dynamics. Sales team please use it in your decks.",
    "Heads up: our G2 rating dropped slightly. Let's get a push on review requests from CS.",
    "Product Hunt launch for mobile app is set for Feb 14. Prep checklist in Notion.",
    "Social media calendar for Q1 is in the Content Hub. Team please review by Friday.",
    "Competitor Monday.com just launched a big brand campaign. Keeping an eye on it.",
    "Brand guidelines v2 are published. Old logo versions should be retired by end of month.",
    "Webinar signups for 'Getting the Most from TechCorp' hit 340. Good leading indicator.",
    "Monthly marketing metrics are in the Analytics collection. Highlights in Thursday's meeting.",
    "SEO audit complete — 12 quick wins identified. Assigning to the content team now.",
],
"CS": [
    "Onboarding call with Meridian Health went great — they're really engaged.",
    "Churn alert: Brightfield Inc hasn't logged in for 21 days. Reaching out today.",
    "New customer health score dashboard is live in Salesforce. Check your accounts!",
    "Renewal reminder: 4 accounts up for renewal in the next 30 days. All flagged in Salesforce.",
    "Customer advisory board is Feb 5. We need 3 power users to present their use cases.",
    "Just got off a call with Apex Dynamics — they want to expand from 25 to 80 seats! 🎉",
    "New feature request logged: bulk task assignment. Added to the product backlog.",
    "Onboarding NPS from last cohort: 71. New high!",
    "Heads up: the import tool has a bug with CSV files over 10MB. Engineering is aware.",
    "Q4 customer health: 78% green, 15% yellow, 7% red. Let's focus on the yellow accounts.",
    "New playbook for handling data migration questions is in the CS docs.",
    "EBR template updated — new slide for the AI features roadmap. Use it in Q1 reviews.",
    "Shoutout to @ned.jones for getting Meridian to a 5-star G2 review this week!",
    "Product is asking for 3 customers willing to beta test the new analytics module. Any candidates?",
    "All CS team members: please complete the security training by end of week.",
],
"ANALYTICS": [
    "Weekly metrics report is out. MAU: 42K (+8% WoW). Activation rate: 50.4%.",
    "The BigQuery pipeline had a 2-hour delay last night. Root cause: storage quota hit. Fixed.",
    "New dashboard in Looker: funnel analysis by acquisition channel. Link in pinned.",
    "Data request from Sales: they need pipeline velocity by deal size. ETA: tomorrow.",
    "Heads up: the trial_started event was double-firing for 6 hours on Wednesday. Patching now.",
    "Q4 cohort analysis is ready. Retention at D30 improved from 34% to 41% YoY.",
    "The lead scoring model is in draft — review in the Sales & Marketing collection.",
    "Feature adoption data for Dashboard V2 beta: 67% of users created a custom view. Strong signal.",
    "New data model for analytics events is in review. Feedback needed before Friday.",
    "A/B test results for onboarding checklist are statistically significant. Recommending to ship.",
    "LTV/CAC ratio is at 7.4x — up from 6.1x in Q3. Efficiency is improving.",
    "Churn prediction model retrained on Q4 data. Accuracy improved from 71% to 78%.",
    "Revenue attribution model updated — organic is 34% of new ARR. SEO is working.",
    "The Stripe webhook for payment events is now wired into BigQuery in real time.",
],
"DEVOPS": [
    "✅ Production deploy v2.15.0 — complete. No rollback needed.",
    "⚠️ Staging environment memory pressure — investigating now.",
    "✅ GKE autoscaling verified under 5x load. Pods scaled from 3 to 14 and back cleanly.",
    "🔴 ALERT: Auth service 500 rate spiked to 12%. Investigating. (@sarah.chen paged)",
    "✅ Auth service incident resolved. Root cause: JWT rotation script. See postmortem.",
    "Reminder: deployment freeze is in effect from Dec 24 – Jan 2.",
    "GCP committed use discounts renewed — saving ~$180K/year.",
    "ElasticSearch self-hosted migration is in staging. Performance is better than managed.",
    "New GKE node pool with spot instances is live. Saving ~$8K/month.",
    "Certificate renewal for api.techcorp.io completed. Expires in 90 days again.",
    "PgBouncer pool was maxed out this morning during the traffic spike. Pool size increased.",
    "CloudFlare DDoS protection triggered on 3 IPs. Blocked. No impact.",
    "Backup restore test passed. RTO: 14 minutes. RPO: <5 minutes.",
    "Dependency update: upgraded to PostgreSQL 15 in staging. Zero issues.",
    "On-call rotation updated — see PagerDuty for new schedule.",
],
"DESIGN": [
    "Dashboard V2 mockups are ready for feedback. Figma link in thread 🧵",
    "Component library updated — new input states and loading skeleton added.",
    "Design review for the mobile app onboarding flow is Thursday at 2pm.",
    "Quick question: should the empty state illustration be in color or grayscale?",
    "Accessibility audit complete — 3 contrast issues found and fixed.",
    "New icons added to the design system. See Figma → Icons / v3.",
    "The user research findings are in — pain point #1 is dashboard customization. Validating our bet.",
    "Motion design spec for the loading states is in Figma. Handoff ready for eng.",
    "Brand guidelines v2 are live. Please update any materials using the old logo.",
    "Weekly design crit is Tuesday at 11am. All designers + PMs welcome.",
    "Usability test on the new nav showed 9/10 users found the settings in <10 seconds. Win!",
    "Typography scale updated to match new brand guidelines. Inter is staying.",
    "Prototype for the AI insights feature is ready. Sharing with PM for review.",
    "Question for the room: do we prefer a modal or a drawer for the new dashboard config panel?",
    "Dark mode is officially on the roadmap for Q3! Starting research this sprint.",
],
"DM": [
    "Hey, do you have 15 min today to sync on the Q2 roadmap?",
    "Just flagging this deal — looks like a potential upsell opportunity.",
    "Can you take a look at this PR when you get a chance? No rush.",
    "Quick question on the budget — is there flexibility for the new tool?",
    "Thanks for covering my standup yesterday 🙏",
    "Are you joining the offsite next month?",
    "The customer is asking about mobile app timelines — can I share the Q1 date?",
    "Can you review the proposal before I send it? I think the pricing is slightly off.",
    "Just wanted to say — great job on the presentation today.",
    "Any blockers on your end for the sprint?",
    "Heads up: I'm taking Friday off, you'll need to cover the on-call handoff.",
    "Did you see the NPS numbers? 52 is incredible.",
    "Quick sync today at 3pm? I want to walk through the incident before the postmortem.",
    "I have a conflict with the 2pm — can we move it 30 min later?",
    "The customer wants a reference call. Do you have someone from a similar company?",
    "Can you share the contract template? The legal folder access isn't working for me.",
    "Are we still on for the 1:1 tomorrow?",
    "Flagging this: the customer mentioned a competitor is undercutting us by 20%.",
    "Do you have the updated deck? I think sales sent an old version.",
    "Great catch on that edge case in the PR — almost missed it.",
    "Quick check-in: how are you feeling about the sprint? We're at 60% velocity mid-week.",
    "Can I get your take on this feature request before I log it in Linear?",
    "Reminder about the interview we're doing Thursday — you're the technical screener.",
    "The onboarding doc needs a section on the new SSO flow — can you draft it?",
    "Thanks for the introduction — had a great call with them.",
],
}


# ── DM pair message counts ─────────────────────────────────────────────────────
DM_MSG_COUNT = (15, 35)   # (min, max) messages per DM thread


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

        # Attach any missing permissions
        existing_perm_names = {p.name for p in role.permissions}
        for pname in perm_names:
            if pname not in existing_perm_names and pname in perm_map:
                role.permissions.append(perm_map[pname])

        role_map[role_name] = role
    await session.flush()
    return role_map


async def seed_company(session) -> str:
    """Create or upsert the TechCorp Inc. Company record. Returns the company id."""
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
        plan="enterprise",
        max_users=200,
        max_storage_gb=500,
        owner_email=f"alex.foster@{COMPANY['domain']}",
        brand_color="#2563EB",
        notes="TechCorp Inc. — primary engineering & SaaS company tenant",
    )
    session.add(company)
    await session.flush()
    print(f"  [company]     created '{company.name}' (id={company.id})")
    return company.id


async def seed_users(session, role_map: dict[str, Role], company_id: str) -> list[User]:
    """Create 100 TechCorp users. Skips existing usernames."""
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
    """Create 12 teams and their memberships. Skips existing team names."""
    # Build username → user_id lookup
    result = await session.execute(select(User.username, User.id))
    user_id_map: dict[str, str] = {row[0]: row[1] for row in result.all()}

    if not user_id_map:
        print("  [warn] no users found — run Phase 1 first")
        return []

    # Team creation timestamps staggered from 2024-01-15
    base_ts = datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc)

    teams_created: list[Team] = []
    total_memberships = 0
    skipped_teams = 0

    for i, tdata in enumerate(TEAMS):
        # Idempotency — skip if team already exists
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
        await session.flush()  # get team.id before creating memberships

        # De-duplicate member list (some teams repeat a username for clarity)
        seen: set[str] = set()
        for username in tdata["members"]:
            if username in seen:
                continue
            seen.add(username)

            member_id = user_id_map.get(username)
            if not member_id:
                continue  # user not seeded yet — silently skip

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
    """Create 5 collections. Returns name→id map for use by Phase 4."""
    result = await session.execute(select(User.username, User.id))
    user_id_map: dict[str, str] = {row[0]: row[1] for row in result.all()}

    base_ts = datetime(2024, 2, 1, 10, 0, tzinfo=timezone.utc)
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

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads" / "company_one"


async def seed_documents(session) -> dict[str, str]:
    """Create 50 document records + write .md files. Returns filename→doc_id map."""
    from src.models.document import Document, DocumentTeamAccess, DocumentStatusEnum, VisibilityEnum

    # Build lookup maps
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

    base_ts = datetime(2025, 1, 10, 9, 0, tzinfo=timezone.utc)
    created = skipped = 0
    doc_id_map: dict[str, str] = {}

    for i, ddata in enumerate(DOCUMENTS):
        fname = ddata["filename"]

        if fname in existing_filenames:
            skipped += 1
            # Still build the id map for existing docs
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

        # Write the .md file
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

        # DocumentTeamAccess rows
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

    # Probe Ollama before starting so we fail fast
    try:
        await embedding_svc.embed_text("ping")
    except Exception as e:
        print(f"  [skip] Ollama not reachable ({e}). Run with --skip-embeddings to skip Phase 5.")
        await engine.dispose()
        return

    # Gather documents to ingest (ready + not yet embedded)
    async with factory() as session:
        result = await session.execute(
            select(Document).where(
                Document.status == "ready",
                Document.chunk_count == 0,
                Document.file_path.is_not(None),
            )
        )
        docs = list(result.scalars().all())

        # Pre-fetch team access per document
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
    # ── build lookup maps ──────────────────────────────────────────────────────
    user_res  = await session.execute(select(User.username, User.id))
    user_rows = user_res.all()
    uid_map: dict[str, str] = {r[0]: r[1] for r in user_rows}   # username → id

    # dept → list of (user_id, username)
    dept_map: dict[str, list[tuple[str, str]]] = {}
    for username, _title, dept, _role in USERS:
        uid = uid_map.get(username)
        if not uid:
            continue
        dept_map.setdefault(dept, []).append((uid, username))
        dept_map.setdefault("all", []).append((uid, username))

    # team name → (team_id, [(user_id, username)])
    team_res = await session.execute(select(Team.name, Team.id))
    team_id_map: dict[str, str] = {r[0]: r[1] for r in team_res.all()}

    from src.models.team import TeamMembership as TM
    tm_res = await session.execute(select(TM.team_id, TM.user_id))
    team_members: dict[str, list[tuple[str, str]]] = {}
    for team_id, user_id in tm_res.all():
        uname = next((u for u, i in uid_map.items() if i == user_id), user_id)
        team_members.setdefault(team_id, []).append((user_id, uname))

    # existing channel names (for idempotency)
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
            created_at=datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc),
        )
        session.add(ch)
        await session.flush()

        for uid, _ in members:
            session.add(ChannelMember(channel_id=ch.id, user_id=uid,
                                      joined_at=datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc)))

        for msg in _make_messages(ch.id, members, cdata["pool"], cdata["msg_count"]):
            session.add(msg)

        total_channels += 1
        total_members  += len(members)
        total_messages += cdata["msg_count"]

    # ── 2. Group channels (one per team) ──────────────────────────────────────
    team_channel_names = {
        "Engineering — Backend":   "backend-team",
        "Engineering — Frontend":  "frontend-team",
        "Engineering — DevOps":    "devops-team",
        "Product — Core":          "product-core",
        "Product — Growth":        "product-growth",
        "Sales — Enterprise":      "sales-enterprise",
        "Sales — SMB":             "sales-smb",
        "Marketing — Content":     "marketing-content",
        "Marketing — Demand Gen":  "marketing-demandgen",
        "Customer Success":        "customer-success-team",
        "Finance & Legal":         "finance-legal",
        "Executive Leadership":    "exec-leadership",
    }
    group_pool_map = {
        "backend-team":          "ENG",
        "frontend-team":         "ENG",
        "devops-team":           "DEVOPS",
        "product-core":          "PRODUCT",
        "product-growth":        "PRODUCT",
        "sales-enterprise":      "SALES",
        "sales-smb":             "SALES",
        "marketing-content":     "MARKETING",
        "marketing-demandgen":   "MARKETING",
        "customer-success-team": "CS",
        "finance-legal":         "GENERAL",
        "exec-leadership":       "GENERAL",
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
            created_at=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
        )
        session.add(ch)
        await session.flush()

        for uid, _ in members:
            session.add(ChannelMember(channel_id=ch.id, user_id=uid,
                                      joined_at=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)))

        msg_count = random.randint(80, 130)
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
# Date window: Jan 20 – Mar 28, 2026  (today = Mar 14, 2026 per system clock)
# weekday: 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri

_ENG_STANDUP = [
    "sarah.chen","liam.nguyen","elena.kovar","mia.carter","josh.banks",
    "priya.mehta","oscar.lindqvist","tara.okafor","felix.braun","zoe.harper",
    "ryan.oconnell","alex.wu","mike.chen","dana.walsh","jade.harris",
    "noah.kim","lily.zhang","sam.petrov","chris.moore","bella.ross",
    "theo.patel","paul.reed","it.admin",
]
_BACKEND_SYNC = [
    "sarah.chen","liam.nguyen","elena.kovar","priya.mehta","oscar.lindqvist",
    "tara.okafor","ryan.oconnell","alex.wu","mike.chen","dana.walsh","it.admin",
]
_FRONTEND_SYNC = [
    "sarah.chen","mia.carter","zoe.harper","lily.zhang","jade.harris",
    "noah.kim","bella.ross","theo.patel","anna.schmidt","cate.williams","ella.park",
]
_DEVOPS_SYNC = [
    "sarah.chen","josh.banks","felix.braun","chris.moore","sam.petrov","paul.reed","it.admin",
]
_PRODUCT_WEEKLY = [
    "marcus.williams","emily.davis","chloe.martin","nat.turner","leo.nguyen",
    "iris.schmidt","nina.kowalski","abby.foster","ben.santos","ethan.bailey",
    "ben.wright","amy.liu","jake.cooper",
]
_SALES_WEEKLY = [
    "diana.rodriguez","carlos.martinez","fiona.brooks","hassan.ali","ingrid.berg",
    "javier.luna","kate.young","lucas.ford","rick.vasquez","mia.johnson",
    "nadia.petrov","omar.farouk","penny.shaw","quinn.taylor",
]
_CS_WEEKLY = [
    "priya.patel","david.kim","elsa.moore","fred.jackson","linda.garcia",
    "mary.wilson","ned.jones","olivia.taylor","paul.adams","gwen.lewis",
    "jan.white","kyle.thomas",
]
_MARKETING_WEEKLY = [
    "james.park","julia.smith","ivan.petrov","helen.zhao","sofia.lee",
    "sue.chen","tim.davidson","uma.patel","val.brooks","ken.brown",
]
_DATA_WEEKLY = [
    "aisha.johnson","raj.patel","boris.petrov","carmen.silva","derek.hunt",
    "eve.morgan","frank.zhang","gabby.harris","harry.chen",
]
_EXEC_SYNC = [
    "alex.foster","sarah.chen","marcus.williams","diana.rodriguez",
    "kevin.obrien","james.park","priya.patel","rachel.thompson","aisha.johnson",
]
_ALL_HANDS = [u for u, *_ in USERS]   # all 100 usernames
_SPRINT_PLAN = list({*_BACKEND_SYNC, *_FRONTEND_SYNC, *_DEVOPS_SYNC,
                     *_PRODUCT_WEEKLY})
_SPRINT_REVIEW = list({*_SPRINT_PLAN,
                       "diana.rodriguez","fiona.brooks","priya.patel"})
_RETRO = list({*_BACKEND_SYNC, *_FRONTEND_SYNC, *_DEVOPS_SYNC})


# Recurring event definitions
# "cadence": "daily_weekday" | "weekly" | "biweekly"
# "weekday": 0=Mon…4=Fri  (for biweekly, also supply "week_parity": 0 or 1)

RECURRING_EVENTS = [
    {
        "title": "Engineering Daily Standup",
        "description": "Quick daily sync: what did you ship yesterday, what are you working on today, any blockers?",
        "organizer": "sarah.chen",
        "cadence": "daily_weekday",
        "hour": 9, "minute": 0, "duration_mins": 15,
        "attendees": _ENG_STANDUP,
        "room_name_prefix": None,
    },
    {
        "title": "Backend Team Sync",
        "description": "Weekly deep-dive on backend architecture, PR reviews, and infrastructure work.",
        "organizer": "liam.nguyen",
        "cadence": "weekly", "weekday": 0,
        "hour": 10, "minute": 0, "duration_mins": 60,
        "attendees": _BACKEND_SYNC,
        "room_name_prefix": None,
    },
    {
        "title": "Frontend Team Sync",
        "description": "Weekly review of frontend PRs, design handoffs, and browser performance.",
        "organizer": "mia.carter",
        "cadence": "weekly", "weekday": 1,
        "hour": 10, "minute": 0, "duration_mins": 60,
        "attendees": _FRONTEND_SYNC,
        "room_name_prefix": None,
    },
    {
        "title": "DevOps Weekly",
        "description": "Infra health, on-call review, upcoming deploy schedule, and cost tracking.",
        "organizer": "felix.braun",
        "cadence": "weekly", "weekday": 2,
        "hour": 11, "minute": 0, "duration_mins": 45,
        "attendees": _DEVOPS_SYNC,
        "room_name_prefix": None,
    },
    {
        "title": "Product Weekly",
        "description": "Roadmap updates, spec reviews, design crits, and cross-team alignment.",
        "organizer": "marcus.williams",
        "cadence": "weekly", "weekday": 2,
        "hour": 14, "minute": 0, "duration_mins": 60,
        "attendees": _PRODUCT_WEEKLY,
        "room_name_prefix": None,
    },
    {
        "title": "Sales Weekly Forecast",
        "description": "Pipeline review, deal updates, forecast call, and win/loss debrief.",
        "organizer": "diana.rodriguez",
        "cadence": "weekly", "weekday": 0,
        "hour": 9, "minute": 0, "duration_mins": 60,
        "attendees": _SALES_WEEKLY,
        "room_name_prefix": None,
    },
    {
        "title": "CS Weekly Sync",
        "description": "Customer health review, escalations, onboarding pipeline, and renewal tracking.",
        "organizer": "priya.patel",
        "cadence": "weekly", "weekday": 1,
        "hour": 11, "minute": 0, "duration_mins": 60,
        "attendees": _CS_WEEKLY,
        "room_name_prefix": None,
    },
    {
        "title": "Marketing Weekly",
        "description": "Campaign performance, content calendar review, and pipeline generation update.",
        "organizer": "james.park",
        "cadence": "weekly", "weekday": 3,
        "hour": 11, "minute": 0, "duration_mins": 60,
        "attendees": _MARKETING_WEEKLY,
        "room_name_prefix": None,
    },
    {
        "title": "Data Weekly",
        "description": "Metrics review, active analyses, data requests, and model updates.",
        "organizer": "aisha.johnson",
        "cadence": "weekly", "weekday": 4,
        "hour": 14, "minute": 0, "duration_mins": 45,
        "attendees": _DATA_WEEKLY,
        "room_name_prefix": None,
    },
    {
        "title": "Exec Leadership Sync",
        "description": "Cross-functional strategy, OKR tracking, and key decisions requiring exec alignment.",
        "organizer": "alex.foster",
        "cadence": "weekly", "weekday": 0,
        "hour": 8, "minute": 0, "duration_mins": 60,
        "attendees": _EXEC_SYNC,
        "room_name_prefix": None,
    },
    {
        "title": "All Hands",
        "description": "Monthly company all-hands: metrics, roadmap updates, Q&A with leadership, team shoutouts.",
        "organizer": "alex.foster",
        "cadence": "monthly_first_friday",
        "hour": 14, "minute": 0, "duration_mins": 90,
        "attendees": _ALL_HANDS,
        "room_name_prefix": "all-hands",
    },
    {
        "title": "Sprint Planning",
        "description": "Biweekly sprint planning: pull issues from backlog, estimate, assign, and commit to sprint goals.",
        "organizer": "sarah.chen",
        "cadence": "biweekly", "weekday": 0, "week_parity": 0,
        "hour": 13, "minute": 0, "duration_mins": 120,
        "attendees": _SPRINT_PLAN,
        "room_name_prefix": None,
    },
    {
        "title": "Sprint Review",
        "description": "Biweekly sprint demo: engineering demos shipped features to stakeholders.",
        "organizer": "sarah.chen",
        "cadence": "biweekly", "weekday": 4, "week_parity": 1,
        "hour": 15, "minute": 0, "duration_mins": 60,
        "attendees": _SPRINT_REVIEW,
        "room_name_prefix": "sprint-review",
    },
    {
        "title": "Retrospective",
        "description": "Engineering retrospective: what went well, what didn't, and one concrete action for next sprint.",
        "organizer": "sarah.chen",
        "cadence": "biweekly", "weekday": 4, "week_parity": 1,
        "hour": 16, "minute": 0, "duration_mins": 60,
        "attendees": _RETRO,
        "room_name_prefix": None,
    },
]

# One-off events: absolute datetime (UTC), organizer, attendee list
ONEOFF_EVENTS = [
    {
        "title": "Q1 2026 Company Kickoff",
        "description": "Full-day kickoff: 2025 year in review, 2026 strategy, team breakouts, and celebration dinner.",
        "organizer": "alex.foster",
        "start": datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 1, 6, 18, 0, tzinfo=timezone.utc),
        "attendees": _ALL_HANDS,
        "room_name": "company-kickoff-2026",
    },
    {
        "title": "Board Meeting Q1",
        "description": "Q4 2025 results, 2026 plan presentation, and board business.",
        "organizer": "alex.foster",
        "start": datetime(2026, 2, 15, 10, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 2, 15, 13, 0, tzinfo=timezone.utc),
        "attendees": [*_EXEC_SYNC, "kevin.obrien", "wendy.foster"],
        "room_name": None,
    },
    {
        "title": "Engineering Offsite — Day 1",
        "description": "Team building, architecture deep-dive, and 2026 technical roadmap workshop.",
        "organizer": "sarah.chen",
        "start": datetime(2026, 2, 20, 9, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 2, 20, 18, 0, tzinfo=timezone.utc),
        "attendees": list({*_BACKEND_SYNC, *_FRONTEND_SYNC, *_DEVOPS_SYNC}),
        "room_name": None,
    },
    {
        "title": "Engineering Offsite — Day 2",
        "description": "Hackathon, tech debt sprint, and team dinner.",
        "organizer": "sarah.chen",
        "start": datetime(2026, 2, 21, 9, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 2, 21, 18, 0, tzinfo=timezone.utc),
        "attendees": list({*_BACKEND_SYNC, *_FRONTEND_SYNC, *_DEVOPS_SYNC}),
        "room_name": None,
    },
    {
        "title": "Sales Kickoff (SKO) — Day 1",
        "description": "Sales kickoff: new comp plan, playbook training, product roadmap briefing, and team awards.",
        "organizer": "diana.rodriguez",
        "start": datetime(2026, 1, 20, 9, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 1, 20, 18, 0, tzinfo=timezone.utc),
        "attendees": _SALES_WEEKLY,
        "room_name": None,
    },
    {
        "title": "New Employee Orientation",
        "description": "Onboarding for new hires: company overview, tools setup, benefits enrollment, and team intros.",
        "organizer": "rachel.thompson",
        "start": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 1, 15, 16, 0, tzinfo=timezone.utc),
        "attendees": ["rachel.thompson","sam.davies","it.admin","jade.harris","noah.kim","lily.zhang","paul.reed","theo.patel"],
        "room_name": "orientation-jan2026",
    },
    {
        "title": "Product Demo Day",
        "description": "Engineering and Product demo all features shipped in Q1 2026 to the full company.",
        "organizer": "marcus.williams",
        "start": datetime(2026, 2, 28, 15, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 2, 28, 17, 0, tzinfo=timezone.utc),
        "attendees": _ALL_HANDS,
        "room_name": "product-demo-day-q1",
    },
    {
        "title": "SOC 2 Audit Prep",
        "description": "Review SOC 2 Type II readiness: open controls, evidence collection, and auditor briefing schedule.",
        "organizer": "kevin.obrien",
        "start": datetime(2026, 2, 10, 14, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 2, 10, 15, 30, tzinfo=timezone.utc),
        "attendees": [*_BACKEND_SYNC, *_EXEC_SYNC, "yvonne.king","wendy.foster"],
        "room_name": None,
    },
    {
        "title": "Company-Wide Security Training",
        "description": "Mandatory annual security awareness training covering phishing, data handling, and incident reporting.",
        "organizer": "it.admin",
        "start": datetime(2026, 1, 30, 11, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 1, 30, 13, 0, tzinfo=timezone.utc),
        "attendees": _ALL_HANDS,
        "room_name": "security-training-2026",
    },
    {
        "title": "Budget Review H1 2026",
        "description": "Finance and executive review of H1 budget allocation, headcount plan, and spend-to-date.",
        "organizer": "kevin.obrien",
        "start": datetime(2026, 1, 25, 13, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 1, 25, 14, 30, tzinfo=timezone.utc),
        "attendees": [*_EXEC_SYNC, "wendy.foster","tom.harris"],
        "room_name": None,
    },
    {
        "title": "Team Building — SF Outing",
        "description": "Company team building event at Golden Gate Park. Lunch, activities, and team photos.",
        "organizer": "rachel.thompson",
        "start": datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 3, 7, 17, 0, tzinfo=timezone.utc),
        "attendees": _ALL_HANDS,
        "room_name": None,
    },
    {
        "title": "Customer Advisory Board",
        "description": "Quarterly CAB meeting: product roadmap preview, customer panel, and NPS discussion.",
        "organizer": "marcus.williams",
        "start": datetime(2026, 2, 5, 13, 0, tzinfo=timezone.utc),
        "end":   datetime(2026, 2, 5, 15, 0, tzinfo=timezone.utc),
        "attendees": [*_PRODUCT_WEEKLY, *_CS_WEEKLY[:4], *_EXEC_SYNC[:3]],
        "room_name": "customer-advisory-board",
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
        # Advance cursor to the first matching weekday
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
        # First Friday of each month in the window
        y, mo = window_start.year, window_start.month
        while True:
            # Find first Friday of this month
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
    """Create recurring + one-off calendar events with attendees."""
    # User lookup
    user_res = await session.execute(select(User.username, User.id))
    uid_map: dict[str, str] = {r[0]: r[1] for r in user_res.all()}

    # Idempotency: existing (title, start_time) pairs
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
        # de-dup attendees
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

    # Recurring events
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

    # One-off events
    for ev in ONEOFF_EVENTS:
        _add_event(
            ev["title"], ev["description"],
            ev["organizer"], ev["start"], ev["end"],
            list(set(ev["attendees"])), ev.get("room_name"),
        )

    await session.flush()
    print(f"  [calendar]    {total_events} events, {total_attendees} attendee rows")


# ── Phase 8: RAG Conversations ───────────────────────────────────────────────
# Each template is assigned to multiple users → ~200 total conversations.
# exchanges: list of (user_q, assistant_a, [source_filenames])
# Each template is shown to avg 3-4 users.

CONV_TEMPLATES = [
    # ── HR Policy (10) ───────────────────────────────────────────────────────
    {
        "title": "PTO policy for new hires",
        "collection": "HR & People Ops",
        "exchanges": [
            ("What is the PTO policy for employees hired this year?",
             "Full-time employees receive 20 days (160 hours) of PTO per year, accruing at 1.67 days per month starting from day one. Unused PTO rolls over up to 5 days at the end of each calendar year.",
             ["PTO_and_Leave_Policy.md"]),
            ("Is there a waiting period before I can use PTO?",
             "No waiting period. PTO accrues from day one, so you can use accrued days as soon as they are available.",
             ["PTO_and_Leave_Policy.md"]),
        ],
    },
    {
        "title": "Parental leave details",
        "collection": "HR & People Ops",
        "exchanges": [
            ("How much parental leave does TechCorp offer?",
             "Primary caregivers receive 16 weeks of fully paid parental leave. Secondary caregivers receive 6 weeks. Leave can be taken at any time within the first 12 months after birth, adoption, or foster placement.",
             ["PTO_and_Leave_Policy.md", "Employee_Handbook_2026.md"]),
        ],
    },
    {
        "title": "Benefits enrollment deadline",
        "collection": "HR & People Ops",
        "exchanges": [
            ("When does benefits enrollment close and what's included?",
             "Benefits open enrollment runs each November with a November 30 deadline. The 2026 package includes Blue Shield PPO, Kaiser HMO, or an HSA-eligible HDHP for health; Delta Dental; VSP Vision; a 401(k) with 4% company match; and a $600 annual wellness stipend.",
             ["Benefits_Guide_2026.md"]),
        ],
    },
    {
        "title": "Performance review rating scale",
        "collection": "HR & People Ops",
        "exchanges": [
            ("What is the performance review rating scale?",
             "Reviews use a 1–5 scale: 1 = Below Expectations, 2 = Developing, 3 = Meets Expectations, 4 = Exceeds Expectations, 5 = Outstanding. Reviews cover four dimensions: Impact, Collaboration, Growth, and Execution.",
             ["Performance_Review_Template.md"]),
            ("When do reviews happen?",
             "Annual reviews are completed in February. Mid-year check-ins occur in August. Managers submit reviews two weeks before the review meeting.",
             ["Performance_Review_Template.md"]),
        ],
    },
    {
        "title": "Remote work equipment stipend",
        "collection": "HR & People Ops",
        "exchanges": [
            ("Is there a stipend for setting up a home office?",
             "Yes. New hires receive a one-time $750 home office stipend within their first 90 days. Eligible purchases include a monitor, keyboard, webcam, desk, and chair. Submit receipts through Expensify.",
             ["Remote_Work_Policy.md"]),
        ],
    },
    {
        "title": "Learning and development budget",
        "collection": "HR & People Ops",
        "exchanges": [
            ("How do I use the learning and development stipend?",
             "All full-time employees receive a $1,500 annual L&D stipend for courses, conferences, books, and certifications. Submit requests through the L&D portal and get manager approval. The budget resets on January 1 each year.",
             ["Benefits_Guide_2026.md", "Employee_Handbook_2026.md"]),
        ],
    },
    {
        "title": "Expense reimbursement process",
        "collection": "HR & People Ops",
        "exchanges": [
            ("How do I submit an expense report?",
             "Submit expenses within 30 days through Expensify. Receipts are required for anything over $25. Manager approval is needed for amounts up to $500; Finance approval is added for $501–$5,000. Reimbursements are processed in the next payroll cycle (1st and 15th of each month).",
             ["Invoice_and_Expense_Policy.md"]),
        ],
    },
    {
        "title": "Sick leave and mental health days",
        "collection": "HR & People Ops",
        "exchanges": [
            ("Can I use sick leave for mental health days?",
             "Yes. Mental health days count as sick leave. Employees receive 10 days of sick leave per year, separate from PTO. You don't need to provide a doctor's note for absences of 3 days or fewer.",
             ["PTO_and_Leave_Policy.md"]),
        ],
    },
    {
        "title": "401k matching details",
        "collection": "HR & People Ops",
        "exchanges": [
            ("What is the 401k match at TechCorp?",
             "TechCorp matches 100% of your contributions up to 4% of your salary. Matching contributions vest over 3 years: 33% at year 1, 66% at year 2, and 100% at year 3.",
             ["Benefits_Guide_2026.md"]),
        ],
    },
    {
        "title": "Onboarding first week checklist",
        "collection": "HR & People Ops",
        "exchanges": [
            ("What should I complete in my first week at TechCorp?",
             "In your first week: complete I-9 and tax forms in Rippling, set up 1Password with MFA on all accounts, join your Slack channels, have a 1:1 with your manager, attend the benefits enrollment walkthrough, read the Employee Handbook and Code of Conduct, and complete the mandatory security awareness training.",
             ["Onboarding_Checklist.md"]),
        ],
    },
    # ── Engineering (15) ─────────────────────────────────────────────────────
    {
        "title": "Authentication flow and JWT tokens",
        "collection": "Engineering Docs",
        "exchanges": [
            ("How does the TechCorp authentication flow work?",
             "The auth flow uses JWT HS256 tokens. The client POSTs credentials to /auth/login and receives an access_token (30-minute expiry) and refresh_token (7-day expiry). All subsequent requests include the access token as a Bearer header. When the access token expires, the client calls /auth/refresh to get a new one.",
             ["System_Architecture_Overview.md", "API_Documentation_v3.md"]),
            ("What happens to active sessions when we rotate the JWT secret?",
             "All issued tokens are immediately invalidated when the JWT secret rotates, since they can no longer be verified. The December 2025 auth outage was caused by exactly this — the rotation script ran mid-deploy and invalidated all active sessions. A guard was added to block rotation during active deployments.",
             ["Postmortem_Dec2025_Auth_Outage.md"]),
        ],
    },
    {
        "title": "December 2025 auth outage root cause",
        "collection": "Engineering Docs",
        "exchanges": [
            ("What caused the December auth outage?",
             "The December 14, 2025 auth outage lasted 47 minutes and affected ~8,400 users. The root cause was the JWT secret key rotation script being incorrectly included in the deploy pipeline for v2.14.1. When deployed, it rotated the secret and invalidated all active sessions. A rollback to v2.14.0 resolved it.",
             ["Postmortem_Dec2025_Auth_Outage.md"]),
        ],
    },
    {
        "title": "API rate limits",
        "collection": "Engineering Docs",
        "exchanges": [
            ("What are the API rate limits?",
             "Standard plans are limited to 100 requests/minute per API key. Enterprise plans get 1,000 requests/minute. Rate limit status is communicated via three response headers: X-RateLimit-Limit, X-RateLimit-Remaining, and X-RateLimit-Reset.",
             ["API_Documentation_v3.md"]),
        ],
    },
    {
        "title": "Database connection pool settings",
        "collection": "Engineering Docs",
        "exchanges": [
            ("What are the database connection pool settings in production?",
             "Production uses PgBouncer between services and the database. Pool mode is transaction. Max connections are 100 for the primary and 20 for the read replica. Connection pooling is handled by PgBouncer rather than the ORM directly.",
             ["Database_Schema_Reference.md", "System_Architecture_Overview.md"]),
        ],
    },
    {
        "title": "Code review requirements",
        "collection": "Engineering Docs",
        "exchanges": [
            ("How many approvals are required before merging a PR?",
             "Production code requires a minimum of 2 approvals. Architecture changes need at least 1 approval from a senior engineer (L3 or above). The PR must also pass all CI checks before merging. PRs over 400 lines of change require prior discussion in Linear.",
             ["Code_Review_Standards.md"]),
        ],
    },
    {
        "title": "CI/CD pipeline and deployment process",
        "collection": "Engineering Docs",
        "exchanges": [
            ("How does the CI/CD pipeline work?",
             "The pipeline uses GitHub Actions for CI and ArgoCD for deployment to GKE. Stages are: Lint → Test (80% coverage minimum) → Docker build → Trivy security scan → Deploy to staging (auto on merge to main) → Playwright E2E tests → Manual production deploy (team lead approval required).",
             ["CI_CD_Pipeline_Guide.md"]),
            ("How do I roll back a bad production deploy?",
             "Go to ArgoCD, select the service, click History, and select the previous revision. Rollback completes in under 90 seconds. Do not wait for root cause analysis before rolling back — mitigation first.",
             ["CI_CD_Pipeline_Guide.md", "Incident_Response_Playbook.md"]),
        ],
    },
    {
        "title": "Incident response for P0 incidents",
        "collection": "Engineering Docs",
        "exchanges": [
            ("What is the P0 incident response procedure?",
             "P0 is production down or a security compromise. Steps: (1) On-call acknowledges PagerDuty within 5 minutes. (2) Post in #ops-alerts and #general. (3) Rollback last deploy or disable feature flag — don't wait for root cause. (4) If unresolved in 30 min, page engineering manager and CTO. (5) Post-incident: complete postmortem within 48 hours.",
             ["Incident_Response_Playbook.md"]),
        ],
    },
    {
        "title": "Security policy and password requirements",
        "collection": "Engineering Docs",
        "exchanges": [
            ("What are the password and MFA requirements?",
             "Passwords must be at least 12 characters and include uppercase, lowercase, a digit, and a symbol. Passwords cannot be reused within the last 10 cycles. MFA is mandatory for all employees — there are no exceptions.",
             ["Security_Policy_and_Procedures.md"]),
        ],
    },
    {
        "title": "Vulnerability patching SLAs",
        "collection": "Engineering Docs",
        "exchanges": [
            ("How quickly do we need to patch security vulnerabilities?",
             "Critical vulnerabilities (CVSS 9.0+) must be patched within 24 hours. High severity (CVSS 7.0–8.9) within 7 days. Medium severity within 30 days. Dependency scanning runs automatically in CI on every PR.",
             ["Security_Policy_and_Procedures.md"]),
        ],
    },
    {
        "title": "Engineering OKRs 2026",
        "collection": "Engineering Docs",
        "exchanges": [
            ("What are the engineering OKRs for 2026?",
             "Engineering has four objectives: (1) Achieve 99.99% uptime — reduce P0 incidents to 2 or fewer and MTTR < 15 minutes. (2) Ship faster — reduce PR cycle time to 1.5 days and deploy 5× per week. (3) Scale to 10× current load. (4) Zero critical security vulnerabilities and SOC 2 Type II certification by Q3.",
             ["Engineering_OKRs_2026.md"]),
        ],
    },
    {
        "title": "GDPR and data retention policy",
        "collection": "Engineering Docs",
        "exchanges": [
            ("What are our GDPR obligations for customer data?",
             "Under GDPR: data subject requests (access, deletion, portability) must be fulfilled within 30 days; data breaches must be reported to the supervisory authority within 72 hours; DPAs are required with all sub-processors; and privacy policy updates must be published within 7 days of any material change.",
             ["Data_Privacy_Compliance_Guide.md"]),
            ("How long do we retain customer data after account deletion?",
             "Customer content is retained for 60 days after account deletion. Usage logs are anonymized after 90 days and deleted after 2 years. Financial records are retained for 7 years per IRS requirements.",
             ["Data_Privacy_Compliance_Guide.md"]),
        ],
    },
    {
        "title": "Tech debt priorities this quarter",
        "collection": "Engineering Docs",
        "exchanges": [
            ("What are the top tech debt items for Q1?",
             "Priority 1 items for Q1: (1) Replace synchronous ORM queries with async in Project Service — blocking horizontal scaling. (2) Upgrade PostgreSQL 13 to 15 — currently unsupported. (3) Remove deprecated /v1 API endpoints — confusing SDK users.",
             ["Tech_Debt_Backlog_Q1_2026.md"]),
        ],
    },
    {
        "title": "Infrastructure cost breakdown",
        "collection": "Engineering Docs",
        "exchanges": [
            ("What is our current cloud infrastructure spend?",
             "2025 total GCP spend was $1.24M, up 28% from 2024. The largest buckets are GKE compute ($504K, 41%), Cloud SQL ($222K, 18%), and ElasticSearch managed service ($168K, 14%). The 2026 target is a 17% reduction ($210K savings) through GKE rightsizing, self-hosted ElasticSearch, and BigQuery optimization.",
             ["Infrastructure_Cost_Analysis.md"]),
        ],
    },
    {
        "title": "System architecture overview",
        "collection": "Engineering Docs",
        "exchanges": [
            ("Can you give me an overview of TechCorp's system architecture?",
             "TechCorp runs cloud-native microservices on GCP. Core services include Auth, Project, Notification, Analytics, and Search. Services communicate via internal gRPC. The API gateway handles external REST traffic. Production uses Cloud SQL (PostgreSQL 15). Infrastructure is managed with Terraform on GKE in us-central1 (primary) and us-east1 (failover).",
             ["System_Architecture_Overview.md"]),
        ],
    },
    {
        "title": "SOC 2 compliance readiness",
        "collection": "Engineering Docs",
        "exchanges": [
            ("What is the status of our SOC 2 certification?",
             "SOC 2 Type II certification is targeting Q3 2026. Current status: security controls (access, encryption, vulnerability management) are complete. Open items include the Q2 penetration test, the Q1 disaster recovery test, and the annual access review due February 28.",
             ["Compliance_Checklist_SOC2.md"]),
        ],
    },
    # ── Product & Roadmap (10) ────────────────────────────────────────────────
    {
        "title": "Q2 2026 product features",
        "collection": "Product & Design",
        "exchanges": [
            ("What features are planned for Q2 2026?",
             "Q2 2026 focuses on Dashboard V2 (fully customizable dashboards with drag-and-drop widgets), Custom Reporting (build and share reports across projects), and API v4 with cursor pagination and richer filtering.",
             ["Product_Roadmap_2026.md"]),
        ],
    },
    {
        "title": "Dashboard V2 specification",
        "collection": "Product & Design",
        "exchanges": [
            ("What is the spec for Dashboard V2?",
             "Dashboard V2 allows users to build custom dashboards with draggable widgets. MVP widget types include task lists, charts (by status/assignee/priority), progress bars, calendar views, and free-form text. Dashboards are stored as JSON in PostgreSQL and rendered via react-grid-layout. Target: 50% adoption within 60 days of launch.",
             ["Feature_Spec_DashboardV2.md"]),
            ("What's the success metric for Dashboard V2?",
             "Success metrics: 50% of active users create at least one custom dashboard within 60 days, NPS improvement of +5 points in dashboard satisfaction, and zero P0 incidents within the first 30 days post-launch.",
             ["Feature_Spec_DashboardV2.md"]),
        ],
    },
    {
        "title": "Top user research findings",
        "collection": "Product & Design",
        "exchanges": [
            ("What were the top findings from the January 2026 user research?",
             "Top pain points from 20 user interviews: (1) No customization — 17/20 said 'I can't build the view I need.' (2) Unusable mobile experience — 15/20. (3) Notification overload — 14/20. (4) Reporting limitations requiring Excel exports — 12/20. Top loved features: recurring tasks, guest access, and keyboard shortcuts.",
             ["User_Research_Report_Jan2026.md"]),
        ],
    },
    {
        "title": "Competitive landscape",
        "collection": "Product & Design",
        "exchanges": [
            ("How do we compare to Asana and Linear?",
             "Win rate vs Asana is 38% — we win on UX simplicity and price. Win rate vs Linear is 54% — we win because Linear is developer-only and we serve mixed teams. Top loss reason vs both: missing integrations and no mobile app.",
             ["Competitive_Analysis_2026.md"]),
        ],
    },
    {
        "title": "Q4 2025 product metrics",
        "collection": "Product & Design",
        "exchanges": [
            ("What were the product metrics for Q4 2025?",
             "Q4 2025: MAU reached 42,000 (up 34% from Q3's 31,300). NPS hit 52, up from 44. Feature adoption rate for new features at 30 days was 41%. API P99 latency improved to 380ms from 620ms in Q3.",
             ["Q4_2025_Product_Review.md"]),
        ],
    },
    {
        "title": "A/B test results onboarding",
        "collection": "Product & Design",
        "exchanges": [
            ("What did the onboarding A/B test show?",
             "The onboarding checklist redesign test showed a 23% improvement in 7-day activation (41% control vs 50.4% variant), statistically significant at p < 0.01 with n=3,200. Decision: ship the variant. The notification digest default test also shipped — it reduced 30-day churn by 12%.",
             ["AB_Test_Results_Q4_2025.md"]),
        ],
    },
    {
        "title": "Design system color palette",
        "collection": "Product & Design",
        "exchanges": [
            ("What colors are in the TechCorp design system?",
             "Primary: TechBlue #1B55E2 (buttons, links, active states). Primary Dark: #1240B8 (hover). Success: #16A34A. Warning: #D97706. Danger: #DC2626. Neutral 900: #111827 (primary text). Neutral 500: #6B7280 (secondary). Neutral 100: #F3F4F6 (backgrounds).",
             ["Design_System_Guidelines.md"]),
        ],
    },
    {
        "title": "NextGen Analytics PRD",
        "collection": "Product & Design",
        "exchanges": [
            ("What problem is the NextGen Analytics module solving?",
             "42% of enterprise customers (42% of ARR) cite analytics as a top-3 churn reason. Current analytics are limited to basic status reports. The module will enable cross-project reporting, velocity charts, team workload heatmaps, OKR tracking, and PDF/CSV export — eliminating dependence on manual Excel exports.",
             ["PRD_NextGen_Analytics.md"]),
        ],
    },
    {
        "title": "Mobile app launch plan",
        "collection": "Product & Design",
        "exchanges": [
            ("When is the mobile app launching and what's included?",
             "The mobile app is targeted for Q1 2026 (February 14 soft launch). It will have feature parity with the web app for task management on iOS and Android. The launch plan includes App Store optimization, a Product Hunt launch, and email to existing users. Goal: 10,000 downloads in the first 30 days.",
             ["Product_Roadmap_2026.md", "Marketing_Campaign_H1_2026.md"]),
        ],
    },
    {
        "title": "What is not on the 2026 roadmap",
        "collection": "Product & Design",
        "exchanges": [
            ("What features are explicitly not planned for 2026?",
             "The following are explicitly out of scope for 2026: video calling / collaboration features, white-labeling or OEM capabilities, and a desktop native app.",
             ["Product_Roadmap_2026.md"]),
        ],
    },
    # ── Sales & Revenue (10) ──────────────────────────────────────────────────
    {
        "title": "Sales process and deal stages",
        "collection": "Sales & Marketing",
        "exchanges": [
            ("What are the deal stages in our sales process?",
             "The six deal stages are: (1) Discovery (0%) — qualify BANT; (2) Demo (20%) — tailored to their use case; (3) Technical Evaluation (40%) — POC or trial; (4) Proposal (60%) — formal proposal sent; (5) Negotiation (80%) — commercial and legal; (6) Closed Won (100%) or Closed Lost.",
             ["Sales_Playbook_2026.md"]),
        ],
    },
    {
        "title": "Discount authority levels",
        "collection": "Sales & Marketing",
        "exchanges": [
            ("How much can an AE discount without approval?",
             "AEs can discount up to 10% without approval. Discounts of 11–20% require Director of Sales approval. Anything above 20% requires both VP Sales and CFO approval. The pricing floor for enterprise is $7/user/month all-in — never go below this.",
             ["Pricing_Guide_2026.md", "Sales_Playbook_2026.md"]),
        ],
    },
    {
        "title": "Ideal customer profile",
        "collection": "Sales & Marketing",
        "exchanges": [
            ("Who is our ideal customer?",
             "Primary ICP: Mid-market technology companies (SaaS, fintech, agencies) with 50–500 employees, $10M–$200M ARR, Series A–C funded, outgrowing spreadsheets or point solutions. Key personas: VP Engineering/CTO (technical champion) and VP Operations/COO (economic buyer). Negative ICP: pure engineering teams, on-premise requirements, companies under 10 employees.",
             ["Ideal_Customer_Profile.md"]),
        ],
    },
    {
        "title": "Handling the 'too expensive' objection",
        "collection": "Sales & Marketing",
        "exchanges": [
            ("How should I handle a pricing objection?",
             "Start by asking what budget they're working with. Often you can structure a deal within budget, especially on an annual plan or if replacing an existing tool. If still stuck, offer a structured 2-week paid pilot at 50% off the first month. Never drop below the pricing floor without CFO approval.",
             ["Objection_Handling_Guide.md"]),
        ],
    },
    {
        "title": "Q4 2025 sales performance",
        "collection": "Sales & Marketing",
        "exchanges": [
            ("How did we perform in Q4 2025?",
             "Q4 2025 was the best quarter in company history. New ARR: $3.2M vs $2.8M target (114% attainment). Total ARR reached $18.4M. Enterprise segment led at 127% attainment. Top deal: Apex Dynamics at $240K ARR on a 3-year term.",
             ["Q4_2025_Sales_Report.md"]),
        ],
    },
    {
        "title": "Q1 2026 pipeline",
        "collection": "Sales & Marketing",
        "exchanges": [
            ("What does our Q1 2026 pipeline look like?",
             "Entering Q1 2026 with $9.4M in qualified pipeline against a $3.5M new ARR target. The win rate vs Asana improved to 44% in Q4. Top loss reasons remain missing integrations (38%) and no mobile app (29%) — both addressed in the Q1 roadmap.",
             ["Q4_2025_Sales_Report.md"]),
        ],
    },
    {
        "title": "Brand voice and tone",
        "collection": "Sales & Marketing",
        "exchanges": [
            ("What is TechCorp's brand voice?",
             "TechCorp's brand voice is Clear (say what you mean in as few words as possible), Confident (no hedging — we know our product is excellent), and Human (write like a smart colleague, not a press release). Avoid: buzzwords like 'synergy' or 'leverage', passive voice, and jargon.",
             ["Brand_Guidelines_v2.md"]),
        ],
    },
    {
        "title": "Proposal structure for enterprise deals",
        "collection": "Sales & Marketing",
        "exchanges": [
            ("What should be included in an enterprise proposal?",
             "Enterprise proposals should include: Executive Summary (2–3 sentences), Understanding Your Challenges (mirror their words back), Proposed Solution (specific configuration), Implementation Plan (4-week onboarding), Investment Summary (seats × price × annual total), Why TechCorp (case studies and reviews), and Next Steps (MSA review, sign, kickoff).",
             ["Enterprise_Proposal_Template.md"]),
        ],
    },
    {
        "title": "SEO targets 2026",
        "collection": "Sales & Marketing",
        "exchanges": [
            ("What are our SEO goals for 2026?",
             "Organic traffic target: 150,000 monthly visitors by end of 2026 (up from 82,000 in Dec 2025). Organic-sourced signups: 1,800/month by Q4. Domain Rating: 62 (up from 54). Priority keywords: 'project management software' (90K volume, currently #14) and 'asana alternative' (12K volume, currently #6).",
             ["SEO_Content_Strategy_2026.md"]),
        ],
    },
    {
        "title": "Customer case study Apex Dynamics",
        "collection": "Sales & Marketing",
        "exchanges": [
            ("Do we have a case study I can share with an operations prospect?",
             "Yes — Apex Dynamics is ideal for operations buyers. They had 4 different tools across departments with no cross-team visibility. After deploying TechCorp org-wide in 3 weeks: executives saved 3 hours/week on status reporting, missed deadlines dropped 22%, and their team NPS is 72. Quote: 'TechCorp is the first tool all of our teams actually use.'",
             ["Customer_Case_Studies.md"]),
        ],
    },
    # ── Finance & Legal (8) ───────────────────────────────────────────────────
    {
        "title": "Annual budget overview 2026",
        "collection": "Finance & Legal",
        "exchanges": [
            ("What is the 2026 operating budget?",
             "The 2026 operating budget is $28.5M. Largest allocations: Engineering $9.2M (32%), Sales $7.1M (25%), Marketing $3.4M (12%), Customer Success $2.8M (10%). Revenue target: grow ARR from $18.4M to $32M — requiring $13.6M in new ARR.",
             ["Budget_2026.md"]),
        ],
    },
    {
        "title": "Q4 2025 financial results",
        "collection": "Finance & Legal",
        "exchanges": [
            ("What were the Q4 2025 financial results?",
             "Q4 2025 recognized revenue was $4.2M. Gross margin was 78%. Net Revenue Retention (NRR): 118%. LTV/CAC: 7.4×. Operating loss was $1.34M — improved from Q3. Cash position at end of Q4: $22.1M with $1.8M monthly burn.",
             ["Q4_2025_Financial_Report.md"]),
        ],
    },
    {
        "title": "Vendor contract renewals",
        "collection": "Finance & Legal",
        "exchanges": [
            ("Which vendor contracts are coming up for renewal?",
             "Upcoming renewals in the next 90 days: Elastic Cloud (March 15, $168K/year — migration to self-hosted is being evaluated for $100K savings) and Notion (February 28 — usage has declined, may downgrade). Salesforce is next in July ($142K/year, enterprise agreement with 3-year term).",
             ["Vendor_Contracts_Summary.md"]),
        ],
    },
    {
        "title": "IP ownership and open source contributions",
        "collection": "Finance & Legal",
        "exchanges": [
            ("Can I contribute to open source projects while working at TechCorp?",
             "Yes, with manager approval for projects unrelated to TechCorp's business. Contributing any TechCorp code to open source requires explicit written approval from the CTO. All work product created during employment using company resources is owned by TechCorp.",
             ["IP_and_Confidentiality_Policy.md"]),
        ],
    },
    {
        "title": "Equity vesting schedule",
        "collection": "Finance & Legal",
        "exchanges": [
            ("How does equity vesting work at TechCorp?",
             "Standard vesting is 4 years with a 1-year cliff. At 12 months, 25% of options vest. After that, 1/48th vests each month through year 4. Options are granted at Fair Market Value (FMV) from the most recent 409A valuation. Annual refresh grants are performance-based, awarded each March.",
             ["Equity_Vesting_Guide.md"]),
        ],
    },
    {
        "title": "Data processing agreement requirements",
        "collection": "Finance & Legal",
        "exchanges": [
            ("When do we need a DPA with a vendor?",
             "A Data Processing Agreement is required with all vendors who process personal data on our behalf (sub-processors). The DPA must cover: security measures, sub-processor consent, data subject rights assistance, breach notification within 48 hours, and data return/deletion on termination.",
             ["Data_Processing_Agreement.md"]),
        ],
    },
    {
        "title": "Expense approval thresholds",
        "collection": "Finance & Legal",
        "exchanges": [
            ("What are the approval thresholds for company expenses?",
             "Expenses up to $500 need manager approval only. $501–$5,000 requires manager plus Finance approval. Over $5,000 requires manager, Finance, and VP approval. All expenses must be submitted within 30 days with original receipts for anything over $25.",
             ["Invoice_and_Expense_Policy.md"]),
        ],
    },
    {
        "title": "SOC 2 open controls",
        "collection": "Finance & Legal",
        "exchanges": [
            ("What SOC 2 controls are still open?",
             "Three controls are still open: (1) Penetration test scheduled for Q2 2026 (owner: felix.braun). (2) Disaster recovery test not yet conducted (owner: josh.banks, due Q1 2026). (3) CCPA opt-out mechanism needs testing (owner: yvonne.king, due March 1, 2026). Annual access review is also due February 28.",
             ["Compliance_Checklist_SOC2.md"]),
        ],
    },
    # ── General / Cross-Collection (7) ────────────────────────────────────────
    {
        "title": "Company mission and values",
        "collection": None,
        "exchanges": [
            ("What is TechCorp's mission and what are its values?",
             "TechCorp's mission is to build project management software that helps teams ship faster. The four core values are: Transparency, Customer Obsession, Ownership, and Continuous Learning.",
             ["Employee_Handbook_2026.md"]),
        ],
    },
    {
        "title": "2026 company strategy summary",
        "collection": None,
        "exchanges": [
            ("Can you summarize TechCorp's 2026 strategy?",
             "TechCorp's 2026 theme is 'Intelligence + Scale.' Key strategic bets: (1) Mobile app launch in Q1 to address the #2 user pain point. (2) Dashboard V2 in Q2 to address the #1 pain point and reduce enterprise churn risk. (3) AI-powered insights in Q3 to differentiate against Asana and Monday. (4) SOC 2 Type II and enterprise compliance in Q3–Q4 to unlock regulated industry segments.",
             ["Product_Roadmap_2026.md", "Engineering_OKRs_2026.md"]),
        ],
    },
    {
        "title": "Headcount plan Q1 2026",
        "collection": None,
        "exchanges": [
            ("How many people are we hiring in Q1?",
             "TechCorp plans to hire 18 net new employees in Q1 2026, growing from 100 to 118. The largest cohort is Engineering (8 hires: backend, frontend, DevOps, ML, QA), followed by Sales (5 hires: SDRs and AEs) and Customer Success (2 hires).",
             ["Hiring_Plan_Q1_2026.md"]),
        ],
    },
    {
        "title": "How to handle a data breach",
        "collection": None,
        "exchanges": [
            ("What do we do if there's a customer data breach?",
             "Under GDPR, the supervisory authority must be notified within 72 hours of becoming aware of a breach. Our Data Processing Agreements require processors to notify us within 48 hours. Affected customers must be notified without undue delay. Internally, follow the Incident Response Playbook and engage Legal immediately.",
             ["Data_Privacy_Compliance_Guide.md", "Incident_Response_Playbook.md"]),
        ],
    },
    {
        "title": "Where to find the sales playbook",
        "collection": None,
        "exchanges": [
            ("Where can I find the sales playbook?",
             "The Sales Playbook 2026 is in the 'Sales & Marketing' collection. It covers the MEDDIC sales methodology, discovery frameworks, deal stages, pricing authority, and objection handling. For quick objection scripts, see Objection_Handling_Guide.md in the same collection.",
             ["Sales_Playbook_2026.md", "Objection_Handling_Guide.md"]),
        ],
    },
    {
        "title": "Engineering team OKR owners",
        "collection": None,
        "exchanges": [
            ("Who owns the engineering OKRs for 2026?",
             "The engineering OKRs are owned by the Engineering team led by sarah.chen (VP Engineering). OKR progress is tracked weekly in the Engineering Linear project and reviewed monthly by VP Engineering and updated in the Exec Leadership Sync.",
             ["Engineering_OKRs_2026.md"]),
        ],
    },
    {
        "title": "Security training requirements",
        "collection": None,
        "exchanges": [
            ("Is security training mandatory?",
             "Yes. All employees must complete annual security awareness training. The 2026 company-wide session is January 30 (2 hours, virtual). Completion is tracked by IT and is a required onboarding step. Current completion rate as of last check-in was 87%.",
             ["Onboarding_Checklist.md", "Security_Policy_and_Procedures.md"]),
        ],
    },
]

# Which roles should be assigned which conversation categories
# Analyst users get any template; admin gets all; viewer gets HR + General only


async def seed_conversations(session) -> None:
    """Create ~200 RAG conversations with realistic Q&A and source citations."""
    # Build lookups
    user_res = await session.execute(select(User.username, User.id))
    uid_map: dict[str, str] = {r[0]: r[1] for r in user_res.all()}

    coll_res = await session.execute(select(Collection.name, Collection.id))
    coll_id_map: dict[str, str] = {r[0]: r[1] for r in coll_res.all()}

    doc_res = await session.execute(
        select(Document.filename, Document.id)
    )
    doc_id_map: dict[str, str] = {r[0]: r[1] for r in doc_res.all()}

    # All analyst + admin users
    eligible = [
        (uname, uid_map[uname])
        for uname, _title, _dept, role in USERS
        if role in ("analyst", "admin") and uname in uid_map
    ]

    def _feedback() -> int | None:
        r = random.random()
        if r < 0.60: return None
        if r < 0.90: return 1
        return -1

    def _build_sources(filenames: list[str]) -> list[dict]:
        sources = []
        for fname in filenames:
            did = doc_id_map.get(fname)
            # pull a short excerpt from the content if available
            full = DOC_CONTENT.get(fname, "")
            lines = [l.strip() for l in full.splitlines() if l.strip() and not l.startswith("#")]
            chunk = lines[random.randint(0, max(0, len(lines) - 1))] if lines else fname
            sources.append({
                "document_id": did or fname,
                "filename": fname,
                "score": round(random.uniform(0.72, 0.97), 3),
                "chunk": chunk[:200],
            })
        return sources

    # Assign each template to 3-4 random users
    total_conv = total_msgs = 0
    random.shuffle(eligible)

    for tmpl in CONV_TEMPLATES:
        assigned_count = random.randint(3, 4)
        assignees = random.sample(eligible, min(assigned_count, len(eligible)))
        coll_id = coll_id_map.get(tmpl["collection"]) if tmpl["collection"] else None
        ts_base = _rand_ts(days_back=75)

        for uname, uid in assignees:
            conv = Conversation(
                id=str(uuid.uuid4()),
                user_id=uid,
                title=tmpl["title"],
                collection_id=coll_id,
                created_at=ts_base,
                updated_at=ts_base,
            )
            session.add(conv)

            msg_ts = ts_base
            for user_q, asst_a, src_fnames in tmpl["exchanges"]:
                # User message
                msg_ts = msg_ts + timedelta(seconds=random.randint(5, 30))
                session.add(ConversationMessage(
                    id=str(uuid.uuid4()),
                    conversation_id=conv.id,
                    role="user",
                    content=user_q,
                    sources=None,
                    feedback=None,
                    created_at=msg_ts,
                ))
                # Assistant message
                msg_ts = msg_ts + timedelta(seconds=random.randint(2, 8))
                session.add(ConversationMessage(
                    id=str(uuid.uuid4()),
                    conversation_id=conv.id,
                    role="assistant",
                    content=asst_a,
                    sources=_build_sources(src_fnames),
                    feedback=_feedback(),
                    created_at=msg_ts,
                ))
                total_msgs += 2

            total_conv += 1

    await session.flush()
    print(f"  [conversations] {total_conv} conversations, {total_msgs} messages")


# ── Phase 9 — Notifications ────────────────────────────────────────────────────

async def seed_notifications(session) -> None:
    """Generate in-app notifications:
    - event_invite: one per attendee for every calendar event
    - dm: last-message notification for recent DM channels
    - system: policy/training reminders for all users
    """
    from src.models.notification import Notification
    from src.models.calendar import CalendarEvent, EventAttendee
    from src.models.chat import Channel, ChatMessage, ChannelMember

    now = datetime.now(timezone.utc)
    total = 0

    # ── Build user id → username map ──────────────────────────────────────────
    user_res = await session.execute(select(User.id, User.username))
    uid_to_uname: dict[str, str] = {r[0]: r[1] for r in user_res.all()}

    # ── 1. event_invite notifications ─────────────────────────────────────────
    # Load all events + attendees
    evt_res = await session.execute(
        select(CalendarEvent.id, CalendarEvent.title, CalendarEvent.start_time,
               CalendarEvent.created_by)
    )
    events = evt_res.all()

    att_res = await session.execute(
        select(EventAttendee.event_id, EventAttendee.user_id, EventAttendee.status)
    )
    attendees_by_event: dict[str, list[tuple[str, str]]] = {}
    for event_id, user_id, rsvp in att_res.all():
        attendees_by_event.setdefault(event_id, []).append((user_id, rsvp))

    for evt_id, evt_title, evt_start, organizer_id in events:
        organizer_name = uid_to_uname.get(organizer_id, "Someone")
        try:
            date_str = evt_start.strftime("%b %-d") if evt_start else "upcoming"
        except Exception:
            date_str = "upcoming"
        for user_id, rsvp in attendees_by_event.get(evt_id, []):
            if user_id == organizer_id:
                continue  # organizer doesn't get invited to their own event
            is_read = random.random() < 0.70  # 70% read
            # Stagger notification times: 1–48 h before event start
            hours_before = random.randint(1, 48)
            # Normalise evt_start to UTC-aware so comparison with `now` works
            if evt_start is not None:
                if evt_start.tzinfo is None:
                    evt_start_tz = evt_start.replace(tzinfo=timezone.utc)
                else:
                    evt_start_tz = evt_start
                notif_ts = evt_start_tz - timedelta(hours=hours_before)
            else:
                notif_ts = now
            if notif_ts > now:
                notif_ts = now - timedelta(hours=random.randint(1, 6))
            session.add(Notification(
                id=str(uuid.uuid4()),
                user_id=user_id,
                type="event_invite",
                title=f"You're invited: {evt_title}",
                body=f"{organizer_name} invited you to '{evt_title}' on {date_str}.",
                link="/calendar",
                is_read=is_read,
                created_at=notif_ts,
            ))
            total += 1

    # ── 2. dm notifications — last message per DM channel ─────────────────────
    dm_res = await session.execute(
        select(Channel.id, Channel.name).where(Channel.type == "dm")
    )
    dm_channels = dm_res.all()

    for ch_id, ch_name in dm_channels:
        # Latest message in channel
        msg_res = await session.execute(
            select(ChatMessage.sender_id, ChatMessage.content, ChatMessage.created_at)
            .where(ChatMessage.channel_id == ch_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        row = msg_res.first()
        if not row:
            continue
        sender_id, content, msg_ts = row
        sender_name = uid_to_uname.get(sender_id, "Someone")

        # Notify all DM members except sender
        mem_res = await session.execute(
            select(ChannelMember.user_id).where(ChannelMember.channel_id == ch_id)
        )
        for (member_uid,) in mem_res.all():
            if member_uid == sender_id:
                continue
            is_read = random.random() < 0.55
            body_text = content[:100] + ("…" if len(content) > 100 else "")
            session.add(Notification(
                id=str(uuid.uuid4()),
                user_id=member_uid,
                type="dm",
                title=f"New message from {sender_name}",
                body=body_text,
                link="/chat",
                is_read=is_read,
                created_at=msg_ts,
            ))
            total += 1

    # ── 3. system notifications — policy & training reminders ─────────────────
    SYSTEM_NOTIFS = [
        (
            "Complete Security Awareness Training",
            "Your annual security awareness training is due by March 31, 2026. "
            "Complete it in the Learning Portal to stay compliant.",
            "/documents",
            0.40,   # read_rate
        ),
        (
            "Acknowledge Updated Expense Policy",
            "The Expense Reimbursement Policy was updated on Jan 15, 2026. "
            "Please review and acknowledge by Feb 28.",
            "/documents",
            0.65,
        ),
        (
            "Performance Review Cycle Open",
            "Q1 2026 performance reviews are now open. Submit your self-assessment "
            "in the HR portal by March 20.",
            "/documents",
            0.50,
        ),
        (
            "Mandatory: Update Emergency Contact",
            "HR requires all employees to verify their emergency contact on file. "
            "Log in to the HR portal and confirm or update by April 1.",
            "/documents",
            0.35,
        ),
        (
            "Nexus Platform Update — New Features Available",
            "Nexus v2.4 shipped this week. Check out the release notes for new RAG "
            "search filters, calendar sync, and improved notification settings.",
            "/",
            0.80,
        ),
        (
            "Open Enrollment: Benefits Selection Deadline",
            "Open enrollment for 2026 benefits closes March 15. Review your options "
            "and make selections in the Benefits portal.",
            "/documents",
            0.55,
        ),
    ]

    # Load all user ids
    all_uid_res = await session.execute(select(User.id))
    all_user_ids = [r[0] for r in all_uid_res.all()]

    for title, body, link, read_rate in SYSTEM_NOTIFS:
        # Send to 60–100% of users (random subset per notification)
        sample_size = random.randint(int(len(all_user_ids) * 0.6), len(all_user_ids))
        recipients = random.sample(all_user_ids, sample_size)
        days_ago = random.randint(1, 45)
        base_ts = now - timedelta(days=days_ago)
        for uid in recipients:
            jitter = timedelta(minutes=random.randint(0, 120))
            session.add(Notification(
                id=str(uuid.uuid4()),
                user_id=uid,
                type="system",
                title=title,
                body=body,
                link=link,
                is_read=random.random() < read_rate,
                created_at=base_ts + jitter,
            ))
            total += 1

    await session.flush()
    print(f"  [notifications] {total} notifications created")


# ── Phase 10 — Audit & Query Logs ─────────────────────────────────────────────

# Realistic query strings for QueryLog backfill
_QUERY_SAMPLES = [
    "What is the vacation and PTO policy?",
    "How do I request parental leave?",
    "What are the expense reimbursement limits?",
    "How does the performance review process work?",
    "What is the remote work policy?",
    "How do I submit an IT support ticket?",
    "What security training is required this year?",
    "Explain the data retention policy.",
    "What are the rules for using personal devices at work?",
    "How are bonuses calculated?",
    "What is the process for requesting a new software license?",
    "How do I set up two-factor authentication?",
    "What is the incident response procedure?",
    "Explain the deployment pipeline for backend services.",
    "How do I roll back a failed deployment?",
    "What are the SLO targets for the API gateway?",
    "How is the on-call rotation structured?",
    "What is the database backup schedule?",
    "How do I add a new environment variable to production?",
    "Explain the code review policy.",
    "What is the Git branching strategy?",
    "How do I get access to the staging environment?",
    "What monitoring alerts are configured for the payments service?",
    "How do I run the integration test suite?",
    "What is the process for promoting a hotfix to production?",
    "What is the product roadmap for Q2 2026?",
    "How are feature requests prioritized?",
    "What is the design system color palette?",
    "How do accessibility requirements affect our product decisions?",
    "What metrics define product-market fit for our growth team?",
    "How does the A/B testing framework work?",
    "What are the OKRs for the Product team this quarter?",
    "How do I write a product requirements document?",
    "What is the enterprise sales cycle?",
    "How should I handle a procurement objection?",
    "What are the discount approval tiers?",
    "How do I escalate a deal to executive sponsorship?",
    "What CRM fields are required for a Stage 3 opportunity?",
    "What is our competitive positioning against Competitor X?",
    "How do I calculate ARR for a multi-year deal?",
    "What is our churn rate for SMB accounts?",
    "How does the commission structure work?",
    "What is the content approval workflow?",
    "How do I create a campaign in our marketing automation tool?",
    "What are the brand guidelines for social media posts?",
    "What is the Q1 2026 marketing budget breakdown?",
    "How does the demand gen funnel work?",
    "What are the finance approval thresholds?",
    "How do I submit an invoice for payment?",
    "What is the quarterly close process?",
    "How are stock options calculated at vesting?",
    "What are the audit committee reporting requirements?",
    "How do I file an expense report?",
    "What is the travel booking policy?",
    "How does equity vesting work for new hires?",
    "What is the headcount approval process?",
    "How do I escalate a compliance concern?",
    "What are the data privacy requirements for customer data?",
    "What is the process for requesting a background check?",
    "How do I set up a new vendor in the procurement system?",
]


async def seed_audit_logs(session) -> None:
    """Backfill QueryLog, IngestionLog, DocumentAuditLog, and TeamAuditLog."""
    from src.models.audit import (
        QueryLog, IngestionLog, DocumentAuditLog, TeamAuditLog,
        DocumentAction, TeamAction,
    )

    now = datetime.now(timezone.utc)

    # ── Build lookup maps ──────────────────────────────────────────────────────
    user_res = await session.execute(select(User.id, User.username))
    users_all = user_res.all()
    uid_map: dict[str, str] = {uname: uid for uid, uname in users_all}
    all_uids = [uid for uid, _ in users_all]

    # Analysts + admins for queries
    analyst_uids = [
        uid_map[uname]
        for uname, _title, _dept, role in USERS
        if role in ("analyst", "admin") and uname in uid_map
    ]

    doc_res = await session.execute(
        select(Document.id, Document.filename, Document.owner_id, Document.visibility,
               Document.created_at)
    )
    docs = doc_res.all()  # (id, filename, owner_id, visibility, created_at)

    team_res = await session.execute(
        select(Team.id, Team.name, Team.created_by)
    )
    teams = team_res.all()  # (id, name, created_by)

    mem_res = await session.execute(
        select(Team.id, TeamMembership.user_id)
        .join(TeamMembership, Team.id == TeamMembership.team_id)
    )
    memberships = mem_res.all()  # (team_id, user_id)

    ql_count = il_count = dal_count = tal_count = 0

    # ── 1. QueryLog — 500 entries over 90 days ────────────────────────────────
    for _ in range(500):
        days_ago = random.uniform(0, 90)
        ts = now - timedelta(days=days_ago)
        uid = random.choice(analyst_uids)
        session.add(QueryLog(
            id=str(uuid.uuid4()),
            user_id=uid,
            query_text=random.choice(_QUERY_SAMPLES),
            chunks_retrieved=random.randint(3, 8),
            response_length=random.randint(180, 2200),
            latency_ms=random.randint(280, 4500),
            created_at=ts,
        ))
        ql_count += 1

    # ── 2. IngestionLog — one per document ────────────────────────────────────
    # Weight: 90% completed, 6% failed, 4% processing
    statuses = (["completed"] * 45 + ["failed"] * 3 + ["processing"] * 2)
    random.shuffle(statuses)
    for i, (doc_id, filename, owner_id, _vis, doc_created_at) in enumerate(docs):
        status = statuses[i % len(statuses)]
        error_msg = None
        if status == "failed":
            error_msg = random.choice([
                "Embedding service timeout after 30 s",
                "Unsupported encoding in file; UTF-8 decoding failed",
                "ChromaDB insert error: collection not found",
            ])
        ingest_ts = doc_created_at + timedelta(seconds=random.randint(5, 60))
        session.add(IngestionLog(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            user_id=owner_id,
            status=status,
            error_message=error_msg,
            duration_ms=random.randint(800, 18000),
            created_at=ingest_ts,
        ))
        il_count += 1

    # ── 3. DocumentAuditLog — created + mutations ─────────────────────────────
    for doc_id, filename, owner_id, visibility, doc_created_at in docs:
        # "created" entry for every document
        session.add(DocumentAuditLog(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            user_id=owner_id,
            action=DocumentAction.CREATED.value,
            old_metadata=None,
            new_metadata={"filename": filename, "visibility": str(visibility)},
            created_at=doc_created_at,
        ))
        dal_count += 1

    # A handful of visibility changes (10 random docs)
    vis_sample = random.sample(docs, min(10, len(docs)))
    old_vis_options = ["public", "team", "confidential"]
    for doc_id, filename, owner_id, visibility, doc_created_at in vis_sample:
        old_v = random.choice([v for v in old_vis_options if v != str(visibility)])
        changer_uid = random.choice(analyst_uids)
        change_ts = doc_created_at + timedelta(days=random.randint(1, 30))
        session.add(DocumentAuditLog(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            user_id=changer_uid,
            action=DocumentAction.VISIBILITY_CHANGED.value,
            old_metadata={"visibility": old_v},
            new_metadata={"visibility": str(visibility)},
            created_at=change_ts,
        ))
        dal_count += 1

    # A couple of ownership transfers (5 random docs)
    transfer_sample = random.sample(docs, min(5, len(docs)))
    for doc_id, filename, owner_id, visibility, doc_created_at in transfer_sample:
        new_owner_uid = random.choice([u for u in analyst_uids if u != owner_id])
        transfer_ts = doc_created_at + timedelta(days=random.randint(5, 60))
        session.add(DocumentAuditLog(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            user_id=owner_id,
            action=DocumentAction.OWNERSHIP_TRANSFERRED.value,
            old_metadata={"owner_id": owner_id},
            new_metadata={"owner_id": new_owner_uid},
            created_at=transfer_ts,
        ))
        dal_count += 1

    # ── 4. TeamAuditLog — created + member_added + updates ───────────────────
    # "created" for every team
    for team_id, team_name, created_by_uid in teams:
        if not created_by_uid:
            created_by_uid = random.choice(analyst_uids)
        session.add(TeamAuditLog(
            id=str(uuid.uuid4()),
            team_id=team_id,
            user_id=created_by_uid,
            action=TeamAction.CREATED.value,
            target_user_id=None,
            created_at=now - timedelta(days=random.randint(60, 90)),
        ))
        tal_count += 1

    # "member_added" — sample up to 60 memberships
    mem_sample = random.sample(memberships, min(60, len(memberships)))
    for team_id, member_uid in mem_sample:
        # Find team creator as the actor
        actor_uid = next(
            (cb for tid, _tname, cb in teams if tid == team_id and cb),
            random.choice(analyst_uids),
        )
        session.add(TeamAuditLog(
            id=str(uuid.uuid4()),
            team_id=team_id,
            user_id=actor_uid,
            action=TeamAction.MEMBER_ADDED.value,
            target_user_id=member_uid,
            created_at=now - timedelta(days=random.randint(30, 88)),
        ))
        tal_count += 1

    # "updated" — a few team description changes
    update_sample = random.sample(teams, min(6, len(teams)))
    for team_id, _team_name, created_by_uid in update_sample:
        if not created_by_uid:
            created_by_uid = random.choice(analyst_uids)
        session.add(TeamAuditLog(
            id=str(uuid.uuid4()),
            team_id=team_id,
            user_id=created_by_uid,
            action=TeamAction.UPDATED.value,
            target_user_id=None,
            created_at=now - timedelta(days=random.randint(1, 29)),
        ))
        tal_count += 1

    await session.flush()
    print(
        f"  [audit] {ql_count} query logs, {il_count} ingestion logs, "
        f"{dal_count} doc audit logs, {tal_count} team audit logs"
    )


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

        print("[seed] Phase 8: RAG conversations")
        await seed_conversations(session)
        await session.commit()

        print("[seed] Phase 9: Notifications")
        await seed_notifications(session)
        await session.commit()

        print("[seed] Phase 10: Audit & query logs")
        await seed_audit_logs(session)
        await session.commit()
    await engine2.dispose()

    print()
    print("[seed] ✓ All phases complete (1–10).")
    print(f"       Admin login: alex.foster@{COMPANY['domain']} / {COMPANY['admin_password']}")
    print(f"       All users:   <username>@{COMPANY['domain']} / {COMPANY['user_password']}")


async def reset_data(settings) -> None:
    """Wipe all TechCorp tenant data so the script can be re-run cleanly.

    Deletes rows in dependency order (children before parents) to avoid FK
    constraint violations.  Roles and permissions are left intact — they are
    global and not tenant-specific.
    """
    from sqlalchemy import text

    engine = get_async_engine(settings.DATABASE_URL)
    dialect = engine.dialect.name  # "sqlite" or "postgresql"

    async with engine.begin() as conn:
        if dialect == "sqlite":
            await conn.execute(text("PRAGMA foreign_keys = OFF"))

        tables_ordered = [
            # Audit / logs
            "query_logs",
            "ingestion_logs",
            "document_audit_logs",
            "team_audit_logs",
            # Notifications
            "notifications",
            # Conversations
            "conversation_messages",
            "conversations",
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
            "document_tags",
            "documents",
            "collections",
            # Teams
            "team_memberships",
            "teams",
            # Users (last — everything else refs users)
            "users",
            # Company
            "companies",
        ]

        deleted_totals = {}
        for table in tables_ordered:
            try:
                if dialect == "postgresql":
                    result = await conn.execute(text(f"DELETE FROM {table}"))
                else:
                    result = await conn.execute(text(f"DELETE FROM {table}"))
                deleted_totals[table] = result.rowcount
            except Exception as exc:
                print(f"  [reset] WARNING: could not clear {table}: {exc}")

        if dialect == "sqlite":
            await conn.execute(text("PRAGMA foreign_keys = ON"))

    await engine.dispose()

    total = sum(deleted_totals.values())
    print(f"[reset] Wiped {total} rows across {len(tables_ordered)} tables.")

    # Clear vector store (ChromaDB)
    try:
        from src.vectorstore import get_vector_store
        vs = get_vector_store(settings)
        await vs.delete_all()
        print("[reset] Vector store cleared.")
    except Exception as exc:
        print(f"  [reset] WARNING: could not clear vector store: {exc}")

    # Clear BM25 index
    try:
        from src.services.bm25_service import BM25Service
        import asyncio as _asyncio
        bm25 = BM25Service()
        await _asyncio.to_thread(bm25.clear_all)
        print("[reset] BM25 index cleared.")
    except Exception as exc:
        print(f"  [reset] WARNING: could not clear BM25 index: {exc}")

    # Clear Neo4j knowledge graph
    try:
        from src.services.knowledge_graph_service import get_kg_service
        kg = get_kg_service(settings)
        if kg:
            await kg.delete_all()
            print("[reset] Neo4j knowledge graph cleared.")
    except Exception as exc:
        print(f"  [reset] WARNING: could not clear Neo4j: {exc}")

    # Also remove uploaded document files
    upload_dir = Path("data/uploads/company_one")
    if upload_dir.exists():
        import shutil
        shutil.rmtree(upload_dir)
        print(f"[reset] Removed {upload_dir}")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        async def _do_reset():
            settings = get_settings()
            print(f"[reset] Wiping all TechCorp data from {settings.DATABASE_URL} …")
            await reset_data(settings)
            print("[reset] Done. Run the script again (without --reset) to re-seed.")
        asyncio.run(_do_reset())
    else:
        asyncio.run(main())
