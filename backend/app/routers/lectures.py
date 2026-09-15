"""Completed-class transcript review; no browser-claimed recording or speech inference."""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.access import course_access, tenant
from app.core.deps import get_current_user
from app.database import get_db
from app.models.ai import AIAuditLog, AIKnowledgeSource, AILectureContent
from app.models.attendance import ClassSession
from app.models.user import User, UserRole
from app.native_ai.lecture_digest import build_digest
from app.schemas.lecture import LectureContentOut, LecturePublicationIn, LectureReviewIn, LectureTranscriptIn

router = APIRouter(prefix="/ai/lectures", tags=["native-ai-lectures"])


def _lecture_out(item: AILectureContent, manager: bool) -> LectureContentOut:
    summary = dict(item.summary)
    if not manager:
        summary.pop("candidate_notes", None)
        summary.pop("candidate_topics", None)
        summary.pop("reviewed_by", None)
    return LectureContentOut(id=item.id, course_id=item.course_id, session_id=item.session_id,
                             status=item.status, transcript_source=item.transcript_source,
                             summary=summary, transcript=item.transcript if manager else None,
                             created_at=item.created_at, updated_at=item.updated_at)


def _manager(db: Session, user: User, course_id: int):
    if user.role not in (UserRole.faculty, UserRole.admin):
        raise HTTPException(403, "Only course faculty or administrators can review lecture transcripts")
    return course_access(db, user, course_id, manage=True)


def _audit(db: Session, user: User, event: str, item: AILectureContent):
    db.add(AIAuditLog(institution_id=tenant(user), user_id=user.id, event_type=event,
                      details={"lecture_id": item.id, "course_id": item.course_id,
                               "session_id": item.session_id, "status": item.status}))


@router.post("/sessions/{session_id}/transcript", response_model=LectureContentOut, status_code=201)
def submit_transcript(session_id: int, payload: LectureTranscriptIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    session = db.get(ClassSession, session_id)
    if not session:
        raise HTTPException(404, "Class session not found")
    course = _manager(db, user, session.course_id)
    if session.ended_at is None:
        raise HTTPException(409, "End the class before preparing lecture notes")
    if re.search(r"\b(password|private key|api[_ -]?token|secret key)\b", payload.transcript, re.I):
        raise HTTPException(422, "Remove passwords, private keys and API tokens from the transcript")
    try:
        digest = build_digest(payload.transcript)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    item = db.query(AILectureContent).filter(AILectureContent.session_id == session_id,
                                             AILectureContent.institution_id == tenant(user)).first()
    if item and item.status == "published":
        raise HTTPException(409, "Unpublish the current lecture notes before replacing the transcript")
    if item:
        item.transcript = payload.transcript
        item.summary = digest
        item.status = "draft"
    else:
        item = AILectureContent(institution_id=tenant(user), course_id=course.id,
                                session_id=session.id, submitted_by=user.id,
                                transcript=payload.transcript, transcript_source="faculty_text",
                                summary=digest, status="draft")
        db.add(item)
    db.flush()
    _audit(db, user, "lecture_transcript_digest_prepared", item)
    db.commit(); db.refresh(item)
    return _lecture_out(item, True)


@router.get("/course/{course_id}", response_model=list[LectureContentOut])
def list_lectures(course_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    course = course_access(db, user, course_id)
    manager = user.role == UserRole.admin or (user.role == UserRole.faculty and course.faculty_id == user.id)
    query = db.query(AILectureContent).filter(AILectureContent.institution_id == tenant(user),
                                               AILectureContent.course_id == course_id)
    if not manager:
        query = query.filter(AILectureContent.status == "published")
    return [_lecture_out(item, manager) for item in query.order_by(AILectureContent.id.desc()).limit(100).all()]


@router.patch("/{lecture_id}/review", response_model=LectureContentOut)
def review_lecture(lecture_id: int, payload: LectureReviewIn,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(AILectureContent).filter(AILectureContent.id == lecture_id,
                                              AILectureContent.institution_id == tenant(user)).first()
    if not item:
        raise HTTPException(404, "Lecture notes not found")
    _manager(db, user, item.course_id)
    if item.status == "published":
        raise HTTPException(409, "Unpublish the lecture notes before changing the review")
    candidate_notes = item.summary.get("candidate_notes") or item.summary.get("notes") or []
    candidate_topics = item.summary.get("candidate_topics") or item.summary.get("topics") or []
    allowed = {note["statement_number"] for note in candidate_notes}
    requested = payload.included_statement_numbers
    if len(set(requested)) != len(requested) or not set(requested) <= allowed:
        raise HTTPException(422, "Select distinct statements from this transcript draft")
    if len(set(payload.included_topics)) != len(payload.included_topics) or not set(payload.included_topics) <= set(candidate_topics):
        raise HTTPException(422, "Select distinct topics from this transcript draft")
    notes = [note for note in candidate_notes if note["statement_number"] in requested]
    summary = dict(item.summary)
    summary.update({"notes": notes, "topics": [topic for topic in candidate_topics if topic in payload.included_topics],
                    "summary": " ".join(note["text"] for note in notes),
                    "candidate_notes": candidate_notes, "candidate_topics": candidate_topics,
                    "review_required": False, "reviewed_by": user.id})
    item.summary = summary
    item.status = "reviewed"
    _audit(db, user, "lecture_digest_reviewed", item)
    db.commit(); db.refresh(item)
    return _lecture_out(item, True)


@router.patch("/{lecture_id}/publication", response_model=LectureContentOut)
def change_publication(lecture_id: int, payload: LecturePublicationIn,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(AILectureContent).filter(AILectureContent.id == lecture_id,
                                              AILectureContent.institution_id == tenant(user)).first()
    if not item:
        raise HTTPException(404, "Lecture notes not found")
    _manager(db, user, item.course_id)
    if payload.publish:
        if item.status not in ("reviewed", "published") or item.summary.get("review_required", True):
            raise HTTPException(409, "Review and select transcript statements before publishing")
        if not item.summary.get("notes"):
            raise HTTPException(409, "This transcript has no reviewable notes")
        if item.knowledge_source_id:
            source = db.query(AIKnowledgeSource).filter(AIKnowledgeSource.id == item.knowledge_source_id,
                                                       AIKnowledgeSource.institution_id == tenant(user)).first()
        else:
            source = None
        if source is None:
            source = AIKnowledgeSource(institution_id=tenant(user), course_id=item.course_id,
                                       created_by=user.id, title=f"Lecture {item.session_id} reviewed notes",
                                       source_type="lecture", content="\n".join(
                                           row["text"] for row in item.summary["notes"]), is_published=True)
            db.add(source); db.flush()
            item.knowledge_source_id = source.id
        else:
            source.content = "\n".join(row["text"] for row in item.summary["notes"])
            source.is_published = True
            source.archived_at = None
        item.status = "published"
    else:
        item.status = "reviewed" if not item.summary.get("review_required", True) else "draft"
        if item.knowledge_source_id:
            source = db.query(AIKnowledgeSource).filter(AIKnowledgeSource.id == item.knowledge_source_id,
                                                       AIKnowledgeSource.institution_id == tenant(user)).first()
            if source:
                source.is_published = False
    _audit(db, user, "lecture_digest_published" if payload.publish else "lecture_digest_unpublished", item)
    db.commit(); db.refresh(item)
    return _lecture_out(item, True)
