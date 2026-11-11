"""P8 read-only extension; base P7 API/source remains unchanged."""
import json
import re
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .rebuild_api import create_app as create_matching_app


ROOT=Path(__file__).resolve().parents[2]
MAX_ASSISTANT_BYTES=32768


def create_app(*,service=None,assistant=None,token=None,output=None,selection_manifest=None,
               frontend_dir=None,allow_origins=None):
    output=Path(output or ROOT/'data_rebuild/v1')
    app=create_matching_app(service=service,token=token,output=output,selection_manifest=selection_manifest,
                            frontend_dir=frontend_dir,allow_origins=allow_origins)
    app.state.rebuild_assistant=assistant
    assistant_lock=threading.Lock()
    authorize=app.state.rebuild_authorize
    get_service=app.state.rebuild_get_service

    def get_assistant(active=Depends(get_service)):
        if app.state.rebuild_assistant is None:
            with assistant_lock:
                if app.state.rebuild_assistant is None:
                    try:
                        from src.serving.rebuild_assistant import AdvisorAssistant
                        app.state.rebuild_assistant=AdvisorAssistant.from_artifacts(output,active)
                    except Exception:
                        raise HTTPException(503,detail='verified_advisor_knowledge_not_ready') from None
        return app.state.rebuild_assistant

    router=APIRouter()

    @router.get('/api/rebuild/bootstrap')
    def bootstrap(active=Depends(get_service)):
        result=active.bootstrap()
        try:
            get_assistant(active)
            result.update(assistant_ready=True,assistant_mode='deterministic_read_only')
        except HTTPException:
            result.update(assistant_ready=False,assistant_mode='unavailable')
        return result

    @router.post('/api/rebuild/assistant')
    async def answer(request:Request,scope=Depends(authorize),active=Depends(get_service)):
        try:
            declared=int(request.headers.get('content-length','0'))
        except ValueError:
            raise HTTPException(400,detail='invalid_content_length') from None
        if declared<0 or declared>MAX_ASSISTANT_BYTES:
            raise HTTPException(413,detail='assistant_request_size_limit')
        parts=[];length=0
        async for chunk in request.stream():
            length+=len(chunk)
            if length>MAX_ASSISTANT_BYTES:
                raise HTTPException(413,detail='assistant_request_size_limit')
            parts.append(chunk)
        try:
            payload=json.loads(b''.join(parts).decode('utf-8'))
        except (ValueError,UnicodeError):
            raise HTTPException(400,detail='invalid_json') from None
        if not isinstance(payload,dict) or set(payload)-{'question','cohort_id','advisor_ids','top_k'}:
            raise HTTPException(400,detail='invalid_assistant_request')
        question=payload.get('question');top_k=payload.get('top_k',5);ids=payload.get('advisor_ids')
        cohort_id=payload.get('cohort_id')
        if (not isinstance(question,str) or not question.strip() or len(question)>4000
                or type(top_k) is not int or not 1<=top_k<=10
                or ids is not None and (not isinstance(ids,list) or any(not isinstance(x,str) or x not in active.advisor_ids for x in ids))
                or cohort_id is not None and (not isinstance(cohort_id,str) or re.fullmatch('[0-9a-f]{64}',cohort_id) is None)):
            raise HTTPException(400,detail='invalid_assistant_request')
        if cohort_id is not None:
            active.get_students(cohort_id,scope=scope)
        knowledge=get_assistant(active)
        result=await run_in_threadpool(knowledge.answer,question,advisor_ids=ids or None,
                                      top_k=top_k,cohort_id=cohort_id,scope=scope)
        profile_scope = ('retrospective_public_sources' if active.versions.get('checkpoint_catalog')
                         else 'all_approved_public_profiles')
        return {**result,'advisor_selection_scope':('explicit_selected_profiles' if ids else profile_scope)}

    # Exact new routes must precede the existing catch-all StaticFiles mount.
    # Bootstrap adds a capability flag; every other P7 endpoint is retained.
    base_routes=list(app.router.routes)
    app.include_router(router)
    added=app.router.routes[len(base_routes):]
    app.router.routes[:]=added+base_routes
    return app


app=create_app()
