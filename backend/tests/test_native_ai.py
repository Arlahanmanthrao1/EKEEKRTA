"""Native AI tests use only disposable in-memory records and no external model/API."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token
from app.core.secret_box import encrypt_secret
from app.database import Base, get_db
from app.models import (Assignment, Attendance, ClassSession, Course, Enrollment, Question, Quiz, QuizAttempt,
                        ScheduledClass, Submission, User, UserRole)
from app.models.ai import (AIAction, AIAuditLog, AICGPAGoal, AIKnowledgeSource,
                           AILectureContent, AILecturePreparationJob,
                           AILectureRecording, AITrainingExample)
from app.models.erp import ERPIntegration
from app.models.institution import Department, Institution
from app.native_ai.intent_model import model
from app.native_ai.model_runtime import run_slide_ocr, run_speech_model
from app.native_ai.recording_ingest import ingest_jibri_recording
from app.native_ai.recording_retention import purge_expired_recordings
from app.native_ai.recording_worker import process_next_recording_job
from app.config import settings
from app.routers import ai, lectures


class NativeAITest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([Institution(id=1, name="Alpha", email_domain="alpha.edu"),
                         Institution(id=2, name="Beta", email_domain="beta.edu")])
        self.db.flush()
        self.db.add_all([Department(institution_id=1, name="CS"), Department(institution_id=2, name="CS")])
        self.db.flush()
        self.db.add_all([
            User(id=1, institution_id=1, name="Faculty One", email="f1@alpha.edu", role=UserRole.faculty,
                 department="CS", hashed_password="unused"),
            User(id=2, institution_id=1, name="Faculty Two", email="f2@alpha.edu", role=UserRole.faculty,
                 department="CS", hashed_password="unused"),
            User(id=3, institution_id=1, name="Student One", email="s1@alpha.edu", role=UserRole.student,
                 department="CS", hashed_password="unused"),
            User(id=4, institution_id=1, name="Admin One", email="admin@alpha.edu", role=UserRole.admin,
                 hashed_password="unused"),
            User(id=5, institution_id=2, name="Foreign Student", email="s@beta.edu", role=UserRole.student,
                 department="CS", hashed_password="unused"),
            User(id=6, institution_id=2, name="Foreign Admin", email="admin@beta.edu", role=UserRole.admin,
                 hashed_password="unused"),
        ])
        self.db.flush()
        self.db.add_all([
            Course(id=1, institution_id=1, name="Cloud Computing", code="CS401", department="CS", faculty_id=1),
            Course(id=2, institution_id=1, name="Machine Learning", code="CS405", department="CS", faculty_id=2),
            Course(id=3, institution_id=2, name="Foreign Course", code="BE101", department="CS", faculty_id=None),
        ])
        self.db.flush()
        self.db.add(Enrollment(course_id=1, student_id=3))
        self.db.commit()
        app = FastAPI(); app.include_router(ai.router); app.include_router(lectures.router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.engine.dispose); self.addCleanup(self.db.close); self.addCleanup(self.client.close)

    def request(self, method, path, user=1, **kwargs):
        headers = {"Authorization": "Bearer " + create_access_token({"sub": str(user)})}
        return self.client.request(method, path, headers=headers, **kwargs)

    def command(self, text, user=1, **values):
        return self.request("POST", "/ai/commands", user, json={"command": text, **values})

    def test_owned_classifier_recognises_supported_intents(self):
        self.assertEqual(model.predict("schedule a class tomorrow at 10 am")[0], "schedule_class")
        self.assertEqual(model.predict("create assignment on arrays")[0], "draft_assignment")
        self.assertEqual(model.predict("import students from erp")[0], "import_erp_students")

    def test_ai_erp_command_previews_and_confirms_role_based_users(self):
        self.db.add(ERPIntegration(institution_id=1, base_url="https://erp.alpha.example",
                                   encrypted_api_token=encrypt_secret("isolated-ai-erp-token-12345"),
                                   external_institution_id="ALPHA", enabled=True, sync_students=True,
                                   sync_courses=False, sync_attendance=False))
        self.db.commit()
        export = {"institution_id": "ALPHA", "users": [{
            "role": "faculty", "institutional_id": "EMP-AI", "name": "AI ERP Faculty",
            "email": "ai.faculty@alpha.edu", "department": "CS",
        }]}
        with patch("app.routers.erp.fetch_erp_users", return_value=export):
            response = self.command("Import users from ERP based on role", user=4)
        self.assertEqual(response.status_code, 201, response.text)
        action = response.json()["action"]
        self.assertEqual(action["preview"]["creates"], 1)
        self.assertEqual(action["preview"]["records"][0]["role"], "faculty")
        self.assertEqual(self.db.query(User).filter_by(institutional_id="EMP-AI").count(), 0)
        with patch("app.routers.erp.fetch_erp_users", return_value=export):
            confirmed = self.request("POST", f"/ai/actions/{action['id']}/confirm", user=4)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        account = self.db.query(User).filter_by(institutional_id="EMP-AI").one()
        self.assertEqual(account.role, UserRole.faculty)

    def test_schedule_requires_preview_and_explicit_confirmation(self):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        response = self.command(f"Schedule a Cloud Computing class on {tomorrow} at 10:30 AM")
        self.assertEqual(response.status_code, 201, response.text)
        action = response.json()["action"]
        self.assertEqual((action["intent"], action["status"], action["requires_confirmation"]),
                         ("schedule_class", "draft", True))
        self.assertEqual(self.db.query(ScheduledClass).count(), 0)
        confirmed = self.request("POST", f"/ai/actions/{action['id']}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(self.db.query(ScheduledClass).count(), 1)
        self.assertEqual(self.db.query(ScheduledClass).one().title, "Cloud Computing class")
        repeated = self.request("POST", f"/ai/actions/{action['id']}/confirm")
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(self.db.query(ScheduledClass).count(), 1)

    def test_course_and_role_boundaries_are_fail_closed(self):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        forbidden_course = self.command(f"Schedule Machine Learning on {tomorrow} at 10 AM", course_id=2)
        self.assertIn(forbidden_course.status_code, (403, 404))
        student_write = self.command("Create assignment on arrays for Cloud Computing", user=3)
        self.assertEqual(student_write.status_code, 403)
        foreign_progress = self.command("Show progress", user=4, student_id=5)
        self.assertEqual(foreign_progress.status_code, 404)

    def test_assignment_is_created_only_after_confirmation(self):
        response = self.command("Create assignment on load balancing for Cloud Computing worth 25 marks")
        self.assertEqual(response.status_code, 201, response.text)
        action = response.json()["action"]
        self.assertEqual(self.db.query(Assignment).count(), 0)
        confirmed = self.request("POST", f"/ai/actions/{action['id']}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        assignment = self.db.query(Assignment).one()
        self.assertEqual((assignment.course_id, assignment.max_marks), (1, 25))

    def test_quiz_outline_never_publishes_invented_answers(self):
        response = self.command("Draft a 10 question quiz on load balancing for Cloud Computing")
        self.assertEqual(response.status_code, 201, response.text)
        action = response.json()["action"]
        self.assertEqual(action["status"], "completed")
        self.assertFalse(action["preview"]["published"])
        self.assertIn("faculty_input_required", action["preview"])

    def test_faculty_notes_generate_reviewed_quiz_before_publication(self):
        notes = ("Load Balancing distributes network traffic across servers. "
                 "Round Robin assigns requests in a repeating sequence. "
                 "Least Connections selects the server with the fewest active sessions. "
                 "Health Checks identify unavailable servers. "
                 "A Load Balancer improves service availability and scalability.")
        response = self.request("POST", "/ai/content-drafts", json={
            "course_id": 1, "content_type": "quiz", "topic": "Load Balancing",
            "source_text": notes, "question_count": 4, "max_marks": 40,
        })
        self.assertEqual(response.status_code, 201, response.text)
        action = response.json()["action"]
        self.assertEqual((action["intent"], action["status"], action["requires_confirmation"]),
                         ("draft_quiz", "draft", True))
        self.assertEqual(self.db.query(Quiz).count(), 0)
        self.assertFalse(action["preview"]["external_model"])
        self.assertEqual(action["preview"]["generated_question_count"], 4)
        for question in action["preview"]["questions"]:
            self.assertIn(question["options"][question["correct_option"]], notes)
        confirmed = self.request("POST", f"/ai/actions/{action['id']}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual((self.db.query(Quiz).count(), self.db.query(Question).count()), (1, 4))
        self.assertEqual(confirmed.json()["action"]["result"]["question_count"], 4)

    def test_content_studio_is_course_scoped_and_rejects_weak_sources(self):
        notes = ("Recursion solves a problem through smaller instances. Base Case stops recursive calls. "
                 "Call Stack stores active function frames. Recursive Case reduces the current problem. "
                 "Stack Overflow occurs when recursion does not terminate.")
        assignment = self.request("POST", "/ai/content-drafts", json={
            "course_id": 1, "content_type": "assignment", "topic": "Recursion",
            "source_text": notes, "max_marks": 25,
        })
        self.assertEqual(assignment.status_code, 201, assignment.text)
        self.assertEqual(self.db.query(Assignment).count(), 0)
        confirmed = self.request("POST", f"/ai/actions/{assignment.json()['action']['id']}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertIn("Recursion", self.db.query(Assignment).one().description)
        forbidden = self.request("POST", "/ai/content-drafts", user=1, json={
            "course_id": 2, "content_type": "quiz", "topic": "Foreign course",
            "source_text": notes, "question_count": 3,
        })
        self.assertIn(forbidden.status_code, (403, 404))
        student = self.request("POST", "/ai/content-drafts", user=3, json={
            "course_id": 1, "content_type": "quiz", "topic": "Recursion",
            "source_text": notes, "question_count": 3,
        })
        self.assertEqual(student.status_code, 403)
        weak = self.request("POST", "/ai/content-drafts", json={
            "course_id": 1, "content_type": "quiz", "topic": "Short",
            "source_text": "This is intentionally too short to be accepted.", "question_count": 3,
        })
        self.assertEqual(weak.status_code, 422)

    def test_course_knowledge_answers_only_from_published_scoped_sources(self):
        content = ("Load Balancing distributes incoming requests across multiple servers. "
                   "Round Robin assigns each request to the next server in a repeating sequence. "
                   "Health Checks remove unavailable servers from active routing. "
                   "Least Connections chooses the server with the fewest active connections.")
        created = self.request("POST", "/ai/knowledge-sources", user=1, json={
            "course_id": 1, "title": "Faculty-approved load balancing notes",
            "source_type": "faculty_note", "content": content, "publish_to_students": True,
        })
        self.assertEqual(created.status_code, 201, created.text)
        source_id = created.json()["source"]["id"]
        self.assertEqual(self.db.query(AIKnowledgeSource).count(), 1)

        listed = self.request("GET", "/ai/knowledge-sources/course/1", user=3)
        self.assertEqual([item["title"] for item in listed.json()], ["Faculty-approved load balancing notes"])
        answer = self.request("POST", "/ai/course-question", user=3,
                              json={"course_id": 1, "question": "How does Round Robin assign requests?"})
        self.assertEqual(answer.status_code, 201, answer.text)
        result = answer.json()["action"]["result"]
        self.assertTrue(result["answered"])
        self.assertIn("Round Robin", result["citations"][0]["excerpt"])
        self.assertFalse(result["external_model"])

        unsupported = self.request("POST", "/ai/course-question", user=3,
                                   json={"course_id": 1, "question": "Explain quantum entanglement"})
        self.assertFalse(unsupported.json()["action"]["result"]["answered"])
        self.assertEqual(unsupported.json()["action"]["result"]["citations"], [])
        self.assertEqual(self.request("POST", "/ai/knowledge-sources", user=3, json={
            "course_id": 1, "title": "Student source", "source_type": "other",
            "content": content, "publish_to_students": True,
        }).status_code, 403)
        self.assertIn(self.request("POST", "/ai/knowledge-sources", user=2, json={
            "course_id": 1, "title": "Wrong faculty", "source_type": "other",
            "content": content, "publish_to_students": True,
        }).status_code, (403, 404))

        hidden = self.request("PATCH", f"/ai/knowledge-sources/{source_id}/publication", user=1,
                              json={"published": False})
        self.assertEqual(hidden.status_code, 200, hidden.text)
        self.assertEqual(self.request("GET", "/ai/knowledge-sources/course/1", user=3).json(), [])
        no_source = self.request("POST", "/ai/course-question", user=3,
                                 json={"course_id": 1, "question": "What is load balancing?"})
        self.assertFalse(no_source.json()["action"]["result"]["answered"])
        self.assertEqual(self.request("GET", "/ai/knowledge-sources/course/1", user=6).status_code, 404)

    def test_stage_four_lecture_digest_requires_completed_class_and_faculty_review(self):
        transcript = ("Load balancing distributes incoming traffic across multiple service servers. "
                      "Round robin assigns requests to servers in a repeating order. "
                      "Health checks exclude servers that are unavailable from routing. "
                      "Least connections chooses the server with the smallest active workload. "
                      "The teacher compares round robin and least connections during the lecture.")
        self.db.add_all([ClassSession(id=40, course_id=1, jitsi_room_id="lecture-ended",
                                      ended_at=datetime.now(timezone.utc)),
                         ClassSession(id=41, course_id=1, jitsi_room_id="lecture-active"),
                         ClassSession(id=42, course_id=2, jitsi_room_id="other-faculty-ended",
                                      ended_at=datetime.now(timezone.utc))])
        self.db.commit()
        payload = {"transcript": transcript, "transcript_source": "faculty_text", "permissions_confirmed": True}
        self.assertEqual(self.request("POST", "/ai/lectures/sessions/40/transcript",
                                      json={**payload, "permissions_confirmed": False}).status_code, 422)
        self.assertEqual(self.request("POST", "/ai/lectures/sessions/41/transcript", json=payload).status_code, 409)
        self.assertEqual(self.request("POST", "/ai/lectures/sessions/42/transcript", json=payload).status_code, 403)
        self.assertEqual(self.request("POST", "/ai/lectures/sessions/40/transcript", user=3, json=payload).status_code, 403)
        draft = self.request("POST", "/ai/lectures/sessions/40/transcript", json=payload)
        self.assertEqual(draft.status_code, 201, draft.text)
        digest = draft.json()
        self.assertEqual((digest["status"], digest["transcript_source"]), ("draft", "faculty_text"))
        self.assertFalse(digest["summary"]["external_model"])
        self.assertTrue(digest["summary"]["review_required"])
        for note in digest["summary"]["notes"]:
            self.assertIn(note["text"], transcript)
        self.assertEqual(self.request("GET", "/ai/lectures/course/1", user=3).json(), [])
        self.assertEqual(self.db.query(AIKnowledgeSource).count(), 0)
        self.assertEqual(self.request("PATCH", f"/ai/lectures/{digest['id']}/publication", user=3,
                                      json={"publish": True}).status_code, 403)
        self.assertEqual(self.request("PATCH", f"/ai/lectures/{digest['id']}/publication",
                                      json={"publish": True}).status_code, 409)
        self.assertEqual(self.request("PATCH", f"/ai/lectures/{digest['id']}/review", user=3,
                                      json={"included_statement_numbers": [1], "included_topics": []}).status_code, 403)
        self.assertEqual(self.request("PATCH", f"/ai/lectures/{digest['id']}/review",
                                      json={"included_statement_numbers": [999], "included_topics": []}).status_code, 422)
        selected = [note["statement_number"] for note in digest["summary"]["notes"][:-1]]
        excluded = digest["summary"]["notes"][-1]["text"]
        reviewed = self.request("PATCH", f"/ai/lectures/{digest['id']}/review",
                                json={"included_statement_numbers": selected, "included_topics": []})
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["status"], "reviewed")
        self.assertNotIn(excluded, reviewed.json()["summary"]["summary"])
        published = self.request("PATCH", f"/ai/lectures/{digest['id']}/publication",
                                 json={"publish": True})
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()["status"], "published")
        self.assertEqual(self.db.query(AIKnowledgeSource).count(), 1)
        source_id = self.db.query(AIKnowledgeSource).one().id
        faculty_sources = self.request("GET", "/ai/knowledge-sources/course/1").json()
        self.assertTrue(faculty_sources[0]["managed_by_lecture"])
        self.assertEqual(self.request("PATCH", f"/ai/knowledge-sources/{source_id}/publication",
                                      json={"published": False}).status_code, 409)
        self.assertEqual(self.request("DELETE", f"/ai/knowledge-sources/{source_id}").status_code, 409)
        self.assertTrue(self.db.query(AIKnowledgeSource).one().is_published)
        student = self.request("GET", "/ai/lectures/course/1", user=3).json()
        self.assertEqual(len(student), 1)
        self.assertIsNone(student[0]["transcript"])
        self.assertTrue(student[0]["summary"]["notes"])
        self.assertNotIn("candidate_notes", student[0]["summary"])
        self.assertNotIn(excluded, student[0]["summary"]["summary"])
        self.assertNotIn(excluded, self.db.query(AIKnowledgeSource).one().content)
        self.assertEqual(self.request("GET", "/ai/lectures/course/1", user=5).status_code, 404)
        self.assertEqual(self.request("POST", "/ai/lectures/sessions/40/transcript", json=payload).status_code, 409)
        unpublished = self.request("PATCH", f"/ai/lectures/{digest['id']}/publication",
                                   json={"publish": False})
        self.assertEqual(unpublished.status_code, 200)
        self.assertEqual(self.request("GET", "/ai/lectures/course/1", user=3).json(), [])
        self.assertFalse(self.db.query(AIKnowledgeSource).one().is_published)

    def test_private_local_recording_intake_is_scoped_and_never_claims_transcription(self):
        self.db.add_all([ClassSession(id=44, course_id=1, jitsi_room_id="recording-ended",
                                      ended_at=datetime.now(timezone.utc)),
                         ClassSession(id=45, course_id=1, jitsi_room_id="recording-active")])
        self.db.commit()
        media = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 2048
        upload = {"files": {"file": ("class.mp4", media, "video/mp4")},
                  "data": {"permissions_confirmed": "true"}}
        with TemporaryDirectory() as folder, patch("app.routers.lectures._recording_root", return_value=Path(folder)):
            self.assertEqual(self.request("GET", "/ai/lectures/recording-capabilities", user=3).status_code, 403)
            capabilities = self.request("GET", "/ai/lectures/recording-capabilities").json()
            self.assertTrue(capabilities["local_upload_available"])
            self.assertFalse(capabilities["automatic_recording_available"])
            self.assertFalse(capabilities["automatic_transcription_available"])
            self.assertEqual(self.request("POST", "/ai/lectures/sessions/44/recording",
                                          files=upload["files"], data={"permissions_confirmed": "false"}).status_code, 422)
            self.assertEqual(self.request("POST", "/ai/lectures/sessions/45/recording", **upload).status_code, 409)
            self.assertEqual(self.request("POST", "/ai/lectures/sessions/44/recording", user=2, **upload).status_code, 403)
            self.assertEqual(self.request("POST", "/ai/lectures/sessions/44/recording", user=3, **upload).status_code, 403)
            self.assertEqual(self.request("POST", "/ai/lectures/sessions/44/recording",
                                          files={"file": ("fake.mp4", b"not a video", "video/mp4")},
                                          data={"permissions_confirmed": "true"}).status_code, 422)
            self.assertEqual(list(Path(folder).iterdir()), [])
            with patch.dict("os.environ", {"VERCEL": "1"}):
                self.assertEqual(self.request("POST", "/ai/lectures/sessions/44/recording", **upload).status_code, 503)
            uploaded = self.request("POST", "/ai/lectures/sessions/44/recording", **upload)
            self.assertEqual(uploaded.status_code, 201, uploaded.text)
            self.assertEqual(uploaded.json()["notes_status"], None)
            self.assertEqual(uploaded.json()["status"], "uploaded")
            self.assertEqual(len(list(Path(folder).iterdir())), 1)
            recording_id = uploaded.json()["id"]
            saved_file = next(Path(folder).glob("*.mp4"))
            saved_file.write_bytes(media[:-1] + b"x")
            with patch.object(settings, "recording_storage_dir", folder), patch(
                "app.native_ai.recording_media.shutil.which", return_value="ffmpeg-test"
            ):
                queued = self.request("POST", f"/ai/lectures/recordings/{recording_id}/prepare")
                self.assertEqual(queued.status_code, 200, queued.text)
                self.assertEqual(queued.json()["status"], "queued")
                self.assertEqual(self.request("POST", f"/ai/lectures/recordings/{recording_id}/prepare").json()["id"], queued.json()["id"])
                failed = process_next_recording_job(self.db, 1, runner=lambda *_args, **_options: None)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error_code"], "recording_integrity_failed")
            self.assertEqual(self.db.query(AILectureRecording).one().status, "preparation_failed")
            saved_file.write_bytes(media)
            def fake_ffmpeg(arguments, **_options):
                output = Path(arguments[-1])
                if output.name == "%06d.jpg":
                    (output.parent / "000001.jpg").write_bytes(b"frame")
                else:
                    output.write_bytes(b"RIFFtest-audio")
            with patch.object(settings, "recording_storage_dir", folder), patch(
                "app.native_ai.recording_media.shutil.which", return_value="ffmpeg-test"
            ):
                retried = self.request("POST", f"/ai/lectures/recordings/{recording_id}/prepare")
                self.assertEqual(retried.json()["status"], "queued")
                prepared = process_next_recording_job(self.db, 1, runner=fake_ffmpeg)
            self.assertEqual(prepared["status"], "completed", prepared)
            self.assertEqual(prepared["result"]["sampled_frame_count"], 1)
            self.assertFalse(prepared["result"]["transcript_created"])
            self.assertFalse(prepared["result"]["notes_created"])
            self.assertEqual(self.db.query(AILectureRecording).one().status, "media_prepared")
            self.assertEqual(len(list((Path(folder) / "derived").glob("*/audio.wav"))), 1)
            self.assertEqual(self.request("POST", f"/ai/lectures/recordings/{recording_id}/prepare").status_code, 409)
            self.assertEqual(self.request("GET", "/ai/lectures/recordings/course/1", user=3).status_code, 403)
            self.assertEqual(self.request("GET", "/ai/lectures/recordings/course/1", user=2).status_code, 403)
            self.assertEqual(self.request("GET", "/ai/lectures/recordings/course/1", user=6).status_code, 404)
            self.assertEqual(len(self.request("GET", "/ai/lectures/recordings/course/1").json()), 1)
            self.assertEqual(self.request("POST", "/ai/lectures/sessions/44/recording", **upload).status_code, 409)
            transcript = ("The professor explains cloud load balancing across server nodes. "
                          "Round robin assigns client requests in a repeating order. "
                          "Health checks stop traffic to an unavailable service. "
                          "The class compares cloud routing choices using these examples. ")
            notes = self.request("POST", "/ai/lectures/sessions/44/transcript",
                                 json={"transcript": transcript, "permissions_confirmed": True})
            self.assertEqual(notes.status_code, 201, notes.text)
            self.assertEqual(self.request("GET", "/ai/lectures/recordings/course/1").json()[0]["notes_status"], "draft")
            self.assertEqual(self.request("DELETE", f"/ai/lectures/recordings/{recording_id}", user=3).status_code, 403)
            with patch.dict("os.environ", {"VERCEL": "1"}):
                self.assertEqual(self.request("POST", f"/ai/lectures/recordings/{recording_id}/prepare").status_code, 503)
                self.assertEqual(self.request("DELETE", f"/ai/lectures/recordings/{recording_id}").status_code, 503)
            self.assertEqual(self.request("DELETE", f"/ai/lectures/recordings/{recording_id}").status_code, 204)
            self.assertEqual(list(Path(folder).glob("*.mp4")), [])
            self.assertEqual(list((Path(folder) / "derived").glob("*/audio.wav")), [])
            self.assertEqual(self.request("GET", "/ai/lectures/recordings/course/1").json(), [])
            self.assertEqual(self.db.query(AILectureRecording).one().status, "deleted")
            self.assertEqual(self.request("GET", "/ai/lectures/course/1").json()[0]["status"], "draft")

    def test_private_model_contract_validates_speech_and_slide_output(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            executable = root / "ekeekrta-model.exe"
            executable.write_bytes(b"private-test-binary")
            audio = root / "audio.wav"
            audio.write_bytes(b"RIFF-private-test")
            frames = root / "frames"
            frames.mkdir()

            def speech_runner(arguments, **options):
                self.assertFalse(options["shell"])
                Path(arguments[-1]).write_text(json.dumps({
                    "schema_version": 1, "language": "en",
                    "segments": [
                        {"start_ms": 0, "end_ms": 12000, "speaker": "Faculty",
                         "confidence": 0.93, "text": "Load balancing distributes requests across healthy servers so one machine does not receive every request."},
                        {"start_ms": 12000, "end_ms": 25000, "speaker": "Faculty",
                         "confidence": 0.91, "text": "Health checks remove unavailable servers from routing until those servers recover and pass validation again."},
                    ]}), encoding="utf-8")

            speech = run_speech_model(audio, str(executable), "ekeekrta-stt-test-v1", 30, speech_runner)
            self.assertEqual(speech["segment_count"], 2)
            self.assertIn("Faculty", speech["transcript"])
            self.assertEqual(list(root.glob(".speech-*.json")), [])

            def slide_runner(arguments, **options):
                self.assertFalse(options["shell"])
                Path(arguments[-1]).write_text(json.dumps({
                    "schema_version": 1,
                    "slides": [{"timestamp_ms": 30000, "confidence": 0.88,
                                "text": "Application Load Balancer health-check workflow"}],
                }), encoding="utf-8")

            slides = run_slide_ocr(frames, str(executable), "ekeekrta-ocr-test-v1", 30, slide_runner)
            self.assertEqual(slides["slide_count"], 1)
            self.assertEqual(list(root.glob(".slides-*.json")), [])

            def bad_runner(arguments, **_options):
                Path(arguments[-1]).write_text('{"schema_version":1,"segments":[]}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "invalid_segments"):
                run_speech_model(audio, str(executable), "ekeekrta-stt-test-v1", 30, bad_runner)

    def test_private_worker_creates_review_draft_from_configured_local_model(self):
        self.db.add(ClassSession(id=46, course_id=1, jitsi_room_id="model-ended",
                                 ended_at=datetime.now(timezone.utc)))
        with TemporaryDirectory() as folder:
            root = Path(folder)
            storage_key = f"{'a' * 32}.mp4"
            raw = b"\x00\x00\x00\x18ftypisom" + b"private-recording"
            (root / storage_key).write_bytes(raw)
            prepared = root / "derived" / ("a" * 32)
            (prepared / "frames").mkdir(parents=True)
            (prepared / "audio.wav").write_bytes(b"RIFF-private-audio")
            (prepared / "frames" / "000001.jpg").write_bytes(b"frame")
            executable = root / "ekeekrta-stt.exe"
            executable.write_bytes(b"private-model")
            recording = AILectureRecording(institution_id=1, course_id=1, session_id=46,
                uploaded_by=1, original_filename="class.mp4", content_type="video/mp4",
                storage_key=storage_key, size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                status="media_prepared")
            self.db.add(recording); self.db.flush()
            self.db.add(AILecturePreparationJob(institution_id=1, course_id=1,
                recording_id=recording.id, requested_by=1, status="queued",
                stage="awaiting_private_worker"))
            self.db.commit()

            def model_runner(arguments, **_options):
                self.assertIn("--input-audio", arguments)
                Path(arguments[-1]).write_text(json.dumps({
                    "schema_version": 1, "language": "en",
                    "segments": [
                        {"start_ms": 0, "end_ms": 14000, "speaker": "Faculty", "confidence": 0.94,
                         "text": "The lecture explains that load balancing distributes incoming requests across healthy application servers."},
                        {"start_ms": 14000, "end_ms": 30000, "speaker": "Faculty", "confidence": 0.92,
                         "text": "Health checks temporarily remove unavailable servers and return them to routing only after successful recovery checks."},
                        {"start_ms": 30000, "end_ms": 42000, "speaker": "Faculty", "confidence": 0.90,
                         "text": "Students compare round robin routing with least connection routing using the demonstrated cloud architecture."},
                    ]}), encoding="utf-8")

            patches = [
                patch.object(settings, "recording_storage_dir", folder),
                patch.object(settings, "native_speech_model_executable", str(executable)),
                patch.object(settings, "native_speech_model_id", "ekeekrta-stt-test-v1"),
                patch.object(settings, "native_slide_ocr_executable", ""),
                patch.object(settings, "native_slide_ocr_model_id", ""),
            ]
            for active_patch in patches:
                active_patch.start(); self.addCleanup(active_patch.stop)
            result = process_next_recording_job(self.db, 1, runner=model_runner)
            self.assertEqual(result["stage"], "transcript_draft_ready_for_faculty_review")
            self.assertTrue(result["result"]["transcript_created"])
            lecture = self.db.query(AILectureContent).filter(AILectureContent.session_id == 46).one()
            self.assertEqual(lecture.transcript_source, "ekeekrta_local_models")
            self.assertEqual(lecture.status, "draft")
            self.assertEqual(lecture.summary["model_provenance"]["speech_model_id"], "ekeekrta-stt-test-v1")
            self.assertTrue(lecture.summary["review_required"])
            self.assertEqual(self.db.get(AILectureRecording, recording.id).status, "transcript_draft_ready")

    def test_jibri_import_is_private_idempotent_and_queues_processing(self):
        self.db.add(ClassSession(id=47, course_id=1, jitsi_room_id="jibri-ended",
                                 ended_at=datetime.now(timezone.utc)))
        self.db.commit()
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "jibri-class.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"recorded-class")
            private = root / "private"
            with patch.object(settings, "recording_storage_dir", str(private)):
                with self.assertRaisesRegex(ValueError, "permission_not_confirmed"):
                    ingest_jibri_recording(self.db, 47, source, False)
                item = ingest_jibri_recording(self.db, 47, source, True)
                repeated = ingest_jibri_recording(self.db, 47, source, True)
            self.assertEqual(item.id, repeated.id)
            self.assertEqual(item.status, "preparation_queued")
            self.assertEqual(self.db.query(AILecturePreparationJob).filter_by(recording_id=item.id).count(), 1)
            self.assertEqual(len(list(private.glob("*.mp4"))), 1)
            item.created_at = datetime.now(timezone.utc) - timedelta(days=10)
            job = self.db.query(AILecturePreparationJob).filter_by(recording_id=item.id).one()
            self.db.commit()
            with patch.object(settings, "recording_storage_dir", str(private)), patch.object(
                    settings, "recording_retention_days", 7):
                self.assertEqual(purge_expired_recordings(self.db)["eligible_recording_ids"], [])
                job.status = "completed"; self.db.commit()
                preview = purge_expired_recordings(self.db)
                self.assertEqual(preview["eligible_recording_ids"], [item.id])
                applied = purge_expired_recordings(self.db, True)
            self.assertEqual(applied["deleted"], 1)
            self.assertEqual(list(private.glob("*.mp4")), [])
            self.assertEqual(self.db.get(AILectureRecording, item.id).status, "expired")

    def test_stage_four_rejects_false_audio_origin_and_weak_transcript(self):
        self.db.add(ClassSession(id=43, course_id=1, jitsi_room_id="lecture-second",
                                 ended_at=datetime.now(timezone.utc)))
        self.db.commit()
        self.assertEqual(self.request("POST", "/ai/lectures/sessions/43/transcript",
                                      json={"transcript_source": "automatic_recording",
                                            "transcript": "This is a long text. " * 20,
                                            "permissions_confirmed": True}).status_code, 422)
        weak = "A long meeting introduction without distinct facts or sentence boundaries " * 5
        self.assertEqual(self.request("POST", "/ai/lectures/sessions/43/transcript",
                                      json={"transcript": weak, "permissions_confirmed": True}).status_code, 422)

    def test_progress_is_scoped_and_corrections_require_consent(self):
        progress = self.command("Show my progress", user=3)
        self.assertEqual(progress.status_code, 201, progress.text)
        record = progress.json()["action"]["result"]["records"][0]
        self.assertEqual(record["student_id"], 3)
        action_id = progress.json()["action"]["id"]
        denied = self.request("POST", f"/ai/actions/{action_id}/correction", user=3,
                              json={"corrected_intent": "help", "corrected_payload": {}, "consent": False})
        self.assertEqual(denied.status_code, 422)
        saved = self.request("POST", f"/ai/actions/{action_id}/correction", user=3,
                             json={"corrected_intent": "help", "corrected_payload": {}, "consent": True})
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(self.db.query(AITrainingExample).count(), 1)
        self.assertGreaterEqual(self.db.query(AIAuditLog).count(), 2)

    def test_stage_five_progress_insights_are_explainable_read_only_and_scoped(self):
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        self.db.add_all([
            Assignment(id=30, course_id=1, title="Due one", max_marks=100, due_date=yesterday),
            Assignment(id=31, course_id=1, title="Due two", max_marks=100, due_date=yesterday),
            Assignment(id=32, course_id=1, title="Graded", max_marks=100, due_date=yesterday),
            Quiz(id=30, course_id=1, title="Quiz one"),
            Quiz(id=31, course_id=1, title="Quiz two"),
            ClassSession(id=30, course_id=1, jitsi_room_id="stage-five-one",
                         scheduled_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc)),
            ClassSession(id=31, course_id=1, jitsi_room_id="stage-five-two",
                         scheduled_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc)),
        ])
        self.db.flush()
        self.db.add_all([
            Submission(assignment_id=32, student_id=3, file_url="https://example.com/work", marks_obtained=30),
            QuizAttempt(quiz_id=30, student_id=3, score=35),
            QuizAttempt(quiz_id=31, student_id=3, score=40),
            Attendance(session_id=30, student_id=3, duration_minutes=4, present=False),
            Attendance(session_id=31, student_id=3, duration_minutes=5, present=False),
        ])
        self.db.commit()

        student = self.request("GET", "/ai/progress-insights", user=3)
        self.assertEqual(student.status_code, 200, student.text)
        payload = student.json()
        self.assertEqual((payload["stage"], payload["summary"]["total_students"]), (5, 1))
        self.assertEqual(payload["students"][0]["risk_level"], "critical")
        self.assertEqual(payload["students"][0]["metrics"]["assignments"]["missing_due"], 2)
        self.assertTrue(any("Attendance is 0.0%" in item for item in payload["students"][0]["risk_reasons"]))
        self.assertFalse(payload["external_model"])
        self.assertIn("not an official grade", payload["notice"])
        self.assertEqual(self.db.query(Submission).count(), 1, "Reading insights must not change academic records")

        faculty = self.request("GET", "/ai/progress-insights?course_id=1", user=1)
        self.assertEqual(faculty.status_code, 200, faculty.text)
        self.assertEqual(faculty.json()["scope"]["course"]["code"], "CS401")
        self.assertEqual([item["student_id"] for item in faculty.json()["students"]], [3])
        self.assertEqual(self.request("GET", "/ai/progress-insights?course_id=2", user=1).status_code, 403)
        self.assertEqual(self.request("GET", "/ai/progress-insights?course_id=1", user=6).status_code, 404)
        self.assertGreaterEqual(self.db.query(AIAuditLog).filter_by(event_type="progress_insights_viewed").count(), 2)

    def test_student_cgpa_planner_uses_real_course_evidence_and_checks_feasibility(self):
        self.db.add_all([
            Assignment(id=20, course_id=1, title="Submitted work", max_marks=100),
            Assignment(id=21, course_id=1, title="Missing work", max_marks=100),
            Quiz(id=20, course_id=1, title="Course quiz"),
            ClassSession(id=20, course_id=1, jitsi_room_id="cgpa-evidence-room"),
        ])
        self.db.flush()
        self.db.add_all([
            Submission(assignment_id=20, student_id=3, file_url="https://example.com/work", marks_obtained=45),
            QuizAttempt(quiz_id=20, student_id=3, score=55),
            Attendance(session_id=20, student_id=3, duration_minutes=10, present=False),
        ])
        self.db.commit()
        payload = {"grading_scale_max": 10, "current_cgpa": 7, "target_cgpa": 8,
                   "completed_credits": 60, "remaining_credits": 60,
                   "remaining_semesters": 4, "weekly_study_hours": 16}
        response = self.request("POST", "/ai/cgpa-plan", user=3, json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        action = response.json()["action"]
        projection = action["result"]["projection"]
        self.assertEqual((projection["required_average_for_remaining_credits"],
                          projection["best_possible_final_cgpa"], projection["status"]),
                         (9.0, 8.5, "very_demanding"))
        priority = action["result"]["course_priorities"][0]
        self.assertEqual(priority["course_code"], "CS401")
        self.assertTrue(any("Missing assignments: 1" in item for item in priority["evidence"]))
        self.assertTrue(any("Attendance: 0.0%" in item for item in priority["evidence"]))
        self.assertFalse(action["result"]["external_model"])
        self.assertIn("not an official result", action["result"]["official_record_notice"])
        self.assertEqual(self.db.query(AIAction).filter_by(intent="cgpa_plan", requester_id=3).count(), 1)

        impossible = self.request("POST", "/ai/cgpa-plan", user=3,
                                  json={**payload, "target_cgpa": 9.5})
        self.assertEqual(impossible.json()["action"]["result"]["projection"]["status"],
                         "not_mathematically_reachable")
        self.assertEqual(self.request("POST", "/ai/cgpa-plan", user=1, json=payload).status_code, 403)
        self.assertEqual(self.request("POST", "/ai/cgpa-plan", user=3,
                                      json={**payload, "target_cgpa": 11}).status_code, 422)

    def test_stage_two_saves_goal_simulates_course_grades_and_refreshes_verified_erp(self):
        student = self.db.get(User, 3); student.institutional_id = "A-003"
        self.db.get(Course, 1).credits = 4
        self.db.add(ERPIntegration(institution_id=1, base_url="https://erp.alpha.example",
                                   encrypted_api_token=encrypt_secret("isolated-ai-erp-token-12345"),
                                   external_institution_id="ALPHA", enabled=True, sync_students=True,
                                   sync_courses=False, sync_attendance=False))
        self.db.commit()
        payload = {"grading_scale_max": 10, "current_cgpa": 7, "target_cgpa": 8,
                   "completed_credits": 60, "remaining_credits": 60,
                   "remaining_semesters": 4, "weekly_study_hours": 16,
                   "course_scenarios": [{"course_id": 1, "expected_grade_point": 9}]}
        response = self.request("POST", "/ai/cgpa-plan", user=3, json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        scenario = response.json()["action"]["result"]["course_scenario"]
        self.assertEqual((scenario["scenario_credits"], scenario["projected_cgpa_after_scenario"]), (4, 7.12))
        saved = self.request("GET", "/ai/cgpa-goal", user=3).json()["goal"]
        self.assertEqual(saved["target_cgpa"], 8)
        self.assertEqual(saved["checkpoints"][0]["source"], "student")
        self.assertEqual(self.db.query(AICGPAGoal).count(), 1)

        export = {"institution_id": "ALPHA", "result": {"student_institutional_id": "A-003",
                  "current_cgpa": 7.5, "completed_credits": 80, "remaining_credits": 40,
                  "grading_scale_max": 10}}
        with patch("app.routers.ai.fetch_erp_academic_result", return_value=export):
            refreshed = self.request("POST", "/ai/cgpa-goal/refresh-erp", user=3)
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertIn("Verified institution ERP", refreshed.json()["action"]["result"]["data_basis"])
        saved = self.request("GET", "/ai/cgpa-goal", user=3).json()["goal"]
        self.assertEqual((saved["current_cgpa"], saved["data_source"]), (7.5, "erp"))
        self.assertEqual([item["source"] for item in saved["checkpoints"]], ["student", "erp"])

        foreign_scenario = self.request("POST", "/ai/cgpa-plan", user=3,
                                        json={**payload, "course_scenarios": [{"course_id": 2, "expected_grade_point": 8}]})
        self.assertEqual(foreign_scenario.status_code, 403)

    def test_history_is_private_to_requester_and_institution(self):
        self.command("Show my progress", user=3)
        self.command("Show progress for students", user=4)
        student_history = self.request("GET", "/ai/actions", user=3).json()
        admin_history = self.request("GET", "/ai/actions", user=4).json()
        self.assertEqual(len(student_history), 1)
        self.assertEqual(len(admin_history), 1)
        self.assertNotEqual(student_history[0]["id"], admin_history[0]["id"])
        self.assertEqual(self.db.query(AIAction).count(), 2)

    def test_admin_can_preview_and_confirm_department_creation(self):
        response = self.command("Create department Electronics", user=4)
        self.assertEqual(response.status_code, 201, response.text)
        action = response.json()["action"]
        self.assertEqual(action["intent"], "create_department")
        self.assertIsNone(self.db.query(Department).filter_by(name="Electronics").first())
        confirmed = self.request("POST", f"/ai/actions/{action['id']}/confirm", user=4)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertIsNotNone(self.db.query(Department).filter_by(institution_id=1, name="Electronics").first())
        self.assertEqual(self.command("Create department Civil", user=1).status_code, 403)

    def test_faculty_can_create_structured_course_for_own_department(self):
        response = self.command("Create course Distributed Systems code CS402 department CS program B.Tech CSE batch 2026-2030 semester 7 section A compulsory")
        self.assertEqual(response.status_code, 201, response.text)
        action = response.json()["action"]
        self.assertEqual(action["preview"]["faculty"], "Faculty One")
        self.assertEqual(self.db.query(Course).filter_by(code="CS402").count(), 0)
        confirmed = self.request("POST", f"/ai/actions/{action['id']}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        course = self.db.query(Course).filter_by(code="CS402").one()
        self.assertEqual((course.faculty_id, course.semester_number, course.enrollment_mode), (1, 7, "compulsory"))

    def test_bulk_accounts_are_validated_then_created_without_shared_password(self):
        records = [{"role": "student", "name": "Bulk Student", "email": "bulk.student@alpha.edu",
                    "institutional_id": "BULK-S-1", "department": "CS", "program": "B.Tech CSE",
                    "batch": "2026-2030", "semester_number": 1, "section": "A"},
                   {"role": "faculty", "name": "Bulk Faculty", "email": "bulk.faculty@alpha.edu",
                    "institutional_id": "BULK-F-1", "department": "CS"}]
        response = self.request("POST", "/ai/bulk-accounts/preview", user=4, json={"records": records})
        self.assertEqual(response.status_code, 201, response.text)
        action = response.json()["action"]
        self.assertEqual(action["status"], "draft")
        self.assertNotIn("password", str(action["payload"]).lower())
        confirmed = self.request("POST", f"/ai/actions/{action['id']}/confirm", user=4)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["action"]["result"]["created_count"], 2)
        self.assertEqual(self.db.query(User).filter(User.email.like("bulk.%")).count(), 2)
        duplicate = self.request("POST", "/ai/bulk-accounts/preview", user=4, json={"records": records})
        self.assertEqual(duplicate.json()["action"]["status"], "needs_changes")
        self.assertEqual(duplicate.json()["action"]["preview"]["invalid_rows"], 2)

    def test_admin_review_is_institution_scoped_and_can_reject_pending_action(self):
        draft = self.command("Create assignment on networks for Cloud Computing").json()["action"]
        self.assertEqual(self.request("GET", "/ai/review/actions", user=1).status_code, 403)
        review = self.request("GET", "/ai/review/actions", user=4)
        self.assertEqual(review.status_code, 200, review.text)
        item = next(row for row in review.json() if row["action"]["id"] == draft["id"])
        self.assertEqual(item["requester"]["name"], "Faculty One")
        self.assertEqual(self.request("GET", "/ai/review/actions", user=6).json(), [])
        rejected = self.request("POST", f"/ai/review/actions/{draft['id']}/reject", user=4)
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
