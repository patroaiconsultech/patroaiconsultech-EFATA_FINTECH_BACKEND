from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.access import get_accessible_opportunity
from app.audit import record_audit
from app.db import get_db
from app.models import Document, new_id
from app.schemas import DocumentCreate, DocumentRead
from app.security import SecurityContext, require_security_context

router = APIRouter(prefix="/api/v1/opportunities", tags=["documents"])


@router.post("/{opportunity_id}/documents", response_model=DocumentRead, status_code=201)
def create_mock_document(
    opportunity_id: str,
    payload: DocumentCreate,
    request: Request,
    context: SecurityContext = Depends(require_security_context),
    db: Session = Depends(get_db),
) -> Document:
    opportunity = get_accessible_opportunity(
        db,
        opportunity_id=opportunity_id,
        tenant_id=context.tenant_id,
        required_permission="UPLOAD_DOCUMENTS",
    )
    document_id = new_id()
    document = Document(
        document_id=document_id,
        tenant_id=opportunity.tenant_id,
        opportunity_id=opportunity.opportunity_id,
        filename=payload.filename,
        document_type=payload.document_type,
        storage_key=f"mock://{opportunity.tenant_id}/{opportunity.opportunity_id}/{document_id}",
        checksum_sha256=payload.checksum_sha256.lower(),
        uploaded_by=context.user_id,
    )
    db.add(document)
    record_audit(
        db,
        context=context,
        action="DOCUMENT_MOCK_CREATED",
        resource_type="DOCUMENT",
        resource_id=document.document_id,
        request_id=request.state.request_id,
        correlation_id=request.state.correlation_id,
        tenant_id=opportunity.tenant_id,
    )
    db.commit()
    db.refresh(document)
    return document
