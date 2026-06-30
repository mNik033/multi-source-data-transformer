from typing import List, Optional
from pydantic import BaseModel, Field

# ---- Canonical Profile Schemas (Target Output) -----

class Location(BaseModel):
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None

class Links(BaseModel):
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: List[str] = Field(default_factory=list)

class Skill(BaseModel):
    name: str
    confidence: float
    sources: List[str] = Field(default_factory=list)

class Experience(BaseModel):
    company: str
    title: str
    start: Optional[str] = None
    end: Optional[str] = None
    summary: Optional[str] = None

class Education(BaseModel):
    institution: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = Field(default=None, alias="field")
    end_year: Optional[str] = None

    class Config:
        populate_by_name = True

class ProvenanceItem(BaseModel):
    field: str
    source: str
    method: str

class CanonicalProfile(BaseModel):
    candidate_id: str
    full_name: str
    emails: List[str] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)
    location: Optional[Location] = None
    links: Optional[Links] = None
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: List[Skill] = Field(default_factory=list)
    experience: List[Experience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    provenance: List[ProvenanceItem] = Field(default_factory=list)
    overall_confidence: float = 0.0


# ---- Extracted Candidate Schemas (Loader Output) ----

class ExtractedExperience(BaseModel):
    company: str
    title: str
    start: Optional[str] = Field(default=None, description="Start date in YYYY-MM or human format")
    end: Optional[str] = Field(default=None, description="End date in YYYY-MM or human format, or 'Present'")
    summary: Optional[str] = None

class ExtractedEducation(BaseModel):
    institution: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = Field(default=None, alias="field")
    end_year: Optional[str] = None

    class Config:
        populate_by_name = True

class ExtractedCandidate(BaseModel):
    """Unified target schema for all parsed/extracted inputs before normalization and merging."""
    full_name: Optional[str] = None
    emails: List[str] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: List[str] = Field(default_factory=list)
    experience: List[ExtractedExperience] = Field(default_factory=list)
    education: List[ExtractedEducation] = Field(default_factory=list)


class SourceRecord(BaseModel):
    """Represents a record of data extracted from a single source."""
    source_name: str
    method: str
    data: ExtractedCandidate
