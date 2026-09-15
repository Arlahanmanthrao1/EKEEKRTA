"""Disposable in-memory security fixtures. Never connect to application databases."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.models
from app.database import Base, get_db
from app.core.security import create_access_token
from app.models import User, UserRole, Course, Enrollment, Assignment, Submission, Quiz, Question, Attendance, ClassSession
from app.models.institution import Institution, Department
from app.routers import auth, institutions, users, courses, assignments, quiz, materials, attendance
from app.config import settings
from app.integrations.erp_client import sync_attendance_to_erp
from app.core.secret_box import encrypt_secret
from app.models.erp import ERPIntegration


class InstitutionAccessTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([Institution(id=1, name="Test Alpha", email_domain="alpha.edu"), Institution(id=2, name="Test Beta", email_domain="beta.edu")])
        self.db.flush()
        self.db.add_all([Department(institution_id=1, name="CS"), Department(institution_id=1, name="EC"), Department(institution_id=2, name="CS")])
        for ident, role, dept, inst in [(1,"admin",None,1),(2,"faculty","CS",1),(3,"student","CS",1),
                                      (4,"hod","CS",1),(5,"faculty","CS",1),(6,"student","EC",1),
                                      (7,"hod",None,1),(8,"faculty","EC",1),(9,"student","CS",1),
                                      (10,"admin",None,2),(11,"faculty","CS",2),(12,"student","CS",2),(13,"hod","CS",2)]:
            self.db.add(User(id=ident, name=f"Test {ident}", email=f"test{ident}@{'alpha' if inst == 1 else 'beta'}.edu",
                             role=UserRole(role), department=dept, institution_id=inst, hashed_password="unused"))
        self.db.flush()
        for ident, faculty, dept, inst, code in [(1,2,"CS",1,"CS101"),(2,5,"CS",1,"CS102"),(3,8,"EC",1,"EC101"),(4,11,"CS",2,"CS101")]:
            self.db.add(Course(id=ident, name=f"Test course {ident}", code=code, faculty_id=faculty, department=dept, institution_id=inst))
        self.db.flush()
        for student, course in [(3,1),(3,2),(3,3),(6,1),(12,4)]:
            self.db.add(Enrollment(student_id=student, course_id=course))
        for ident in range(1,5):
            self.db.add(Assignment(id=ident, course_id=ident, title="Test work", max_marks=100))
            self.db.add(Quiz(id=ident, course_id=ident, title="Test quiz"))
            self.db.add(ClassSession(id=ident, course_id=ident, jitsi_room_id=f"test-room-{ident}"))
        self.db.flush()
        for ident in range(1,5):
            student = 12 if ident == 4 else 3
            self.db.add(Submission(id=ident, student_id=student, assignment_id=ident, file_url="https://example.com/test"))
            self.db.add(Question(id=ident, quiz_id=ident, text="Test?", options=["A", "B"], correct_option=0))
            self.db.add(Attendance(session_id=ident, student_id=student, present=ident == 1, duration_minutes=40 if ident == 1 else 0))
        self.db.commit()
        api = FastAPI()
        for module in [auth, institutions, users, courses, assignments, quiz, materials, attendance]:
            api.include_router(module.router)
        api.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(api)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.addCleanup(self.client.close)

    def request(self, method, path, user=1, **kwargs):
        headers = {"Authorization": "Bearer " + create_access_token({"sub": str(user)})} if user else {}
        return self.client.request(method, path, headers=headers, **kwargs)

    def ids(self, path, user):
        response = self.request("GET", path, user)
        self.assertEqual(response.status_code, 200, response.text)
        return {entry["id"] for entry in response.json()}

    def test_role_directories(self):
        self.assertEqual(self.ids("/users/",1), set(range(1,10)))
        self.assertEqual(self.ids("/users/",4), {2,3,5,9})
        self.assertEqual(self.ids("/users/",2), {3,6})
        self.assertEqual(self.ids("/users/",7), set())
        self.assertEqual(self.request("GET","/users/",3).status_code,403)
        self.assertEqual(self.ids("/users/",10), {10,11,12,13})

    def test_admin_can_delete_unused_accounts_without_erasing_history(self):
        self.assertEqual(self.request("DELETE", "/users/9", 2).status_code, 403)
        self.assertEqual(self.request("DELETE", "/users/12", 1).status_code, 404)
        self.assertEqual(self.request("DELETE", "/users/1", 1).status_code, 409)
        self.assertEqual(self.request("DELETE", "/users/3", 1).status_code, 409)
        self.assertEqual(self.request("DELETE", "/users/9", 1).status_code, 204)
        self.assertIsNone(self.db.get(User, 9))

        # Removing an unused faculty account preserves the course and unassigns it.
        self.assertEqual(self.request("DELETE", "/users/5", 1).status_code, 204)
        self.assertIsNone(self.db.get(User, 5))
        self.assertIsNone(self.db.get(Course, 2).faculty_id)

    def test_course_catalogs_are_scoped(self):
        for user, expected in [(1,{1,2,3}),(2,{1}),(4,{1,2}),(7,set()),(3,{1,2}),(10,{4})]:
            self.assertEqual(self.ids("/courses/",user),expected)
        self.assertEqual(self.ids("/courses/enrolled",3),{1,2,3})
        self.assertEqual(self.ids("/courses/enrolled",9),set())

    def test_cross_institution_reads(self):
        paths = ["/courses/4", "/courses/4/students", "/assignments/course/4", "/assignments/4/submissions",
                 "/quizzes/course/4", "/quizzes/4", "/materials/course/4", "/attendance/sessions/4",
                 "/attendance/sessions/detail/4", "/attendance/summary/12", "/attendance/4/12"]
        for user in [1,2,3,4]:
            for path in paths:
                with self.subTest(user=user,path=path):
                    self.assertIn(self.request("GET",path,user).status_code,[403,404])

    def test_cross_institution_mutations_and_meeting_tokens(self):
        cases = [("POST","/courses/4/enroll",3,None), ("POST","/attendance/sessions",1,{"course_id":4}),
                 ("POST","/attendance/sessions/4/connection",1,None),
                 ("PATCH","/attendance/sessions/4/fullscreen",1,{"fullscreen_required":False}),
                 ("PATCH","/attendance/sessions/4/end",1,None),
                 ("POST","/assignments/",1,{"course_id":4,"title":"Denied"}),
                 ("POST","/assignments/submit",3,{"assignment_id":4,"file_url":"https://example.com/test"}),
                 ("POST","/assignments/submissions/4/grade?marks=10",1,None),
                 ("POST","/quizzes/",1,{"course_id":4,"title":"Denied","questions":[]}),
                 ("POST","/quizzes/attempt",3,{"quiz_id":4,"answers":{"4":0}}),
                 ("POST","/materials/",1,{"course_id":4,"title":"Denied","file_url":"https://example.com/test"}),
                 ("DELETE","/courses/4/students/12",2,None),
                 ("PATCH","/users/12",1,{"name":"Denied","department":"CS"}),
                 ("POST","/attendance/event",3,{"room_id":"test-room-4","course_id":4,"student_id":3,"event_type":"joined","timestamp":"2026-09-04T10:00:00Z"})]
        with patch("app.routers.attendance.meeting_connection") as mint:
            for method,path,user,payload in cases:
                with self.subTest(path=path):
                    response = self.request(method,path,user,json=payload) if payload is not None else self.request(method,path,user)
                    self.assertIn(response.status_code,[403,404],response.text)
            mint.assert_not_called()
        self.assertIsNone(self.db.get(ClassSession,4).ended_at)
        self.assertIsNone(self.db.get(Submission,4).marks_obtained)
        self.assertEqual(self.db.query(Enrollment).count(),5)

    def test_faculty_cannot_manage_other_faculty_course(self):
        for path,payload in [("/assignments/",{"course_id":2,"title":"Denied"}),
                             ("/quizzes/",{"course_id":2,"title":"Denied","questions":[]}),
                             ("/attendance/sessions",{"course_id":2})]:
            self.assertEqual(self.request("POST",path,2,json=payload).status_code,403)
        self.assertEqual(self.request("POST","/assignments/submissions/2/grade?marks=10",2).status_code,403)

    def test_hod_has_no_admin_or_teaching_writes(self):
        for path,payload in [("/auth/register",{"name":"Denied","email":"denied@alpha.edu","password":"test-password","department":"CS"}),
                             ("/auth/register-hod",{"name":"Denied","email":"denied@alpha.edu","password":"test-password","department":"CS"}),
                             ("/institutions/departments",{"name":"Denied"}),
                             ("/courses/",{"name":"Denied","code":"DENY","department":"CS"}),
                             ("/attendance/sessions",{"course_id":1})]:
            self.assertEqual(self.request("POST",path,4,json=payload).status_code,403)
        self.assertEqual(self.request("PATCH","/users/3",4,json={"name":"Denied","department":"CS"}).status_code,403)
        self.assertEqual(self.request("POST","/attendance/sessions/1/connection",4).status_code,403)

    def test_unenrolled_student_cannot_access_coursework(self):
        for path in ["/assignments/course/1","/quizzes/1","/materials/course/1","/attendance/sessions/detail/1"]:
            self.assertEqual(self.request("GET",path,9).status_code,403)
        self.assertEqual(self.request("POST","/assignments/submit",9,json={"assignment_id":1,"file_url":"https://example.com/test"}).status_code,403)
        self.assertEqual(self.request("POST","/quizzes/attempt",9,json={"quiz_id":1,"answers":{}}).status_code,403)

    def test_attendance_aggregates_do_not_leak_other_courses(self):
        for user,total in [(1,3),(2,1),(4,2),(3,3)]:
            response=self.request("GET","/attendance/summary/3",user)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()["total_sessions"],total)
        self.assertEqual(self.request("GET","/attendance/summary/6",4).status_code,404)
        self.assertEqual(self.request("GET","/attendance/summary/3",9).status_code,404)
        self.assertEqual(self.request("GET","/attendance/2/6",5).status_code,404)

    def test_valid_workflows_and_no_correct_answer_disclosure(self):
        response = self.request("GET","/quizzes/1",3)
        self.assertEqual(response.status_code,200)
        self.assertNotIn("correct_option",response.text)
        self.assertEqual(self.request("POST","/quizzes/attempt",3,json={"quiz_id":1,"answers":{"1":0}}).json()["score"],100)
        self.assertEqual(self.request("POST","/assignments/submissions/1/grade?marks=85",2).status_code,200)
        self.assertEqual(self.request("POST","/assignments/submissions/1/grade?marks=101",2).status_code,422)
        self.assertEqual(self.request("POST","/assignments/submit",3,json={"assignment_id":1,"file_url":"https://example.com/test"}).status_code,201)

    def test_registration_and_department_validation(self):
        payload={"name":"Test new HOD","email":"new@alpha.edu","password":"test-password-123","department":"CS","institutional_id":"EMP-001"}
        response=self.request("POST","/auth/register-hod",1,json=payload)
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()["role"],"hod")
        self.assertEqual(response.json()["institution_id"],1)
        for invalid in [{"department":None},{"department":"Unknown"},{"email":"test@beta.edu"},{"institution_id":2},{"role":"admin"}]:
            self.assertEqual(self.request("POST","/auth/register-hod",1,json={**payload,**invalid}).status_code,422)
        self.assertEqual(self.request("POST","/institutions/departments",1,json={"name":" cs "}).status_code,409)
        self.assertEqual(self.request("POST","/institutions/departments",1,json={"name":"Physics"}).status_code,201)
        self.assertEqual(self.request("PATCH","/users/7",1,json={"name":"Test assigned HOD","department":"CS","institutional_id":"EMP-007"}).status_code,200)
        self.assertEqual(self.ids("/users/",7),{2,3,5,9})

    def test_institution_registration_atomicity_and_profile(self):
        uploaded_logo="data:image/png;base64,iVBORw0KGgo="
        payload={"institution":{"name":"Test new institution","email":"office@gamma.edu","logo_url":uploaded_logo},
                 "administrator":{"name":"Test admin","email":"admin@gamma.edu","password":"secure-test-password"}}
        response=self.request("POST","/institutions/register",None,json=payload)
        self.assertEqual(response.status_code,201,response.text)
        ident=response.json()["id"]
        self.assertEqual(self.db.get(Institution,3).logo_url,uploaded_logo)
        self.assertEqual(response.json()["role"],"admin")
        self.assertEqual(self.ids("/users/",ident),{ident})
        self.assertNotIn("password",response.text)
        self.assertEqual(self.request("POST","/institutions/register",None,json=payload).status_code,409)
        self.assertEqual(self.db.query(Institution).count(),3)
        # An administrator email collision must roll back the new institution too.
        self.db.add(User(name="Test orphan",email="taken@delta.edu",role=UserRole.student,hashed_password="unused"))
        self.db.commit()
        payload["institution"]["email"]="office@delta.edu"
        payload["administrator"]["email"]="taken@delta.edu"
        self.assertEqual(self.request("POST","/institutions/register",None,json=payload).status_code,409)
        self.assertEqual(self.db.query(Institution).count(),3)
        update={"name":"Renamed test institution","email":"office@gamma.edu","address":"Test address","logo_url":None}
        self.assertEqual(self.request("PATCH","/institutions/current",ident,json=update).status_code,200)
        self.assertEqual(self.db.get(Institution,1).name,"Test Alpha")
        self.assertEqual(self.request("PATCH","/institutions/current",3,json=update).status_code,403)
        self.assertEqual(self.request("PATCH","/institutions/current",ident,json={**update,"email":"office@beta.edu"}).status_code,422)
        invalid_logo={**update,"logo_url":"data:image/png;base64,bm90LWFuLWltYWdl"}
        self.assertEqual(self.request("PATCH","/institutions/current",ident,json=invalid_logo).status_code,422)

    def test_only_admin_can_change_institution_default_theme(self):
        response = self.request("PATCH", "/institutions/current/theme", 1, json={"default_theme": "dark"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["default_theme"], "dark")
        self.assertEqual(self.db.get(Institution, 1).default_theme, "dark")
        self.assertEqual(self.db.get(Institution, 2).default_theme, "light")
        for user in [2, 3, 4]:
            self.assertEqual(self.request("PATCH", "/institutions/current/theme", user,
                                          json={"default_theme": "system"}).status_code, 403)
        self.assertEqual(self.request("PATCH", "/institutions/current/theme", 1,
                                      json={"default_theme": "neon"}).status_code, 422)

    def test_grading_rules_and_course_credits_follow_their_owners(self):
        grading = self.request("PATCH", "/institutions/current/grading", 1,
                               json={"grading_scale_max": 10, "passing_grade_point": 5})
        self.assertEqual(grading.status_code, 200, grading.text)
        self.assertEqual(grading.json()["passing_grade_point"], 5)
        self.assertEqual(self.request("PATCH", "/institutions/current/grading", 2,
                                      json={"grading_scale_max": 10, "passing_grade_point": 4}).status_code, 403)
        self.assertEqual(self.request("PATCH", "/institutions/current/grading", 1,
                                      json={"grading_scale_max": 10, "passing_grade_point": 11}).status_code, 422)

        owned = self.request("PATCH", "/courses/1/credits", 2, json={"credits": 4})
        self.assertEqual(owned.status_code, 200, owned.text)
        self.assertEqual(owned.json()["credits"], 4)
        self.assertEqual(self.request("PATCH", "/courses/2/credits", 2, json={"credits": 3}).status_code, 403)
        self.assertEqual(self.request("PATCH", "/courses/1/credits", 3, json={"credits": 3}).status_code, 403)
        self.assertEqual(self.request("PATCH", "/courses/4/credits", 1, json={"credits": 3}).status_code, 404)

    def test_unassigned_accounts_and_invalid_tokens_fail_closed(self):
        self.db.get(User,9).institution_id=None
        self.db.commit()
        self.assertEqual(self.request("GET","/auth/me",9).status_code,403)
        self.assertEqual(self.request("GET","/auth/me","bad-subject").status_code,401)
        self.assertEqual(self.request("GET","/institutions/current",None).status_code,401)

    def test_erp_only_receives_configured_institution(self):
        self.db.add(ERPIntegration(institution_id=1, base_url="https://erp.example.com",
                                   encrypted_api_token=encrypt_secret("isolated-test-token"), enabled=True))
        self.db.commit()
        with patch("app.integrations.erp_client.httpx.post") as post:
            post.return_value.status_code = 200
            # Beta has no integration and must never use Alpha's connection.
            self.assertFalse(sync_attendance_to_erp(self.db, self.db.query(Attendance).filter(Attendance.session_id == 4).one(),
                                                     self.db.get(User,12), self.db.get(Course,4), self.db.get(ClassSession,4)))
            post.assert_not_called()
            self.assertTrue(sync_attendance_to_erp(self.db, self.db.query(Attendance).filter(Attendance.session_id == 1).one(),
                                                    self.db.get(User,3), self.db.get(Course,1), self.db.get(ClassSession,1)))
            post.assert_called_once()
            self.assertNotIn("isolated-test-token", self.db.query(ERPIntegration).filter_by(institution_id=1).one().encrypted_api_token)

    def test_migrated_institution_admin_bootstrap_never_promotes_accounts(self):
        from scripts.create_institution_admin import bootstrap
        from app.schemas.user import UserCreate
        institution=Institution(name="Test migrated",email_domain="migrated.edu")
        self.db.add(institution);self.db.commit()
        details=UserCreate(name="Test admin",email="admin@migrated.edu",password="test-admin-password")
        created=bootstrap(self.db,"migrated.edu",details)
        self.db.commit()
        self.assertEqual(created.institution_id,institution.id)
        self.assertEqual(created.role,UserRole.admin)
        with self.assertRaises(ValueError):
            bootstrap(self.db,"migrated.edu",UserCreate(name="Other admin",email="other@migrated.edu",password="test-admin-password"))
        self.db.rollback()
        with self.assertRaises(ValueError):
            bootstrap(self.db,"alpha.edu",UserCreate(name="Test student",email="test3@alpha.edu",password="test-admin-password"))
        self.db.rollback()
        self.assertEqual(self.db.get(User,3).role,UserRole.student)

    def test_course_code_can_repeat_only_in_another_institution(self):
        payload={"name":"Test course","code":"NEW101","department":"CS","program":"B.Tech CS","batch":"2026-2030","semester_number":1}
        self.assertEqual(self.request("POST","/courses/",2,json=payload).status_code,201)
        self.assertEqual(self.request("POST","/courses/",11,json=payload).status_code,201)
        self.assertEqual(self.request("POST","/courses/",2,json=payload).status_code,400)

    def test_course_type_is_saved_and_validated(self):
        payload={"name":"Coding club","code":"CLUB101","department":"CS","course_type":"non_academic"}
        created=self.request("POST","/courses/",2,json=payload)
        self.assertEqual(created.status_code,201,created.text)
        self.assertEqual(created.json()["course_type"],"non_academic")
        invalid=self.request("POST","/courses/",2,json={**payload,"code":"CLUB102","course_type":"other"})
        self.assertEqual(invalid.status_code,422)

    def test_removed_enrollment_excludes_that_course_from_faculty_summary(self):
        self.db.get(Course,2).faculty_id=2
        self.db.query(Enrollment).filter(Enrollment.course_id == 1,Enrollment.student_id == 3).delete()
        self.db.commit()
        summary=self.request("GET","/attendance/summary/3",2)
        self.assertEqual(summary.status_code,200)
        self.assertEqual(summary.json()["total_sessions"],1)
        self.assertEqual(summary.json()["present_count"],0)


if __name__ == "__main__":
    unittest.main()
