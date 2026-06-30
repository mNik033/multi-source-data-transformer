import csv
import logging
from typing import List
from models import SourceRecord, ExtractedCandidate, ExtractedExperience

logger = logging.getLogger(__name__)

class CSVLoader:
    """
    Loads candidates from a Recruiter CSV export.
    Expected columns: name, email, phone, current_company, title
    """
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.source_name = "Recruiter_CSV"
        self.method = "csv_parser"

    def load(self) -> List[SourceRecord]:
        records = []
        try:
            with open(self.file_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                # Normalize column names to handle variations like "Name", "NAME", " email "
                if reader.fieldnames:
                    reader.fieldnames = [str(field).strip().lower() for field in reader.fieldnames]

                for row in reader:
                    try:
                        # Extract basic fields
                        name = row.get('name', '').strip() or None
                        email = row.get('email', '').strip()
                        phone = row.get('phone', '').strip()
                        
                        emails = [email] if email else []
                        phones = [phone] if phone else []

                        # Extract experience
                        company = row.get('current_company', '').strip()
                        title = row.get('title', '').strip()
                        
                        experience = []
                        if company or title:
                            experience.append(ExtractedExperience(
                                company=company or "Unknown",
                                title=title or "Unknown"
                            ))

                        # Build the intermediate ExtractedCandidate
                        extracted = ExtractedCandidate(
                            full_name=name,
                            emails=emails,
                            phones=phones,
                            experience=experience
                        )

                        # Wrap in a SourceRecord
                        records.append(SourceRecord(
                            source_name=self.source_name,
                            method=self.method,
                            data=extracted
                        ))
                    except Exception as row_e:
                        logger.warning(f"Error parsing CSV row in {self.file_path}: {row_e}")
                        continue

        except FileNotFoundError:
            logger.error(f"CSV file not found: {self.file_path}")
        except Exception as e:
            logger.error(f"Failed to read CSV {self.file_path}: {e}")

        return records
