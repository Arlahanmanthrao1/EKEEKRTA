"""Permanent, transaction-scoped removal of one institution tenant.

The platform API calls this only after an operator has restricted the tenant
and completed an exact-name confirmation.  Keep the dependency order explicit:
production databases pre-date ON DELETE CASCADE and must fail closed if a new
tenant-owned table is added without being considered here.
"""
from pathlib import Path
import logging
import shutil

from sqlalchemy.orm import Session

from app.core.recording_storage import prepared_media_path, recording_path, recording_root
from app.models.ai import (
    AIAction,
    AIAuditLog,
    AICGPAGoal,
    AIKnowledgeSource,
    AILectureContent,
    AILecturePreparationJob,
    AILectureRecording,
    AITrainingExample,
)
from app.models.assignment import Assignment, Submission
from app.models.attendance import Attendance, ClassSession
from app.models.course import Course, Enrollment
from app.models.data_exchange import DataExchangeProfile
from app.models.erp import ERPIntegration, ERPSyncEvent
from app.models.google_drive import GoogleDriveConnection, GoogleDriveOAuthState
from app.models.google_identity import GoogleIdentity
from app.models.institution import Department, Institution
from app.models.material import StudyMaterial
from app.models.password_reset import PasswordResetToken
from app.models.platform import PlatformAuditLog
from app.models.programming import ProgrammingAssessment, ProgrammingSubmission, ProgrammingTestCase
from app.models.quiz import Question, Quiz, QuizAttempt
from app.models.scheduled_class import ScheduledClass
from app.models.training import (TrainingBatch, TrainingBatchEnrollment, TrainingCertificate,
                                 TrainingLesson, TrainingLessonCompletion, TrainingModule)
from app.models.user import User

logger = logging.getLogger(__name__)


