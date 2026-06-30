import csv
import glob
import json
import logging
import os
import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List

load_dotenv()

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

class AtsExperienceExtraction(BaseModel):
    company: str = Field(description="The name of the company where the candidate worked.")
    title: str = Field(description="The job title held by the candidate.")
    start: str | None = Field(default=None, description="Start date strictly in YYYY-MM format. Normalize any variation (e.g., 'January 2020', 'Jan-20', '01/2020') to '2020-01'.")
    end: str | None = Field(default=None, description="End date strictly in YYYY-MM format, or 'Present'. Normalize any variation (e.g., 'current', 'Present', 'Now') to 'Present'.")
    summary: str | None = Field(default=None, description="A brief summary of the role or responsibilities. Extract this exactly as-is. Do not add or modify the summary. Do not add any extra information.")

class AtsEducationExtraction(BaseModel):
    institution: str = Field(description="The name of the university or school.")
    degree: str | None = Field(default=None, description="The degree obtained. Normalize any variation (e.g., 'Bachelor of Science', 'B.Sc') to their full forms like 'Bachelor of Science', 'Master of Science', 'Doctor of Philosophy'.")
    field_of_study: str | None = Field(default=None, description="The major or field of study. Normalize variations (e.g., 'CS', 'Comp Sci') to full names (e.g., 'Computer Science').")
    end_year: str | None = Field(default=None, description="The year of graduation strictly in YYYY format. Normalize any variation (e.g., 'Class of 23', '2023') to '2023'.")

class AtsCandidateExtraction(BaseModel):
    full_name: str | None = Field(default=None, description="The candidate's full name.")
    emails: List[str] = Field(default_factory=list, description="A list of all email addresses found for the candidate.")
    phones: List[str] = Field(default_factory=list, description="A list of all phone numbers found for the candidate. Normalize to E.164 format (e.g., '(555) 123-4567' to '+15551234567') if possible.")
    city: str | None = Field(default=None, description="The city where the candidate is located.")
    region: str | None = Field(default=None, description="The state or region where the candidate is located.")
    country: str | None = Field(default=None, description="Must be a 2-letter ISO-3166 Alpha-2 country code. Normalize any variation (e.g., 'United States', 'USA', 'U.S.') to 'US'.")
    linkedin: str | None = Field(default=None, description="The candidate's LinkedIn URL.")
    github: str | None = Field(default=None, description="The candidate's GitHub URL.")
    portfolio: str | None = Field(default=None, description="The candidate's personal website or portfolio URL.")
    headline: str | None = Field(default=None, description="The candidate's headline or professional summary.")
    years_experience: float | None = Field(default=None, description="Total years of professional experience, if stated or calculable.")
    skills: List[str] = Field(default_factory=list, description="A list of technical and professional skills derived.")
    experience: List[AtsExperienceExtraction] = Field(default_factory=list, description="The candidate's work history.")
    education: List[AtsEducationExtraction] = Field(default_factory=list, description="The candidate's educational background.")
    source_file: str | None = Field(default=None, description="If the input text specifies a source file or note name for this candidate, capture it here.")

class AtsExtractionList(BaseModel):
    candidates: List[AtsCandidateExtraction] = Field(
        description="A list of all candidates extracted from the ATS JSON payload."
    )

class AtsJsonLoader:
    """
    Loads candidates from a messy/semi-structured ATS JSON export.
    Uses Gemini structured extraction to map arbitrary fields to our schema.
    """
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.source_name = "ATS_JSON"
        self.method = "gemini_schema_extraction"
        
        # Initialize Gemini Client
        api_key = os.environ.get("GEMINI_API_KEY", "")
        self.client = genai.Client(api_key=api_key) if api_key and genai else None

    def load(self) -> List[SourceRecord]:
        records = []
        if not self.client:
            logger.error("GEMINI_API_KEY missing. Could not parse ATS JSON.")
            return records
            
        try:
            with open(self.file_path, mode='r', encoding='utf-8') as f:
                raw_json = f.read()

            prompt = (
                "You are an expert data extraction system. "
                "The following text is an ATS JSON export containing one or more candidate profiles. "
                "The schema is unknown and may have strange or nested field names. "
                "Extract all candidates and map the data precisely into the requested schema. "
                "CRITICAL: Do not invent, hallucinate, or insert any data that is not explicitly present in the text. "
                "If a field is missing, return null. "
                "Ensure all dates, country codes, and formats strictly adhere to the field descriptions."
            )

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AtsExtractionList,
                temperature=0.1,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
            )

            response = self.client.models.generate_content(
                model='gemini-3.5-flash',
                contents=[prompt, raw_json],
                config=config
            )

            if response.parsed and response.parsed.candidates:
                for extracted_cand in response.parsed.candidates:
                    candidate = ExtractedCandidate(**extracted_cand.model_dump())
                    records.append(SourceRecord(
                        source_name=self.source_name,
                        method=self.method,
                        data=candidate
                    ))
                    
        except FileNotFoundError:
            logger.error(f"ATS JSON file not found: {self.file_path}")
        except Exception as e:
            logger.error(f"Failed to extract ATS JSON via Gemini: {e}")

        return records

