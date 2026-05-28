from .access import AccessDecision, AccessPolicy, InstitutionAccessProfile
from .doi import DOIInputItem, DOIResolutionResult
from .download import DownloadResult
from .failure import FailureRecord
from .paper import PaperRecord
from .quality import QualityReport, QualityRequirements
from .task_spec import TaskSpec, TaskType

__all__ = [
    "AccessDecision",
    "AccessPolicy",
    "DOIInputItem",
    "DOIResolutionResult",
    "DownloadResult",
    "FailureRecord",
    "InstitutionAccessProfile",
    "PaperRecord",
    "QualityReport",
    "QualityRequirements",
    "TaskSpec",
    "TaskType",
]
