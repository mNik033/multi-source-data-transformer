import sys
import os
import tempfile
import json
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from models import CanonicalProfile, Location, Skill
from projector import Projector
from pydantic import ValidationError

def create_temp_config(config_data):
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, 'w') as f:
        json.dump(config_data, f)
    return path

def test_projector_basic_and_nested():
    """Verify standard field mapping and nested object lookup (location.city)."""
    config = [
        {"field": "name", "path": "full_name", "type": "string"},
        {"field": "city", "path": "location.city", "type": "string"}
    ]
    cfg_path = create_temp_config(config)
    try:
        projector = Projector(cfg_path)
        profile = CanonicalProfile(
            candidate_id="123",
            full_name="John Doe",
            emails=[],
            phones=[],
            location=Location(city="San Francisco", region="CA", country="US"),
            links=None,
            headline=None,
            years_experience=None,
            skills=[],
            experience=[],
            education=[],
            provenance=[],
            overall_confidence=1.0
        )
        res = projector.project(profile)
        assert res["name"] == "John Doe"
        assert res["city"] == "San Francisco"
    finally:
        os.remove(cfg_path)

def test_projector_array_indexing_and_mapping():
    """Verify array indexing (emails[0]) and array mapping (skills[].name)."""
    config = [
        {"field": "primary_email", "path": "emails[0]", "type": "string"},
        {"field": "all_skills", "path": "skills[].name", "type": "list"}
    ]
    cfg_path = create_temp_config(config)
    try:
        projector = Projector(cfg_path)
        profile = CanonicalProfile(
            candidate_id="123",
            full_name="John Doe",
            emails=["primary@test.com", "secondary@test.com"],
            phones=[],
            location=None,
            links=None,
            headline=None,
            years_experience=None,
            skills=[
                Skill(name="react js", confidence=0.9, sources=["CSV"]),
                Skill(name="python", confidence=0.8, sources=["ATS"])
            ],
            experience=[],
            education=[],
            provenance=[],
            overall_confidence=1.0
        )
        res = projector.project(profile)
        assert res["primary_email"] == "primary@test.com"
        assert res["all_skills"] == ["react js", "python"]
    finally:
        os.remove(cfg_path)

def test_projector_on_missing_policies():
    """Verify 'null', 'omit', and 'error' missing value policies work correctly."""
    profile = CanonicalProfile(
        candidate_id="123",
        full_name="John",
        emails=[],
        phones=[],
        location=None,
        links=None,
        headline=None,
        years_experience=None,
        skills=[],
        experience=[],
        education=[],
        provenance=[],
        overall_confidence=1.0
    )

    # 1. Null policy
    cfg_null = create_temp_config([
        {"field": "city", "path": "location.city", "type": "string", "on_missing": "null"}
    ])
    try:
        projector = Projector(cfg_null)
        res = projector.project(profile)
        assert "city" in res
        assert res["city"] is None
    finally:
        os.remove(cfg_null)

    # 2. Omit policy
    cfg_omit = create_temp_config([
        {"field": "city", "path": "location.city", "type": "string", "on_missing": "omit"}
    ])
    try:
        projector = Projector(cfg_omit)
        res = projector.project(profile)
        assert "city" not in res
    finally:
        os.remove(cfg_omit)

    # 3. Error policy
    cfg_err = create_temp_config([
        {"field": "city", "path": "location.city", "type": "string", "on_missing": "error"}
    ])
    try:
        projector = Projector(cfg_err)
        with pytest.raises(ValueError):
            projector.project(profile)
    finally:
        os.remove(cfg_err)

def test_projector_validation_type_mismatch():
    """Verify validation fails if output type does not match dynamic schema."""
    config = [{"field": "exp_years", "path": "full_name", "type": "int"}]
    cfg_path = create_temp_config(config)
    try:
        projector = Projector(cfg_path)
        profile = CanonicalProfile(
            candidate_id="123",
            full_name="John Doe",  # String instead of Int
            emails=[],
            phones=[],
            location=None,
            links=None,
            headline=None,
            years_experience=None,
            skills=[],
            experience=[],
            education=[],
            provenance=[],
            overall_confidence=1.0
        )
        with pytest.raises(ValidationError):
            projector.project(profile)
    finally:
        os.remove(cfg_path)
