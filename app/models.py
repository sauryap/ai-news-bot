"""Plain dataclasses describing the shapes moving through the pipeline."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Article:
    id: Optional[int]
    title: str
    url: str
    source: str
    author: Optional[str]
    published_at: Optional[str]  # ISO 8601 string, may be None
    description: Optional[str]
    category: str
    content_hash: str
    created_at: Optional[str] = None
    processed: int = 0


@dataclass
class Story:
    id: Optional[int]
    title: str
    summary: str
    why_it_matters: str
    importance: int
    category: str
    created_at: Optional[str] = None
    source_urls: List[str] = field(default_factory=list)
