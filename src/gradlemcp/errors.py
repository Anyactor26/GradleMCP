from pydantic import BaseModel, Field


class ServiceError(Exception):
    def __init__(self, code, message, status=400, remediation=None, retryable=False, details=None):
        self.status = status
        self.body = {
            "code": code,
            "message": message,
            "remediation": remediation,
            "retryable": retryable,
            "permanent": not retryable,
            "details": details or {},
        }
        super().__init__(message)


# Shared schema used by generated OpenAPI, including custom validation errors.


class ErrorBody(BaseModel):
    code: str
    message: str
    remediation: str | None = None
    retryable: bool = False
    permanent: bool = True
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
