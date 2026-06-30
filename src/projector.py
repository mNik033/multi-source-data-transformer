import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import create_model, BaseModel, ValidationError

from models import CanonicalProfile
from normalizers import normalize_phone, canonicalize_skill

logger = logging.getLogger(__name__)

class ProjectionConfig(BaseModel):
    field: str
    path: str
    type: str
    normalize: Optional[str] = None
    on_missing: str = "null"  # "null", "omit", "error"

class Projector:
    """
    Dynamically projects CanonicalProfiles into arbitrary JSON schemas based on a configuration file.
    """
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.rules: List[ProjectionConfig] = []
        self._load_config()

    def _load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for item in data:
                    self.rules.append(ProjectionConfig(**item))
            self._compile_model()
        except Exception as e:
            logger.error(f"Failed to load projection config from {self.config_path}: {e}")
            raise

    def _compile_model(self):
        type_mapping = {
            "string": str,
            "int": int,
            "float": float,
            "boolean": bool,
            "list": list,
            "dict": dict
        }
        
        fields = {}
        for rule in self.rules:
            py_type = type_mapping.get(rule.type, Any)
            
            # If on_missing="null" or "omit", the field is allowed to be missing at initialization
            if rule.on_missing in ["null", "omit"]:
                py_type = Optional[py_type]
                fields[rule.field] = (py_type, None)
            else:
                fields[rule.field] = (py_type, ...)
                
        self.DynamicModel = create_model('DynamicProfile', **fields) # type: ignore

    def _resolve_path(self, profile: CanonicalProfile, path: str) -> Any:
        """
        Custom path parser. Supports:
        - dot notation: `location.city`
        - array indexing: `emails[0]`
        - array mapping: `skills[].name` (extracts 'name' from all items in 'skills')
        """
        current: Any = profile
        
        parts = path.split('.')
        for i, part in enumerate(parts):
            if current is None:
                return None
                
            if '[]' in part:
                # Array mapping: skills[].name
                list_field = part.replace('[]', '')
                items = getattr(current, list_field, [])
                
                # If this is the last part, just return the items list
                if i == len(parts) - 1:
                    return items
                    
                # Otherwise, map the next part over the items
                next_part = parts[i + 1]
                mapped = []
                for item in items:
                    val = getattr(item, next_part, None)
                    if val is not None:
                        mapped.append(val)
                return mapped
                
            elif '[' in part and ']' in part:
                # Array indexing: emails[0]
                list_field, index_str = part.split('[')
                index = int(index_str.replace(']', ''))
                items = getattr(current, list_field, [])
                if 0 <= index < len(items):
                    current = items[index]
                else:
                    return None
            else:
                # Standard attribute access (skipping next_part if we just mapped over it)
                if i > 0 and '[]' in parts[i - 1]:
                    continue # Handled by the array mapping block
                current = getattr(current, part, None)
                
        return current

    def project(self, profile: CanonicalProfile) -> Dict[str, Any]:
        """Projects a single profile into a dictionary based on the config."""
        output = {}
        
        for rule in self.rules:
            val = self._resolve_path(profile, rule.path)
            
            # 1. Apply Missing Policy
            if val is None or (isinstance(val, list) and len(val) == 0):
                if rule.on_missing == "error":
                    raise ValueError(f"Required field '{rule.path}' is missing in profile {profile.candidate_id}")
                elif rule.on_missing == "omit":
                    continue
                else:  # default "null"
                    output[rule.field] = None
                    continue
            
            # 2. Apply Dynamic Normalization at Projection Time
            if rule.normalize == "E164":
                if isinstance(val, list):
                    val = [normalize_phone(v) for v in val]
                else:
                    val = normalize_phone(val)
            elif rule.normalize == "canonical":
                if isinstance(val, list):
                    val = [canonicalize_skill(v) for v in val]
                else:
                    val = canonicalize_skill(val)
                    
            output[rule.field] = val
            
        try:
            validated = self.DynamicModel(**output)
            # exclude_unset=True ensures fields with "omit" policy (which are skipped and fallback to defaults) 
            # are completely dropped from the JSON, whereas explicitly set "null" fields are kept.
            return validated.model_dump(exclude_unset=True)
        except ValidationError as e:
            logger.error(f"Validation failed during projection for candidate {profile.candidate_id}: {e}")
            raise