class NotesLoader:
    """
    Loads candidate data from a folder of unstructured recruiter notes (.txt files).
    Reuses the robust AtsExtractionList schemas to ensure determinism.
    """
    def __init__(self, folder_path: str):
        self.folder_path = folder_path
        self.method = "gemini_schema_extraction"
        
        api_key = os.environ.get("GEMINI_API_KEY", "")
        self.client = genai.Client(api_key=api_key) if api_key and genai else None

    def load(self) -> List[SourceRecord]:
        records = []
        if not self.client:
            logger.error("GEMINI_API_KEY missing. Could not parse Notes.")
            return records
            
        txt_files = glob.glob(os.path.join(self.folder_path, "*.txt"))
        if not txt_files:
            logger.warning(f"No .txt files found in {self.folder_path}")
            return records

        combined_text = ""
        for file_path in txt_files:
            try:
                with open(file_path, mode='r', encoding='utf-8') as f:
                    content = f.read()
                    filename = os.path.basename(file_path)
                    combined_text += f"\n--- START OF NOTE: {filename} ---\n{content}\n--- END OF NOTE: {filename} ---\n"
            except Exception as e:
                logger.error(f"Failed to read file {file_path}: {e}")

        if not combined_text.strip():
            return records

        try:
            prompt = (
                "You are an expert data extraction system. "
                "The following text contains unstructured recruiter notes for MULTIPLE candidates. "
                "Each note is separated by delimiters like '--- START OF NOTE: filename.txt ---'. "
                "Extract all candidates from all notes and map the data precisely into the requested schema. "
                "CRITICAL: You MUST populate the `source_file` field with the filename provided in the delimiter for that candidate! "
                "Do not invent, hallucinate, or insert any data that is not explicitly present. "
                "If a field is missing, return null. "
                "Ensure all dates, country codes, and formats strictly adhere to the field descriptions."
            )

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AtsExtractionList,
                temperature=0.1,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
            )

            response = self.client.models.generate_content(
                model='gemini-3.5-flash',
                contents=[prompt, combined_text],
                config=config
            )

            if response.parsed and response.parsed.candidates:
                for extracted_cand in response.parsed.candidates:
                    # Exclude the new source_file field when dumping into the internal schema
                    candidate = ExtractedCandidate(**extracted_cand.model_dump(exclude={'source_file'}))
                    src_name = extracted_cand.source_file if extracted_cand.source_file else "Unknown_Note"
                    records.append(SourceRecord(
                        source_name=src_name,
                        method=self.method,
                        data=candidate
                    ))
        except Exception as e:
            logger.error(f"Failed to extract Notes via Gemini: {e}")

        return records

class GitHubLoader:
    """
    Fetches public GitHub profile data.
    Gracefully degrades if the API is rate-limited or fails.
    """
    def __init__(self, username: str):
        self.username = username
        self.source_name = "GitHub_API"
        self.method = "api_fetch"
        
    def load(self) -> List[SourceRecord]:
        records = []
        try:
            url = f"https://api.github.com/users/{self.username}"
            headers = {"Accept": "application/vnd.github.v3+json"}
            
            # Optional: use GITHUB_TOKEN to avoid severe rate limiting
            token = os.environ.get("GITHUB_TOKEN")
            if token:
                headers["Authorization"] = f"token {token}"
                
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            name = data.get("name")
            email = data.get("email")
            location = data.get("location")
            bio = data.get("bio")
            blog = data.get("blog")
            
            candidate = ExtractedCandidate(
                full_name=name,
                emails=[email] if email else [],
                city=location, 
                headline=bio,
                portfolio=blog,
                github=data.get("html_url")
            )
            
            records.append(SourceRecord(
                source_name=self.source_name,
                method=self.method,
                data=candidate
            ))
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch GitHub profile for {self.username}. Gracefully degrading. Error: {e}")
            
        return records
