from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class AnalyzeRequest(BaseModel):
    source: str
    language: str = "cpp"

class AutocompleteRequest(BaseModel):
    prefix: str
    suffix: str = ""
    line: int = 1
    column: int = 1
    language: str = "cpp"
    symbols: Optional[List[Dict[str, Any]]] = None
    functions: Optional[List[str]] = None

class ExplainFixRequest(BaseModel):
    diagnostic: Dict[str, Any]
    code_context: str
    language: str = "cpp"

class FixAllRequest(BaseModel):
    source: str
    language: str = "cpp"

class ExampleItem(BaseModel):
    id: str
    title: str
    description: str
    language: str
    code: str
