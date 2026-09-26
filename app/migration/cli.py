"""Operator CLI for package export, preflight, dry-run, import, and verification."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.application.identity import ServiceAccountIdentityService
from app.auth.errors import AuthenticationFailed
from app.authorization.service import AuthorizationDenied
from app.authorization.service import AuthorizationService
from app.config.settings import get_settings
from app.documents.s3 import (
    S3DocumentStorage,
    S3DocumentStorageConfig,
    create_s3_client,
)
from app.domain.identifiers import OrganizationId, WorkspaceId
from app.domain.usage import QuotaExceeded
from app.migration.package import (
    MigrationLimits,
    MigrationPackageError,
    export_v2_workspace,
    load_migration_package,
)
from app.migration.reporting import format_migration_report, write_migration_report
from app.migration.service import (
    MigrationConflictMode,
    MigrationImportError,
    MigrationService,
)
from app.observability.logging import configure_json_logging, log_event
from app.observability.metrics import CloudWatchEmfMetricSink, MigrationMetricObserver
from app.persistence.postgres.authorization import (
    PostgresAuthorizationFactsRepository,
    PostgresTenantResourceValidator,
)
from app.persistence.postgres.document_unit_of_work import PostgresDocumentUnitOfWork
from app.persistence.postgres.engine import create_postgres_engine, create_session_factory
from app.persistence.postgres.identity_unit_of_work import PostgresIdentityUnitOfWork
from app.persistence.postgres.usage import quota_defaults_from_settings

logger = logging.getLogger(__name__)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Build or apply a bounded AIRA V2-to-V3 migration package"
    )
    root.add_argument(
        "--mode",
        required=True,
        choices=("export", "preflight", "dry-run", "import", "verify"),
    )
    root.add_argument("--source", type=Path, required=True)
    root.add_argument("--organization-id")
    root.add_argument("--workspace-id")
    root.add_argument("--output", type=Path)
    root.add_argument("--source-identifier")
    root.add_argument("--source-build-sha")
    root.add_argument(
        "--conflict-mode",
        choices=tuple(mode.value for mode in MigrationConflictMode),
        default=MigrationConflictMode.SKIP_IDENTICAL.value,
    )
    root.add_argument("--confirm-import", action="store_true")
    root.add_argument("--max-files", type=int, default=2_000)
    root.add_argument("--max-file-bytes", type=int, default=5_242_880)
    root.add_argument("--max-total-bytes", type=int, default=524_288_000)
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    limits = MigrationLimits(
        max_files=args.max_files,
        max_file_bytes=args.max_file_bytes,
        max_total_bytes=args.max_total_bytes,
    )
    try:
        if args.mode == "export":
            if args.output is None:
                raise MigrationPackageError(
                    "invalid_record", "--output is required for export"
                )
            package = export_v2_workspace(
                args.source,
                args.output,
                source_identifier=args.source_identifier,
                source_build_sha=args.source_build_sha,
                limits=limits,
            )
            print(
                json.dumps(
                    {
                        "manifest_hash": package.manifest_hash,
                        "records": len(package.manifest.records),
                        "documents": len(package.documents),
                        "output": str(package.root),
                    },
                    sort_keys=True,
                )
            )
            return
        _require_destination(args)
        if args.output is None:
            raise MigrationPackageError(
                "invalid_record", "--output report path is required"
            )
        if args.mode == "import" and not args.confirm_import:
            raise MigrationPackageError(
                "invalid_record", "Import requires --confirm-import"
            )
        package = load_migration_package(args.source, limits=limits)
        service, actor, engine = _hosted_service()
        try:
            organization_id = OrganizationId(args.organization_id)
            workspace_id = WorkspaceId(args.workspace_id)
            conflict_mode = MigrationConflictMode(args.conflict_mode)
            operation = {
                "preflight": service.preflight,
                "dry-run": service.dry_run,
                "import": service.import_package,
                "verify": service.verify,
            }[args.mode]
            kwargs = (
                {"conflict_mode": conflict_mode}
                if args.mode in {"preflight", "dry-run", "import"}
                else {}
            )
            report = operation(
                package, actor, organization_id, workspace_id, **kwargs
            )
            write_migration_report(args.output, report)
            log_event(
                logger,
                logging.INFO,
                "migration.completed",
                "Migration operation completed",
                migration_id=report.migration_id,
                source_version=package.manifest.source_version,
                operation=report.mode,
                result="succeeded" if report.clean else "failed",
            )
            print(format_migration_report(report))
        finally:
            engine.dispose()
    except QuotaExceeded as exc:
        raise SystemExit("migration rejected [quota_exceeded]: destination quota exceeded") from exc
    except (AuthorizationDenied, AuthenticationFailed) as exc:
        raise SystemExit("migration rejected [authorization_failed]: authorization failed") from exc
    except SQLAlchemyError as exc:
        raise SystemExit("migration rejected [persistence_failure]: persistence failed") from exc
    except (MigrationPackageError, MigrationImportError, ValueError, OSError) as exc:
        category = getattr(exc, "category", "invalid_record")
        raise SystemExit(f"migration rejected [{category}]: {exc}") from exc


def _require_destination(args: argparse.Namespace) -> None:
    if not args.organization_id or not args.workspace_id:
        raise MigrationPackageError(
            "invalid_record", "--organization-id and --workspace-id are required"
        )


def _hosted_service():
    settings = get_settings()
    configure_json_logging(
        service="migration",
        environment=settings.aira_env,
        build_sha=settings.aira_build_sha,
    )
    required = {
        "AIRA_DATABASE_URL": settings.aira_database_url,
        "AIRA_DOCUMENT_BUCKET": settings.aira_document_bucket,
        "AIRA_KMS_KEY_ARN": settings.aira_kms_key_arn,
        "AIRA_MIGRATION_CREDENTIAL": os.environ.get("AIRA_MIGRATION_CREDENTIAL", ""),
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        raise MigrationPackageError(
            "authorization_failed",
            f"Required migration configuration is missing: {', '.join(missing)}",
        )
    engine = create_postgres_engine(settings.aira_database_url)
    sessions = create_session_factory(engine)
    actor = ServiceAccountIdentityService(
        lambda: PostgresIdentityUnitOfWork(sessions)
    ).authenticate(required["AIRA_MIGRATION_CREDENTIAL"])
    authorization = AuthorizationService(
        PostgresAuthorizationFactsRepository(sessions),
        PostgresTenantResourceValidator(sessions),
    )
    quota_defaults = quota_defaults_from_settings(settings)
    storage_config = S3DocumentStorageConfig(
        settings.aira_document_bucket,
        settings.aira_aws_region,
        settings.aira_kms_key_arn,
    )
    storage = S3DocumentStorage(create_s3_client(storage_config), storage_config)
    service = MigrationService(
        authorization,
        lambda context: PostgresDocumentUnitOfWork(
            sessions, context, quota_defaults
        ),
        storage,
        observer=MigrationMetricObserver(
            CloudWatchEmfMetricSink(
                settings.aira_metric_namespace, settings.aira_env, "migration"
            )
        ),
    )
    return service, actor, engine


if __name__ == "__main__":
    main()
