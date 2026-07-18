"""Pydantic models for the LLM extraction schema (schema_version=1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── enum literals ──────────────────────────────────────────────────────────────

CompanyStage = Literal[
    "bootstrapped", "pre_seed", "seed", "series_a",
    "series_b", "series_c_plus", "public", "unstated",
]
YesNoUnstated = Literal["yes", "no", "unstated"]
WorkplacePolicy = Literal["onsite", "remote", "hybrid", "multiple_options", "unstated"]
SalaryPeriod = Literal["year", "month", "day", "hour", "unstated"]
EquityValue = Literal["yes", "no", "equity_only", "unstated"]
TitleGuess = Literal[
    "software_engineer", "frontend", "backend", "fullstack",
    "ml_engineer", "data_engineer", "data_scientist", "devops_sre",
    "security", "mobile", "embedded", "qa", "product_manager",
    "designer", "engineering_manager", "cto", "founding_engineer", "other",
]
Seniority = Literal[
    "intern", "junior", "mid", "senior", "staff_plus",
    "lead", "manager", "executive", "unstated",
]
EmploymentType = Literal[
    "full_time", "part_time", "contract", "internship", "cofounder", "unstated",
]
PostType = Literal["job_posting", "seeking_work", "meta_or_other"]

# ── nested models ──────────────────────────────────────────────────────────────


class Company(BaseModel):
    name: str | None = None
    url: str | None = None
    description: str | None = None
    stage: CompanyStage = "unstated"
    is_yc: YesNoUnstated = "unstated"
    industry_tags: list[str] = Field(default_factory=list)


class Location(BaseModel):
    city: str | None = None
    region: str | None = None
    country_raw: str | None = None


class Workplace(BaseModel):
    policy: WorkplacePolicy = "unstated"
    remote_region_raw: str | None = None


class Salary(BaseModel):
    min: float | None = None
    max: float | None = None
    currency_raw: str | None = None
    period: SalaryPeriod = "unstated"
    equity: EquityValue = "unstated"


class Role(BaseModel):
    title_raw: str
    title_guess: TitleGuess = "other"
    seniority: Seniority = "unstated"
    employment_type: EmploymentType = "unstated"
    salary: Salary = Field(default_factory=Salary)


class AISignals(BaseModel):
    company_builds_ai: YesNoUnstated = "unstated"
    ai_tools_in_workflow: YesNoUnstated = "unstated"
    ai_skills_required: YesNoUnstated = "unstated"


class Application(BaseModel):
    url: str | None = None
    email: str | None = None


class ExtractionResult(BaseModel):
    post_type: PostType = "job_posting"
    company: Company = Field(default_factory=Company)
    locations: list[Location] = Field(default_factory=list)
    workplace: Workplace = Field(default_factory=Workplace)
    visa_sponsorship: YesNoUnstated = "unstated"
    roles: list[Role] = Field(default_factory=list)
    technologies_raw: list[str] = Field(default_factory=list)
    ai_signals: AISignals = Field(default_factory=AISignals)
    application: Application = Field(default_factory=Application)
    hiring_count_hint: str | None = None


SCHEMA_VERSION = 1
