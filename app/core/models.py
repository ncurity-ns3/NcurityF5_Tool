from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr


class ExecutionMode(str, Enum):
    design = "design"
    collect = "collect"
    generate = "generate"
    preview = "preview"
    apply = "apply"


class OperationClass(str, Enum):
    ro = "RO"
    gen = "GEN"
    pre = "PRE"
    wr = "WR"
    dest = "DEST"


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class PlatformKind(str, Enum):
    """iSeries = TMOS MGMT only; rSeries = F5OS platform MGMT + optional TMOS tenant MGMT."""

    iseries = "iseries"
    rseries = "rseries"


class DeviceTarget(BaseModel):
    label: str
    platform: PlatformKind = PlatformKind.iseries
    host: str
    port: int = 443
    f5os_host: str = ""
    f5os_port: int = 443
    verify_tls: bool = False


class JobRecord(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    module: str
    mode: ExecutionMode
    status: JobStatus = JobStatus.pending
    operator: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    output_dir: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectionProfile(BaseModel):
    target: DeviceTarget
    username: str
    password: SecretStr
    f5os_username: str | None = None
    f5os_password: SecretStr | None = None

    model_config = {"json_schema_extra": {"writeOnly": True}}


class HealthCheckProfile(BaseModel):
    categories: list[str] = Field(
        default_factory=lambda: ["common"]
    )
    perform_ucs_backup: bool = Field(
        default=True,
        description="Trigger tmsh save sys ucs in background during common check.",
    )
    ucs_log_path: str | None = Field(
        default=None,
        description="Append UCS background job results to this file (per job).",
    )


class CollectionResult(BaseModel):
    device_label: str
    host: str
    collected_at: datetime
    data: dict[str, Any]
    errors: list[str] = Field(default_factory=list)


class ReportContext(BaseModel):
    job_id: str
    site_name: str = "lab-site"
    period: str = ""
    engineer_notes: str = ""
    devices: list[CollectionResult]
    exceptions: list[dict[str, Any]] = Field(default_factory=list)
