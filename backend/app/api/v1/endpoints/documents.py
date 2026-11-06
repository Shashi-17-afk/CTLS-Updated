from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from backend.app.core.config import settings
from backend.app.schemas.document import DocumentIngestResponse
from backend.app.schemas.error import ErrorResponse
from backend.app.services.ingestion.exceptions import (
    EmptyFileError,
    EncryptedDocumentError,
    ExcessivePagesError,
    FileTooLargeError,
    MalformedDocumentError,
    UnsupportedFormatError,
)
from backend.app.services.ingestion.service import DocumentIngestionService

router = APIRouter()


@router.post(
    "/ingest",
    response_model=DocumentIngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest Document & Extract Embedded Text",
    description=(
        "Upload a PDF, PNG, or JPEG document. The service validates binary file signatures, "
        "enforces size and page limits, and extracts usable embedded text from text-based PDFs. "
        "Scanned pages and images are tagged with OCR_REQUIRED."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Empty or zero-byte file"},
        413: {"model": ErrorResponse, "description": "File exceeds maximum size limit"},
        415: {"model": ErrorResponse, "description": "Unsupported document format or signature"},
        422: {"model": ErrorResponse, "description": "Malformed, encrypted, or excessive-page document"},
    },
)
async def ingest_document(
    file: UploadFile = File(..., description="Binary document file (PDF, PNG, JPEG)"),
    enable_ocr: bool = Query(
        default=True,
        description="Whether to run local OCR on scanned PDF pages and standalone images",
    ),
) -> DocumentIngestResponse:
    """Ingests, validates, and extracts text from an uploaded document."""
    # Defensively read file content with memory bound
    max_read_bytes = settings.MAX_FILE_SIZE_BYTES + 1024
    content = await file.read(max_read_bytes)

    if len(content) > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Uploaded file exceeds maximum limit of {settings.MAX_FILE_SIZE_BYTES} bytes.",
        )

    filename = file.filename or "unnamed_document"

    try:
        response = DocumentIngestionService.process_document(
            content=content,
            original_filename=filename,
            enable_ocr=enable_ocr,
        )
        return response

    except EmptyFileError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err.message,
        ) from err

    except UnsupportedFormatError as err:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=err.message,
        ) from err

    except FileTooLargeError as err:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=err.message,
        ) from err

    except (EncryptedDocumentError, ExcessivePagesError, MalformedDocumentError) as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=err.message,
        ) from err
