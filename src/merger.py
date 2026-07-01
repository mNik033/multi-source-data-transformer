import uuid
import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict

from models import (
    SourceRecord, 
    CanonicalProfile, 
    Skill, 
    Experience, 
    Education, 
    ProvenanceItem, 
    Location, 
    Links
)
from normalizers import normalize_phone, normalize_date, canonicalize_skill, normalize_country

logger = logging.getLogger(__name__)

# Source-Field Confidence Matrix
CONFIDENCE_MATRIX = {
    "full_name":  {"Recruiter_CSV": 0.80, "ATS_JSON": 0.85, "Recruiter_Notes": 0.90, "GitHub_API": 0.40},
    "emails":     {"Recruiter_CSV": 0.90, "ATS_JSON": 0.95, "Recruiter_Notes": 0.90, "GitHub_API": 0.80},
    "phones":     {"Recruiter_CSV": 0.85, "ATS_JSON": 0.90, "Recruiter_Notes": 0.95, "GitHub_API": 0.00},
    "skills":     {"Recruiter_CSV": 0.60, "ATS_JSON": 0.70, "Recruiter_Notes": 0.80, "GitHub_API": 0.95},
    "experience": {"Recruiter_CSV": 0.70, "ATS_JSON": 0.80, "Recruiter_Notes": 0.85, "GitHub_API": 0.50},
    "education":  {"Recruiter_CSV": 0.60, "ATS_JSON": 0.80, "Recruiter_Notes": 0.85, "GitHub_API": 0.30},
    "default":    {"Recruiter_CSV": 0.70, "ATS_JSON": 0.80, "Recruiter_Notes": 0.80, "GitHub_API": 0.60}
}

def get_confidence(field: str, source: str) -> float:
    # Treat dynamic .txt notes files as "Recruiter_Notes" for matrix lookup
    if source.endswith(".txt"):
        source_type = "Recruiter_Notes"
    else:
        source_type = source
        
    field_matrix = CONFIDENCE_MATRIX.get(field, CONFIDENCE_MATRIX["default"])
    return field_matrix.get(source_type, 0.50)


class CandidateMerger:
    """
    Normalizes, groups, and merges SourceRecords into CanonicalProfiles.
    Resolves conflicts using a Source-Field Confidence Matrix and Consensus Boosting.
    """
    def __init__(self):
        pass

    def normalize_record(self, record: SourceRecord):
        """Applies deterministic normalizers to a single raw record before matching."""
        data = record.data
        if data.phones:
            data.phones = [p for p in (normalize_phone(p) for p in data.phones) if p]
        
        if data.country:
            data.country = normalize_country(data.country)
            
        if data.skills:
            data.skills = [s for s in (canonicalize_skill(s) for s in data.skills) if s]
            
        for exp in data.experience:
            exp.start = normalize_date(exp.start)
            exp.end = normalize_date(exp.end)
            
        for edu in data.education:
            edu.end_year = normalize_date(edu.end_year) 

