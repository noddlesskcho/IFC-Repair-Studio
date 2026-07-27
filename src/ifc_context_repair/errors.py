class RepairError(Exception):
    """Base error with a safe user-facing message."""


class InputError(RepairError):
    pass


class ParseError(RepairError):
    pass


class OutputError(RepairError):
    pass


class DependencyError(RepairError):
    pass


class CancelledError(RepairError):
    pass


class UnsupportedSchemaError(InputError):
    pass


class ArchiveError(InputError):
    pass


class StepSyntaxError(ParseError):
    pass


class SemanticLoadError(ParseError):
    pass


class ResourceError(OutputError):
    pass


class RuleError(RepairError):
    pass


class PatchError(OutputError):
    pass


class VerificationError(OutputError):
    pass


class ReportError(OutputError):
    pass
