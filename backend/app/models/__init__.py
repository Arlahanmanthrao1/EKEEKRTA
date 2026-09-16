from app.models.user import User, UserRole
from app.models.google_identity import GoogleIdentity
from app.models.password_reset import PasswordResetToken
from app.models.institution import Institution, Department
from app.models.course import Course, Enrollment
from app.models.attendance import ClassSession, Attendance
from app.models.scheduled_class import ScheduledClass
from app.models.assignment import Assignment, Submission
from app.models.quiz import Quiz, Question, QuizAttempt
from app.models.material import StudyMaterial, MaterialType
from app.models.programming import ProgrammingAssessment, ProgrammingTestCase, ProgrammingSubmission
from app.models.erp import ERPIntegration, ERPSyncEvent
from app.models.ai import (AIAction, AIAuditLog, AITrainingExample, AICGPAGoal,
                           AIKnowledgeSource, AILectureContent, AILectureRecording,
                           AILecturePreparationJob)
