from pydantic import BaseModel
from datetime import datetime
from typing import Optional

# Auth Schemas
class UserRegister(BaseModel):
    username: str
    email: str
    password: str
    device_id: Optional[str] = None  # auto-generated if omitted

class UserLogin(BaseModel):
    username: str
    password: str
    device_id: Optional[str] = None  # auto-generated if omitted

class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict

class TokenData(BaseModel):
    username: Optional[str] = None

# User Schemas
class UserBase(BaseModel):
    username: str
    email: str
    device_id: str

class UserResponse(UserBase):
    id: int
    is_superuser: bool
    is_active: bool
    plan: str = "free"
    daily_api_calls: int = 0
    trial_ends_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

# Permission Schemas
class PermissionResponse(BaseModel):
    can_run_copilot: bool
    can_run_commands: bool
    can_edit_files: bool
    can_view_files: bool

    class Config:
        from_attributes = True

# Access Request Schemas
class AccessRequestCreate(BaseModel):
    username: str
    email: str
    device_id: str
    request_type: str = "qr_code"

class AccessRequestResponse(BaseModel):
    id: int
    username: str
    request_type: str
    status: str
    qr_code_data: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# Tool Schemas
class ToolInput(BaseModel):
    filepath: Optional[str] = None
    content: Optional[str] = None
    oldText: Optional[str] = None
    newText: Optional[str] = None
    command: Optional[str] = None
    cwd: Optional[str] = None
    dirpath: Optional[str] = None
    query: Optional[str] = None
    line: Optional[int] = None

class ToolResult(BaseModel):
    success: bool
    tool: str
    result: Optional[str] = None
    error: Optional[str] = None


# Billing Schemas
class CheckoutRequest(BaseModel):
    plan: str  # pro | team | self_hosted_monthly | self_hosted_lifetime


class ValidateLicenseRequest(BaseModel):
    license_key: str


class BillingStatusResponse(BaseModel):
    plan: str
    plan_label: str
    daily_api_calls: int
    daily_limit: int   # -1 = unlimited
    trial_ends_at: Optional[datetime] = None
    has_stripe_customer: bool
    subscription_active: bool
