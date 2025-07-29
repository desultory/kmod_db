class UnknownKernelVersionError(Exception):
    """Raised when the kernel version is not known or not set."""

    pass


class UnknownAliasError(Exception):
    """Raised when a kernel module alias is not found."""

    pass
