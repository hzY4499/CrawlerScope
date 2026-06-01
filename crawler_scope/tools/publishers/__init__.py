from .wiley_supplement_adapter import (
    SupplementDiscoveryError,
    build_wiley_article_url_from_doi,
    discover_wiley_supplements,
    download_supplement_file,
    has_wiley_access_challenge,
    parse_wiley_supplements_from_html,
)
from .wiley_browser_adapter import discover_wiley_supplements_with_browser_state

__all__ = [
    "SupplementDiscoveryError",
    "build_wiley_article_url_from_doi",
    "discover_wiley_supplements",
    "discover_wiley_supplements_with_browser_state",
    "download_supplement_file",
    "has_wiley_access_challenge",
    "parse_wiley_supplements_from_html",
]
