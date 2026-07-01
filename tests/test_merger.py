import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import pytest
from merger import CandidateMerger
from models import SourceRecord, ExtractedCandidate, ExtractedExperience, ExtractedEducation

def create_mock_record(source, name=None, email=None, city=None, headline=None, github=None, exp=None, edu=None, skills=None):
    return SourceRecord(
        source_name=source,
        method="mock",
        data=ExtractedCandidate(
            full_name=name,
            emails=[email] if email else [],
            phones=[],
            city=city,
            headline=headline,
            github=github,
            experience=exp or [],
            education=edu or [],
            skills=skills or []
        )
    )

def test_normal_1_perfect_match_email():
    """1. Normal: Exact email match merges into 1 profile."""
    r1 = create_mock_record("Recruiter_CSV", name="John", email="j@test.com", city="NYC")
    r2 = create_mock_record("ATS_JSON", name="John", email="j@test.com", headline="Dev")
    merger = CandidateMerger()
    res = merger.merge([r1, r2])
    assert len(res) == 1
    assert res[0].location.city == "NYC"
    assert res[0].headline == "Dev"

def test_normal_2_perfect_match_name_no_email():
    """2. Normal: Exact name match does NOT merge if no hard identifiers are present."""
    r1 = create_mock_record("Recruiter_CSV", name="Alice Smith", city="NYC")
    r2 = create_mock_record("ATS_JSON", name="Alice Smith", headline="Dev")
    merger = CandidateMerger()
    res = merger.merge([r1, r2])
    # Under hard-matching-only, they should remain split (2 profiles)
    assert len(res) == 2

def test_hard_match_phone_and_links():
    """Verify that records merge on phone, github, or linkedin matches even without email matches."""
    # Merge on Phone
    r1 = SourceRecord(
        source_name="CSV", method="mock",
        data=ExtractedCandidate(full_name="Alice", phones=["+15551234567"])
    )
    r2 = SourceRecord(
        source_name="ATS", method="mock",
        data=ExtractedCandidate(full_name="Alice Smith", phones=["+15551234567"], emails=["alice@test.com"])
    )
    
    # Merge on GitHub
    r3 = SourceRecord(
        source_name="GitHub_API", method="mock",
        data=ExtractedCandidate(full_name="Bob", github="github.com/bobdev")
    )
    r4 = SourceRecord(
        source_name="Notes", method="mock",
        data=ExtractedCandidate(full_name="Robert", github="github.com/bobdev", emails=["bob@test.com"])
    )
    
    merger = CandidateMerger()
    res = merger.merge([r1, r2, r3, r4])
    
    # We should have 2 merged profiles instead of 4
    assert len(res) == 2
    
    alice = next(p for p in res if "Alice" in p.full_name)
    assert "alice@test.com" in alice.emails
    assert "+15551234567" in alice.phones
    
    bob = next(p for p in res if "Bob" in p.full_name or "Robert" in p.full_name)
    assert "bob@test.com" in bob.emails
    assert bob.links.github == "github.com/bobdev"

def test_normal_3_different_candidates():
    """3. Normal: Completely different candidates result in 2 profiles."""
    r1 = create_mock_record("Recruiter_CSV", name="Alice", email="a@test.com")
    r2 = create_mock_record("ATS_JSON", name="Bob", email="b@test.com")
    merger = CandidateMerger()
    res = merger.merge([r1, r2])
    assert len(res) == 2

def test_normal_4_list_merging():
    """4. Normal: Emails and phones are combined in list fields."""
    r1 = SourceRecord(
        source_name="CSV", method="mock",
        data=ExtractedCandidate(full_name="Alice", emails=["a@1.com", "shared@test.com"], phones=["+123"])
    )
    r2 = SourceRecord(
        source_name="ATS", method="mock",
        data=ExtractedCandidate(full_name="Alice", emails=["a@2.com", "shared@test.com"], phones=["+456"])
    )
    merger = CandidateMerger()
    res = merger.merge([r1, r2])
    assert len(res) == 1
    assert set(res[0].emails) == {"a@1.com", "a@2.com", "shared@test.com"}
    assert "+123" in res[0].phones and "+456" in res[0].phones

def test_normal_5_confidence_overwrite():
    """5. Normal: ATS_JSON (0.80 for default) overrides Recruiter_CSV (0.70 for default)."""
    r1 = create_mock_record("Recruiter_CSV", name="Bob", email="b@test.com", headline="Bad Headline")
    r2 = create_mock_record("ATS_JSON", name="Bob", email="b@test.com", headline="Good Headline")
    merger = CandidateMerger()
    res = merger.merge([r1, r2])
    assert len(res) == 1
    assert res[0].headline == "Good Headline"

def test_edge_1_consensus_boosting():
    """6. Edge: If two sources agree on a scalar, confidence boosts."""
    r1 = create_mock_record("Recruiter_CSV", name="Bob", email="b@test.com", headline="Engineer")
    r2 = create_mock_record("ATS_JSON", name="Bob", email="b@test.com", headline="Engineer")
    merger = CandidateMerger()
    res = merger.merge([r1, r2])
    assert len(res) == 1
    assert res[0].headline == "Engineer"
    # CSV default conf = 0.70, ATS default = 0.80. Boost = 1 - (1-0.70)*(1-0.80) = 1 - (0.3*0.2) = 0.94
    assert res[0].overall_confidence > 0.85