def delete_institution_records(db: Session, institution: Institution) -> dict:
    """Remove all rows owned by ``institution`` without committing the session."""
    institution_id = institution.id
    user_ids = [value for (value,) in db.query(User.id).filter(User.institution_id == institution_id).all()]
    course_ids = [value for (value,) in db.query(Course.id).filter(Course.institution_id == institution_id).all()]
    batch_ids = [value for (value,) in db.query(TrainingBatch.id).filter(
        TrainingBatch.institution_id == institution_id).all()]
    module_ids = [value for (value,) in db.query(TrainingModule.id).filter(
        TrainingModule.batch_id.in_(batch_ids)).all()] if batch_ids else []
    lesson_ids = [value for (value,) in db.query(TrainingLesson.id).filter(
        TrainingLesson.module_id.in_(module_ids)).all()] if module_ids else []
    session_ids = [value for (value,) in db.query(ClassSession.id).filter(ClassSession.course_id.in_(course_ids)).all()] if course_ids else []
    assignment_ids = [value for (value,) in db.query(Assignment.id).filter(Assignment.course_id.in_(course_ids)).all()] if course_ids else []
    quiz_ids = [value for (value,) in db.query(Quiz.id).filter(Quiz.course_id.in_(course_ids)).all()] if course_ids else []
    assessment_ids = [value for (value,) in db.query(ProgrammingAssessment.id).filter(ProgrammingAssessment.course_id.in_(course_ids)).all()] if course_ids else []
    recording_rows = db.query(AILectureRecording.id, AILectureRecording.storage_key).filter(
        AILectureRecording.institution_id == institution_id
    ).all()
    recording_ids = [row.id for row in recording_rows]

    # Preserve the immutable platform history without retaining a foreign key to
    # the tenant. The deletion event added by the caller contains its snapshot.
    db.query(PlatformAuditLog).filter(PlatformAuditLog.institution_id == institution_id).update(
        {PlatformAuditLog.institution_id: None}, synchronize_session=False
    )

    db.query(AIAuditLog).filter(AIAuditLog.institution_id == institution_id).delete(synchronize_session=False)
    if recording_ids:
        db.query(AILecturePreparationJob).filter(
            AILecturePreparationJob.recording_id.in_(recording_ids)
        ).delete(synchronize_session=False)
    db.query(AILectureContent).filter(AILectureContent.institution_id == institution_id).delete(synchronize_session=False)
    db.query(AILectureRecording).filter(AILectureRecording.institution_id == institution_id).delete(synchronize_session=False)
    db.query(AIKnowledgeSource).filter(AIKnowledgeSource.institution_id == institution_id).delete(synchronize_session=False)
    db.query(AICGPAGoal).filter(AICGPAGoal.institution_id == institution_id).delete(synchronize_session=False)
    db.query(AITrainingExample).filter(AITrainingExample.institution_id == institution_id).delete(synchronize_session=False)
    db.query(AIAction).filter(AIAction.institution_id == institution_id).delete(synchronize_session=False)

    db.query(GoogleDriveOAuthState).filter(GoogleDriveOAuthState.institution_id == institution_id).delete(synchronize_session=False)
    db.query(GoogleDriveConnection).filter(GoogleDriveConnection.institution_id == institution_id).delete(synchronize_session=False)
    db.query(ERPSyncEvent).filter(ERPSyncEvent.institution_id == institution_id).delete(synchronize_session=False)
    db.query(ERPIntegration).filter(ERPIntegration.institution_id == institution_id).delete(synchronize_session=False)
    db.query(DataExchangeProfile).filter(
        DataExchangeProfile.institution_id == institution_id).delete(synchronize_session=False)

    if batch_ids:
        db.query(TrainingCertificate).filter(TrainingCertificate.batch_id.in_(batch_ids)).delete(synchronize_session=False)
        db.query(TrainingBatchEnrollment).filter(TrainingBatchEnrollment.batch_id.in_(batch_ids)).delete(synchronize_session=False)
    if lesson_ids:
        db.query(TrainingLessonCompletion).filter(
            TrainingLessonCompletion.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)
        db.query(TrainingLesson).filter(TrainingLesson.id.in_(lesson_ids)).delete(synchronize_session=False)
    if module_ids:
        db.query(TrainingModule).filter(TrainingModule.id.in_(module_ids)).delete(synchronize_session=False)

    if user_ids:
        # These filters also clean up any historically inconsistent row that
        # points at a tenant user but not at one of the tenant's own courses.
        db.query(Attendance).filter(Attendance.student_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(Submission).filter(Submission.student_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(QuizAttempt).filter(QuizAttempt.student_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(ProgrammingSubmission).filter(
            ProgrammingSubmission.student_id.in_(user_ids)
        ).delete(synchronize_session=False)
        db.query(Enrollment).filter(Enrollment.student_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(StudyMaterial).filter(StudyMaterial.uploaded_by.in_(user_ids)).delete(synchronize_session=False)
    if session_ids:
        db.query(Attendance).filter(Attendance.session_id.in_(session_ids)).delete(synchronize_session=False)
        db.query(ScheduledClass).filter(ScheduledClass.session_id.in_(session_ids)).delete(synchronize_session=False)
    if assignment_ids:
        db.query(Submission).filter(Submission.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
    if quiz_ids:
        db.query(Question).filter(Question.quiz_id.in_(quiz_ids)).delete(synchronize_session=False)
        db.query(QuizAttempt).filter(QuizAttempt.quiz_id.in_(quiz_ids)).delete(synchronize_session=False)
    if assessment_ids:
        db.query(ProgrammingSubmission).filter(
            ProgrammingSubmission.assessment_id.in_(assessment_ids)
        ).delete(synchronize_session=False)
        db.query(ProgrammingTestCase).filter(
            ProgrammingTestCase.assessment_id.in_(assessment_ids)
        ).delete(synchronize_session=False)
    if course_ids:
        db.query(Enrollment).filter(Enrollment.course_id.in_(course_ids)).delete(synchronize_session=False)
        db.query(StudyMaterial).filter(StudyMaterial.course_id.in_(course_ids)).delete(synchronize_session=False)
        db.query(ScheduledClass).filter(ScheduledClass.course_id.in_(course_ids)).delete(synchronize_session=False)
        db.query(Assignment).filter(Assignment.course_id.in_(course_ids)).delete(synchronize_session=False)
        db.query(Quiz).filter(Quiz.course_id.in_(course_ids)).delete(synchronize_session=False)
        db.query(ProgrammingAssessment).filter(
            ProgrammingAssessment.course_id.in_(course_ids)
        ).delete(synchronize_session=False)
        db.query(ClassSession).filter(ClassSession.course_id.in_(course_ids)).delete(synchronize_session=False)
        if batch_ids:
            db.query(TrainingBatch).filter(TrainingBatch.id.in_(batch_ids)).delete(synchronize_session=False)
        db.query(Course).filter(Course.id.in_(course_ids)).delete(synchronize_session=False)

    if user_ids:
        db.query(GoogleIdentity).filter(GoogleIdentity.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(PasswordResetToken).filter(PasswordResetToken.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    db.query(Department).filter(Department.institution_id == institution_id).delete(synchronize_session=False)
    db.delete(institution)

    return {
        "user_count": len(user_ids),
        "course_count": len(course_ids),
        "recording_keys": [row.storage_key for row in recording_rows],
    }


def remove_private_recording_files(storage_keys: list[str]) -> None:
    """Best-effort removal after the database transaction has committed."""
    if not storage_keys:
        return
    try:
        root = recording_root()
    except ValueError:
        logger.warning("Private recording cleanup skipped because storage is not safely configured")
        return
    for storage_key in storage_keys:
        try:
            raw: Path = recording_path(root, storage_key)
            prepared: Path = prepared_media_path(root, storage_key)
            raw.unlink(missing_ok=True)
            if prepared.exists():
                shutil.rmtree(prepared)
        except (OSError, ValueError):
            logger.exception("Could not remove private recording data for deleted institution")
