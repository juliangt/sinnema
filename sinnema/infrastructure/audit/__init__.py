"""Adaptadores de auditoría de ejecución (implementan AuditTrailPort)."""
from sinnema.infrastructure.audit.filesystem import FilesystemAuditTrail

__all__ = ["FilesystemAuditTrail"]
