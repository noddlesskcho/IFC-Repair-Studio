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