class UnionFind:
    def __init__(self, size):
        self.parent = list(range(size))
        
    def find(self, i):
        if self.parent[i] == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]
        
    def union(self, i, j):
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j

    def group_records(self, records: List[SourceRecord]) -> List[List[SourceRecord]]:
        """
        Groups SourceRecords by matching Hard Identifiers only (email, phone, github, linkedin).
        Uses an O(N) Union-Find algorithm. Removes all soft matching (e.g. name, city) 
        to ensure deterministic, non-corrupting merges.
        """
        n = len(records)
        if n == 0:
            return []
            
        uf = UnionFind(n)
        
        email_to_ids = defaultdict(list)
        phone_to_ids = defaultdict(list)
        github_to_ids = defaultdict(list)
        linkedin_to_ids = defaultdict(list)
        
        for i, record in enumerate(records):
            data = record.data
            
            for e in data.emails:
                if e: email_to_ids[e.lower().strip()].append(i)
                
            for p in data.phones:
                if p: phone_to_ids[p.strip()].append(i)
                
            if data.github:
                github_to_ids[data.github.lower().strip()].append(i)
                
            if data.linkedin:
                linkedin_to_ids[data.linkedin.lower().strip()].append(i)
                
        # Union by any hard identifier match
        for ids in email_to_ids.values():
            for i in range(1, len(ids)):
                uf.union(ids[0], ids[i])
                
        for ids in phone_to_ids.values():
            for i in range(1, len(ids)):
                uf.union(ids[0], ids[i])
                
        for ids in github_to_ids.values():
            for i in range(1, len(ids)):
                uf.union(ids[0], ids[i])
                
        for ids in linkedin_to_ids.values():
            for i in range(1, len(ids)):
                uf.union(ids[0], ids[i])
                    
        groups_dict = defaultdict(list)
        for i in range(n):
            groups_dict[uf.find(i)].append(records[i])
            
        return list(groups_dict.values())
        
    def merge(self, records: List[SourceRecord]) -> List[CanonicalProfile]:
        # 1. Normalize all inputs in-place
        for r in records:
            self.normalize_record(r)
            
        # 2. Group into candidate buckets
        groups = self.group_records(records)
        
        # 3. Merge each bucket into a CanonicalProfile
        profiles = []
        for group in groups:
            profile = self._merge_group(group)
            profiles.append(profile)
            
        return profiles

    def _merge_group(self, group: List[SourceRecord]) -> CanonicalProfile:
        provenance = []
        
        # State tracking for scalar fields
        scalars = {
            "full_name": {"val": None, "conf": 0.0, "src": None, "method": None},
            "city": {"val": None, "conf": 0.0, "src": None, "method": None},
            "region": {"val": None, "conf": 0.0, "src": None, "method": None},
            "country": {"val": None, "conf": 0.0, "src": None, "method": None},
            "linkedin": {"val": None, "conf": 0.0, "src": None, "method": None},
            "github": {"val": None, "conf": 0.0, "src": None, "method": None},
            "portfolio": {"val": None, "conf": 0.0, "src": None, "method": None},
            "headline": {"val": None, "conf": 0.0, "src": None, "method": None},
            "years_experience": {"val": None, "conf": 0.0, "src": None, "method": None},
        }

        all_emails = set()
        all_phones = set()
        
        # Skills tracking: canonical name -> list of confidences
        skills_map = defaultdict(lambda: {"confidences": [], "sources": set(), "methods": set()})
        
        # Experience / Education maps (keyed by company / institution)
        exp_map = {}
        edu_map = {}
        
        for record in group:
            src = record.source_name
            ext_method = record.method
            data = record.data
            
            # 1. Merge Scalars using Confidence Matrix & Consensus Boosting
            for field in scalars.keys():
                val = getattr(data, field)
                if val:
                    conf = get_confidence(field, src)
                    current_conf = scalars[field]["conf"]
                    
                    if val == scalars[field]["val"]:
                        # Consensus boost! Multiple sources agree on the same value.
                        new_conf = 1 - ((1 - current_conf) * (1 - conf))
                        scalars[field]["conf"] = new_conf
                        if conf > current_conf:
                            scalars[field]["src"] = src
                            scalars[field]["method"] = ext_method
                    elif conf > current_conf:
                        # Value mismatch, but this source is more trusted. Overwrite.
                        scalars[field] = {"val": val, "conf": conf, "src": src, "method": ext_method}
            
            # 2. Merge Lists
            if data.emails:
                for e in data.emails:
                    if e.lower() not in all_emails:
                        all_emails.add(e.lower())
                        provenance.append(ProvenanceItem(field="emails", source=src, method=ext_method))
                        
            if data.phones:
                for p in data.phones:
                    if p not in all_phones:
                        all_phones.add(p)
                        provenance.append(ProvenanceItem(field="phones", source=src, method=ext_method))
            
            # 3. Aggregate Skills
            if data.skills:
                s_conf = get_confidence("skills", src)
                for s in data.skills:
                    skills_map[s]["confidences"].append(s_conf)
                    skills_map[s]["sources"].add(src)
                    skills_map[s]["methods"].add(ext_method)

            # 4. Deduplicate Experience
            exp_conf = get_confidence("experience", src)
            for exp in data.experience:
                key = f"{exp.company.lower()}_{exp.title.lower()}"
                if key not in exp_map or exp_conf > exp_map[key]["conf"]:
                    exp_map[key] = {"data": exp, "conf": exp_conf, "src": src, "method": ext_method}

            # 5. Deduplicate Education
            edu_conf = get_confidence("education", src)
            for edu in data.education:
                deg = edu.degree.lower() if edu.degree else "unknown"
                key = f"{edu.institution.lower()}_{deg}"
                if key not in edu_map or edu_conf > edu_map[key]["conf"]:
                    edu_map[key] = {"data": edu, "conf": edu_conf, "src": src, "method": ext_method}

        # --- Assemble Canonical Profile ---
        
        # Assemble provenance for scalars
        for field, info in scalars.items():
            if info["val"] is not None:
                provenance.append(ProvenanceItem(field=field, source=info["src"], method=info["method"]))

        # Finalize Skills (Calculate boosted confidence)
        final_skills = []
        for s_name, s_info in skills_map.items():
            combined_conf = 1.0
            for c in s_info["confidences"]:
                combined_conf *= (1.0 - c)
            combined_conf = 1.0 - combined_conf
            
            final_skills.append(Skill(
                name=s_name,
                confidence=round(combined_conf, 3),
                sources=list(s_info["sources"])
            ))
            for m in s_info["methods"]:
                provenance.append(ProvenanceItem(field=f"skills[{s_name}]", source=list(s_info["sources"])[0], method=m))

        # Finalize Experience
        final_experience = []
        for key, info in exp_map.items():
            exp_data = info["data"]
            final_experience.append(Experience(
                company=exp_data.company,
                title=exp_data.title,
                start=exp_data.start,
                end=exp_data.end,
                summary=exp_data.summary
            ))
            provenance.append(ProvenanceItem(field=f"experience[{exp_data.company}]", source=info["src"], method=info["method"]))

        # Finalize Education
        final_education = []
        for key, info in edu_map.items():
            edu_data = info["data"]
            final_education.append(Education(
                institution=edu_data.institution,
                degree=edu_data.degree,
                field=edu_data.field_of_study,
                end_year=edu_data.end_year
            ))
            provenance.append(ProvenanceItem(field=f"education[{edu_data.institution}]", source=info["src"], method=info["method"]))

        # Location and Links structs
        loc = Location(
            city=scalars["city"]["val"], 
            region=scalars["region"]["val"], 
            country=scalars["country"]["val"]
        )
        if not any([loc.city, loc.region, loc.country]): loc = None
        
        links = Links(
            linkedin=scalars["linkedin"]["val"],
            github=scalars["github"]["val"],
            portfolio=scalars["portfolio"]["val"]
        )
        if not any([links.linkedin, links.github, links.portfolio]): links = None

        # Calculate Overall Confidence (average of populated scalar fields)
        conf_scores = [info["conf"] for info in scalars.values() if info["val"] is not None]
        overall_confidence = sum(conf_scores) / len(conf_scores) if conf_scores else 0.0

        return CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name=scalars["full_name"]["val"] or "Unknown",
            emails=list(all_emails),
            phones=list(all_phones),
            location=loc,
            links=links,
            headline=scalars["headline"]["val"],
            years_experience=scalars["years_experience"]["val"],
            skills=sorted(final_skills, key=lambda s: s.confidence, reverse=True),
            experience=final_experience,
            education=final_education,
            provenance=provenance,
            overall_confidence=round(overall_confidence, 3)
        )
