import argparse
import json
import logging
import os
import sys
from typing import List
from dotenv import load_dotenv

from models import SourceRecord
from loaders import CSVLoader, AtsJsonLoader, NotesLoader, GitHubLoader
from merger import CandidateMerger
from projector import Projector

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def harvest_github_usernames(records: List[SourceRecord]) -> set:
    """Extracts unique GitHub usernames from all loaded records."""
    usernames = set()
    for r in records:
        if r.data.github:
            url_or_name = r.data.github.strip().rstrip('/')
            if 'github.com/' in url_or_name:
                username = url_or_name.split('github.com/')[-1]
            else:
                username = url_or_name
            if username:
                usernames.add(username)
    return usernames

def main():
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="Multi-Source Data Transformer Pipeline")
    parser.add_argument("--csv", help="Path to input CSV file")
    parser.add_argument("--ats", help="Path to ATS JSON payload")
    parser.add_argument("--notes", help="Path to recruiter notes folder")
    parser.add_argument("--config", help="Path to projection config JSON (optional)")
    parser.add_argument("--out", help="Path to output JSON file", default="output.json")
    
    args = parser.parse_args()
    
    all_records: List[SourceRecord] = []
    
    # 1. Load Data
    logger.info("--- Starting Ingestion Phase ---")
    if args.csv:
        logger.info(f"Loading CSV from {args.csv}")
        all_records.extend(CSVLoader(args.csv).load())
        
    if args.ats:
        logger.info(f"Loading ATS JSON from {args.ats}")
        all_records.extend(AtsJsonLoader(args.ats).load())
        
    if args.notes:
        logger.info(f"Loading Notes from {args.notes}")
        all_records.extend(NotesLoader(args.notes).load())
        
    # Harvest and load GitHub data dynamically based on the other sources!
    github_usernames = harvest_github_usernames(all_records)
    if github_usernames:
        logger.info(f"Harvested {len(github_usernames)} GitHub profiles. Fetching from API...")
        for username in github_usernames:
            all_records.extend(GitHubLoader(username).load())
            
    if not all_records:
        logger.warning("No records loaded. Exiting.")
        sys.exit(0)
        
    logger.info(f"Total raw records loaded: {len(all_records)}")
    
    # 2. Merge Data
    logger.info("--- Starting Merge Phase ---")
    merger = CandidateMerger()
    canonical_profiles = merger.merge(all_records)
    logger.info(f"Merged into {len(canonical_profiles)} canonical profiles.")
    
    # 3. Project Data
    final_output = []
    if args.config:
        logger.info(f"--- Starting Projection Phase (config: {args.config}) ---")
        try:
            projector = Projector(args.config)
            
            for profile in canonical_profiles:
                try:
                    projected_data = projector.project(profile)
                    final_output.append(projected_data)
                except Exception as e:
                    logger.error(f"Failed to project candidate {profile.candidate_id}: {e}")
        except Exception as e:
            logger.error(f"Pipeline failed during projection: {e}")
            sys.exit(1)
    else:
        logger.info("--- No config provided. Outputting raw canonical profiles. ---")
        # Dump the Pydantic models directly to dicts for the default output
        final_output = [profile.model_dump() for profile in canonical_profiles]
                
    # 4. Write Output
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=2)
        
    logger.info(f"Successfully wrote {len(final_output)} records to {args.out}")

if __name__ == "__main__":
    main()
