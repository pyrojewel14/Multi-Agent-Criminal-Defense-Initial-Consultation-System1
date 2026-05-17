from typing import List

from fastapi.routing import APIRouter
from fastapi import UploadFile, File, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.v1.router.knowledge_service import KnowledgeService, get_knowledge_service

from app.schemas.models import MD5Record, MD5ListResponse, KnowledgeListResponse, KnowledgeDocumentDetail, DocumentChunksResponse
from app.security.auth import require_session
from app.core.success_response import success_response
from app.core.rate_limit import rate_limit


knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@knowledge_router.post("/add/single")
async def add_vector_single(
        file: UploadFile = File(...),
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service),
        _: None = Depends(rate_limit(limit=5, window=60))
):
    """上传文件，将文件保存到向量数据库，仅支持 TXT 和 PDF。"""
    filename = await knowledge_service.handle_add_vector_single(file, session_id)
    return success_response(message=f"文件 {filename} 已成功上传并存储到向量数据库")


@knowledge_router.post("/add/multiple")
async def add_vector_multiple(
        files: List[UploadFile] = File(..., description="要上传的文件列表，仅支持 PDF 和 TXT 格式"),
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service),
        _: None = Depends(rate_limit(limit=3, window=60))
):
    """上传多个文件，将文件保存到向量数据库，仅支持 TXT 和 PDF。"""
    filenames = await knowledge_service.handle_add_vector_multiple(files, session_id)
    return success_response(message=f"文件 {filenames} 已成功上传并存储到向量数据库")


@knowledge_router.post("/add/multiple/stream")
async def add_vector_multiple_stream(
        files: List[UploadFile] = File(..., description="要上传的文件列表，仅支持 PDF、TXT、MD、PPTX、DOCX 格式"),
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service),
        _: None = Depends(rate_limit(limit=3, window=60))
):
    """上传多个文件，流式返回处理进度，仅支持 TXT、PDF、MD、PPTX、DOCX。"""
    return StreamingResponse(
        knowledge_service.handle_add_vector_multiple_stream(files, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*"
        }
    )


@knowledge_router.delete("/clean")
async def clean_user_vectors(session_id: str = Depends(require_session), knowledge_service: KnowledgeService = Depends(get_knowledge_service)):
    """删除用户上传的所有向量。"""
    await knowledge_service.clean_user_upload(session_id)
    return success_response(message="已成功删除用户上传的所有向量")


@knowledge_router.delete("/md5/clear")
async def clear_user_md5(
        delete_documents: bool = True,
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """清空用户的 MD5 记录。

    Args:
        delete_documents: 是否同时删除知识库文档（默认 True）。
    """
    await knowledge_service.handle_clear_user_md5(session_id, delete_documents)
    if delete_documents:
        return success_response(message="已成功清空用户的 MD5 记录和知识库文档")
    else:
        return success_response(message="已成功清空用户的 MD5 记录（保留知识库文档）")


@knowledge_router.delete("/md5/delete/{md5_value}")
async def delete_single_md5(
        md5_value: str,
        delete_documents: bool = True,
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """删除单个 MD5 记录及其对应的知识库内容。

    Args:
        md5_value: 要删除的 MD5 值。
        delete_documents: 是否同时删除知识库文档（默认 True）。
    """
    success = await knowledge_service.handle_delete_single_md5(session_id, md5_value, delete_documents)
    if success:
        if delete_documents:
            return success_response(message=f"已成功删除 MD5 记录 {md5_value} 及其对应的知识库文档")
        else:
            return success_response(message=f"已成功删除 MD5 记录 {md5_value}（保留知识库文档）")
    else:
        raise HTTPException(status_code=404, detail=f"MD5 记录 {md5_value} 不存在")


@knowledge_router.delete("/delete/filename")
async def delete_by_filename(
        filename: str,
        delete_documents: bool = True,
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service)
):
    """通过文件名删除 MD5 记录及其对应的知识库文档。

    Args:
        filename: 要删除的文件名。
        delete_documents: 是否同时删除知识库文档（默认 True）。
    """
    success = await knowledge_service.handle_delete_by_filename(session_id, filename, delete_documents)
    if success:
        if delete_documents:
            return success_response(message=f"已成功删除文件 {filename} 的 MD5 记录及其对应的知识库文档")
        else:
            return success_response(message=f"已成功删除文件 {filename} 的 MD5 记录（保留知识库文档）")
    else:
        raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")


@knowledge_router.get("/md5/list", response_model=MD5ListResponse)
async def get_all_md5_records(
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service),
        _: None = Depends(rate_limit(limit=10, window=60))
):
    """获取用户的所有 MD5 记录。"""
    records = await knowledge_service.handle_get_all_md5_records(session_id)
    return success_response(data=MD5ListResponse(
        records=records,
        total_count=len(records)
    ))


@knowledge_router.get("/md5/{md5_value}", response_model=MD5Record)
async def get_md5_info(
        md5_value: str,
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service),
        _: None = Depends(rate_limit(limit=10, window=60))
):
    """获取 MD5 对应的文档信息。

    Args:
        md5_value: MD5 值。
    """
    md5_info = await knowledge_service.handle_get_md5_info(session_id, md5_value)
    if md5_info:
        return success_response(data=md5_info)
    else:
        raise HTTPException(status_code=404, detail=f"MD5 记录 {md5_value} 不存在")


@knowledge_router.get("/list", response_model=KnowledgeListResponse)
async def get_user_knowledge_list(
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service),
        _: None = Depends(rate_limit(limit=10, window=60))
):
    """获取用户的知识库文档列表。"""
    documents = await knowledge_service.handle_get_user_knowledge(session_id)
    return success_response(data=KnowledgeListResponse(
        documents=documents,
        total_count=len(documents)
    ))


@knowledge_router.get("/detail", response_model=KnowledgeDocumentDetail)
async def get_document_detail(
        filename: str,
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service),
        _: None = Depends(rate_limit(limit=10, window=60))
):
    """获取文档详情内容。"""
    document = await knowledge_service.handle_get_document_detail(session_id, filename)
    return success_response(data=document)


@knowledge_router.get("/chunks", response_model=DocumentChunksResponse)
async def get_document_chunks(
        filename: str,
        session_id: str = Depends(require_session),
        knowledge_service: KnowledgeService = Depends(get_knowledge_service),
        _: None = Depends(rate_limit(limit=10, window=60))
):
    """获取文档切片信息。"""
    chunks = await knowledge_service.handle_get_document_chunks(session_id, filename)
    return success_response(data=chunks)
