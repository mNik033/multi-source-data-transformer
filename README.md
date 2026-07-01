# Multi-Source Candidate Data Transformer

A data pipeline for processing, normalizing, and merging candidate profiles from unstructured notes, ATS JSON blobs, and recruiter CSV exports into unified, high-confidence profiles.

## Features and Architecture

* **LLM Extraction**: Uses Gemini Structured Outputs to parse unstructured recruiter notes and semi-structured ATS JSONs into typed Pydantic models. We handle missing fields gracefully without making up data.
* **Deterministic Entity Resolution**: We group records using an $O(N)$ Union-Find algorithm. Merging strictly relies on hard identifiers (emails, phone numbers, GitHub, LinkedIn). Name-only matches are deliberately ignored to avoid merging distinct people with the same name.
* **Context-Aware Normalization**: Standardizes dates to `YYYY-MM`, countries to ISO-3166, and maps skills to a canonical list. Phone number parsing uses the candidate's country metadata to prevent regional biases.
* **Provenance and Confidence**: Every data point in the canonical profile tracks its source and extraction method. Values from highly trusted sources (like ATS) win out over recruiter notes, and when multiple sources agree on a value, its confidence score gets a boost.
* **Flexible Runtime Projection**: The internal canonical profile can be reshaped into custom JSON schemas at runtime using a config file. It supports path traversal (e.g., `skills[].name` or `emails[0]`), dynamic normalizations on output fields, missing value policies (null, omit, or error), and toggling provenance/confidence metadata.

## Setup

1. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set your environment variables in a `.env` file:
   ```
   GEMINI_API_KEY=your_key_here
   ```

## Usage

Run the pipeline using the command line interface:

```bash
python src/cli.py \
  --csv samples/recruiter.csv \
  --ats samples/ats.json \
  --notes samples/notes \
  --config samples/config.json \
  --out output.json
```

To run the provided integration test dataset:

```bash
python src/cli.py \
  --csv tests/fixtures/real_world/recruiter.csv \
  --ats tests/fixtures/real_world/ats.json \
  --notes tests/fixtures/real_world/notes \
  --config tests/fixtures/real_world/config.json \
  --out test_output.json
```

## Projection Configuration Formats

The projection layer supports both the assignment-spec nested format and a simple flat list.

### 1. Specification Nested Format (Recommended)
This format dynamically configures schema mappings, type structures, missing-field behaviors, and dynamic metadata toggles:

```json
{
  "fields": [
    { "path": "full_name", "type": "string", "required": true },
    { "path": "primary_email", "from": "emails[0]", "type": "string", "required": true },
    { "path": "phone", "from": "phones[0]", "type": "string", "normalize": "E164" },
    { "path": "skills", "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null"
}
```

### 2. Flat List Format
This is a simpler layout mapping targeted output field names directly to canonical JSON paths:

```json
[
  {"field": "name", "path": "full_name", "type": "string"},
  {"field": "email", "path": "emails[0]", "type": "string", "on_missing": "omit"},
  {"field": "city", "path": "location.city", "type": "string", "on_missing": "null"}
]
```

## Testing

Verify loaders, normalizers, the Union-Find merger, and output projectors by running the test suite:

```bash
pytest tests/
```
