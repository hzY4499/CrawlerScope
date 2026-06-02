from .access import AccessDecision, AccessHint, AccessPolicy, InstitutionAccessProfile
from .auth import BrowserSessionProfile, ManualHandoffRecord
from .doi import DOIInputItem, DOIResolutionResult
from .download import DownloadResult
from .failure import FailureRecord
from .local_corpus import LocalCorpusMatchResult, LocalCorpusSummary, LocalFileRecord
from .manual import ManualDownloadTask, ManualDownloadedFile, ManualScanSummary
from .metadata import MetadataSourceResult
from .parse import ParseResult
from .paper import PaperRecord
from .quality import QualityReport, QualityRequirements
from .requirement import RequirementSpec
from .report import FinalFailureRecord, FinalPaperRecord, RunReport
from .supplement import SupplementDownloadResult, SupplementRecord, SupplementSummary
from .task_spec import TaskSpec, TaskType

__all__ = [
    "AccessDecision",
    "AccessHint",
    "AccessPolicy",
    "BrowserSessionProfile",
    "DOIInputItem",
    "DOIResolutionResult",
    "DownloadResult",
    "FailureRecord",
    "InstitutionAccessProfile",
    "LocalCorpusMatchResult",
    "LocalCorpusSummary",
    "LocalFileRecord",
    "ManualDownloadedFile",
    "ManualDownloadTask",
    "ManualScanSummary",
    "ManualHandoffRecord",
    "MetadataSourceResult",
    "ParseResult",
    "PaperRecord",
    "QualityReport",
    "QualityRequirements",
    "RequirementSpec",
    "FinalPaperRecord",
    "FinalFailureRecord",
    "RunReport",
    "SupplementRecord",
    "SupplementDownloadResult",
    "SupplementSummary",
    "TaskSpec",
    "TaskType",
]
