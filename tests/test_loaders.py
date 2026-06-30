import sys
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from loaders import AtsJsonLoader, NotesLoader
from models import SourceRecord

@patch('loaders.genai.Client')
def test_ats_json_loader_gemini_mock(mock_genai_client_class):
    """Verify that AtsJsonLoader correctly calls the Gemini API and parses the response schema."""
    os.environ["GEMINI_API_KEY"] = "fake-api-key"
    
    # Mock client and response structure
    mock_client = MagicMock()
    mock_genai_client_class.return_value = mock_client
    
    from loaders import AtsExtractionList, AtsCandidateExtraction, AtsExperienceExtraction
    
    mock_candidate = AtsCandidateExtraction(
        full_name="John Doe",
        emails=["john@test.com"],
        phones=["555-1234"],
        city="NYC",
        headline="Engineer",
        github="github.com/johndoe",
        experience=[
            AtsExperienceExtraction(
                company="Google", 
                title="SE", 
                start="2020-01", 
                end="Present", 
                summary="Worked hard"
            )
        ],
        education=[]
    )
    
    mock_parsed_response = AtsExtractionList(candidates=[mock_candidate])
    
    mock_response = MagicMock()
    mock_response.parsed = mock_parsed_response
    mock_client.models.generate_content.return_value = mock_response
    
    # Setup temporary ATS file
    with tempfile.NamedTemporaryFile(suffix=".json", mode='w', delete=False) as f:
        f.write('{"dummy": "data"}')
        temp_file_path = f.name
        
    try:
        loader = AtsJsonLoader(temp_file_path)
        assert loader.client is not None
        
        records = loader.load()
        
        # Verify Gemini generation API was called
        mock_client.models.generate_content.assert_called_once()
        
        # Verify the record matches our mocked payload
        assert len(records) == 1
        record = records[0]
        assert isinstance(record, SourceRecord)
        assert record.source_name == "ATS_JSON"
        assert record.data.full_name == "John Doe"
        assert record.data.emails == ["john@test.com"]
        assert record.data.experience[0].company == "Google"
    finally:
        os.remove(temp_file_path)


@patch('loaders.genai.Client')
def test_notes_loader_gemini_mock(mock_genai_client_class):
    """Verify that NotesLoader dynamically batches txt notes and parses them in a single Gemini call."""
    os.environ["GEMINI_API_KEY"] = "fake-api-key"
    
    mock_client = MagicMock()
    mock_genai_client_class.return_value = mock_client
    
    from loaders import AtsExtractionList, AtsCandidateExtraction
    
    mock_candidate = AtsCandidateExtraction(
        full_name="Jane Doe",
        emails=["jane@test.com"],
        phones=[],
        city="SF",
        experience=[],
        education=[],
        source_file="jane_notes.txt"
    )
    mock_parsed_response = AtsExtractionList(candidates=[mock_candidate])
    
    mock_response = MagicMock()
    mock_response.parsed = mock_parsed_response
    mock_client.models.generate_content.return_value = mock_response
    
    # Setup temporary notes folder with one text file
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file_path = os.path.join(temp_dir, "jane_notes.txt")
        with open(temp_file_path, "w") as f:
            f.write("Jane Doe is a great candidate located in SF.")
            
        loader = NotesLoader(temp_dir)
        records = loader.load()
        
        mock_client.models.generate_content.assert_called_once()
        
        assert len(records) == 1
        record = records[0]
        assert record.source_name == "jane_notes.txt"
        assert record.data.full_name == "Jane Doe"
        assert record.data.emails == ["jane@test.com"]
