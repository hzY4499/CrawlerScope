from .access import AccessDecision, AccessHint, AccessPolicy, InstitutionAccessProfile
from .doi import DOIInputItem, DOIResolutionResult
from .download import DownloadResult
from .failure import FailureRecord
from .metadata import MetadataSourceResult
from .paper import PaperRecord
from .quality import QualityReport, QualityRequirements
from .task_spec import TaskSpec, TaskType

__all__ = [
    "AccessDecision",
    "AccessHint",
    "AccessPolicy",
    "DOIInputItem",
    "DOIResolutionResult",
    "DownloadResult",
    "FailureRecord",
    "InstitutionAccessProfile",
    "MetadataSourceResult",
    "PaperRecord",
    "QualityReport",
    "QualityRequirements",
    "TaskSpec",
    "TaskType",
]
