import re
from typing import Optional
import phonenumbers
from dateutil import parser
import pycountry

def normalize_phone(phone_str: Optional[str]) -> Optional[str]:
    """Normalizes a phone number to E.164 format."""
    if not phone_str:
        return None
    try:
        # Default to "IN" parsing if country code isn't explicitly provided with a '+'
        parsed = phonenumbers.parse(phone_str, "IN")
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    
    # Fallback to the raw string if parsing fails, but strip it cleanly
    return phone_str.strip()


def normalize_date(date_str: Optional[str]) -> Optional[str]:
    """Normalizes date strings to YYYY-MM."""
    if not date_str:
        return None
    
    date_str = str(date_str).strip()
    
    # Handle simple cases like just a year "2020" or "Present"
    if len(date_str) == 4 and date_str.isdigit():
        return date_str
    if date_str.lower() in ("present", "now", "current"):
        return "Present"
        
    try:
        parsed = parser.parse(date_str)
        return parsed.strftime("%Y-%m")
    except (ValueError, OverflowError):
        pass
        
    return date_str


def canonicalize_skill(skill: Optional[str]) -> Optional[str]:
    """Canonicalizes a skill name (lowercase, strip special chars)."""
    if not skill:
        return None
    s = str(skill).lower()
    # Replace non-alphanumeric (except + and #) with space
    s = re.sub(r'[^a-z0-9+#\s]', ' ', s)
    # Collapse multiple spaces
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def normalize_country(country_str: Optional[str]) -> Optional[str]:
    """Normalizes country names to ISO-3166 alpha-2 codes (e.g. United States -> US)."""
    if not country_str:
        return None
    try:
        # search_fuzzy handles variations like "United States of America", "USA", etc.
        matches = pycountry.countries.search_fuzzy(country_str)
        if matches:
            return matches[0].alpha_2
    except LookupError:
        pass
        
    return str(country_str).strip()
