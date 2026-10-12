class AdapterError(Exception):
    pass

class AdapterCapabilityError(AdapterError):
    pass

class AdapterResolutionError(AdapterError):
    pass

class LiveExecutionUnavailableError(AdapterError):
    pass

class InvalidParameterError(AdapterError):
    pass

class ArbitraryCommandError(AdapterError):
    pass