def test_edge_2_experience_preserves_multiple_roles():
    """7. Edge: Candidate with 2 roles at the same company preserves both."""
    e1 = ExtractedExperience(company="Google", title="SE", start="2020", end="2021", summary="")
    e2 = ExtractedExperience(company="Google", title="Senior SE", start="2021", end="2022", summary="")
    r1 = create_mock_record("ATS_JSON", name="Bob", email="b@test.com", exp=[e1, e2])
    merger = CandidateMerger()
    res = merger.merge([r1])
    assert len(res[0].experience) == 2

def test_edge_3_experience_deduplicates_exact_roles():
    """8. Edge: Overlapping exact role at same company is deduplicated."""
    e1 = ExtractedExperience(company="Google", title="SE", start="2020", end="2021", summary="CSV summary")
    e2 = ExtractedExperience(company="Google", title="SE", start="2020", end="2021", summary="ATS summary")
    r1 = create_mock_record("Recruiter_CSV", name="Bob", email="b@test.com", exp=[e1])
    r2 = create_mock_record("ATS_JSON", name="Bob", email="b@test.com", exp=[e2])
    merger = CandidateMerger()
    res = merger.merge([r1, r2])
    assert len(res) == 1
    assert len(res[0].experience) == 1
    assert res[0].experience[0].summary == "ATS summary" # ATS (0.8) > CSV (0.7) for experience

def test_edge_4_missing_values_dont_overwrite():
    """9. Edge: A None value from a higher confidence source shouldn't wipe out a valid value."""
    r1 = create_mock_record("Recruiter_CSV", name="Bob", email="b@test.com", github="http://github.com/bob")
    r2 = create_mock_record("ATS_JSON", name="Bob", email="b@test.com", github=None)
    merger = CandidateMerger()
    res = merger.merge([r1, r2])
    assert res[0].links.github == "http://github.com/bob"

def test_edge_5_case_insensitive_grouping():
    """10. Edge: Emails should group regardless of case."""
    r1 = create_mock_record("Recruiter_CSV", name="Bob", email="BOB@TEST.COM", city="NYC")
    r2 = create_mock_record("ATS_JSON", name="Bob", email="bob@test.com", city="SF")
    merger = CandidateMerger()
    res = merger.merge([r1, r2])
    assert len(res) == 1
    assert res[0].location.city == "SF"
    
def test_edge_6_transitive_matching():
    """11. Edge: Transitive matching across 3 records (A=email1, B=email1+email2, C=email2)."""
    r1 = SourceRecord(source_name="S1", method="mock", data=ExtractedCandidate(full_name="Bob", emails=["e1@test.com"]))
    r2 = SourceRecord(source_name="S2", method="mock", data=ExtractedCandidate(full_name="Bob", emails=["e1@test.com", "e2@test.com"]))
    r3 = SourceRecord(source_name="S3", method="mock", data=ExtractedCandidate(full_name="Bob", emails=["e2@test.com"]))
    
    merger = CandidateMerger()
    res = merger.merge([r1, r2, r3])
    assert len(res) == 1
    assert set(res[0].emails) == {"e1@test.com", "e2@test.com"}

def test_edge_7_normalizers_integration():
    """12. Edge: Pipeline correctly triggers deterministic normalizers on raw input fields during merge."""
    r = SourceRecord(
        source_name="Recruiter_CSV",
        method="mock",
        data=ExtractedCandidate(
            full_name="Bob",
            emails=["b@test.com"],
            phones=["(555) 123-4567"],
            country="United States",
            experience=[
                ExtractedExperience(company="Google", title="SE", start="Jan 2021", end="Present", summary="")
            ],
            education=[
                ExtractedEducation(institution="Stanford", degree="Bachelor of Science", field_of_study="CS", end_year="2023-05")
            ],
            skills=["reactjs"]
        )
    )
    merger = CandidateMerger()
    res = merger.merge([r])
    assert res[0].phones[0] == "+15551234567"
    assert res[0].location.country == "US"
    assert res[0].experience[0].start == "2021-01"

def test_edge_8_skills_consensus():
    """13. Edge: Skills canonicalization allows matching versions to boost consensus confidence."""
    # S1 has ReactJS (conf 0.60), S2 has reactjs (conf 0.70)
    # Both canonicalize to "reactjs".
    # Boost: 1 - (1 - 0.60)*(1 - 0.70) = 1 - 0.40 * 0.30 = 0.88
    r1 = SourceRecord(source_name="Recruiter_CSV", method="mock", data=ExtractedCandidate(full_name="Bob", emails=["b@test.com"], skills=["ReactJS"]))
    r2 = SourceRecord(source_name="ATS_JSON", method="mock", data=ExtractedCandidate(full_name="Bob", emails=["b@test.com"], skills=["reactjs"]))
    
    merger = CandidateMerger()
    res = merger.merge([r1, r2])
    assert len(res[0].skills) == 1
    assert res[0].skills[0].name == "reactjs"
    assert res[0].skills[0].confidence == 0.88

