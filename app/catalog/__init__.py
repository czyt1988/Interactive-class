"""Course catalog: manifest models, composition parser, resolver and loader.

The catalog is the platform's deep module. Build scripts use the resolver to
turn ``courses/<slug>/`` into a resolved manifest; the web process only reads
resolved manifests from ``dist/courses`` through the loader.
"""

from app.catalog.loader import CatalogLoader, load_catalog
from app.catalog.models import (
    Catalog,
    CatalogError,
    CourseSource,
    CourseSummary,
    ResolvedCourse,
    ResolvedScreen,
)
from app.catalog.resolver import resolve_course

__all__ = [
    "Catalog",
    "CatalogError",
    "CatalogLoader",
    "CourseSource",
    "CourseSummary",
    "ResolvedCourse",
    "ResolvedScreen",
    "load_catalog",
    "resolve_course",
]
