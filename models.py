from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Problem(db.Model):
    __tablename__ = 'problems'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    statement = db.Column(db.Text)
    input_format = db.Column(db.Text, nullable=True)
    output_format = db.Column(db.Text, nullable=True)
    samples = db.Column(db.Text, nullable=True)  # store samples as plain text or JSON
    data_range = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    testcases = db.relationship('TestCase', backref='problem', cascade='all,delete-orphan')
    submissions = db.relationship('Submission', backref='problem', cascade='all,delete-orphan')


class TestCase(db.Model):
    __tablename__ = 'test_cases'
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problems.id'), nullable=False)
    input_file = db.Column(db.String(200), nullable=False)
    output_file = db.Column(db.String(200), nullable=False)
    score = db.Column(db.Integer, default=100)
    deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)


class Submission(db.Model):
    __tablename__ = 'submissions'
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problems.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    contest_id = db.Column(db.Integer, db.ForeignKey('contests.id'), nullable=True)
    language = db.Column(db.String(20))
    filename = db.Column(db.String(200))
    submit_time = db.Column(db.DateTime, default=datetime.utcnow)

    results = db.relationship('SubmissionResult', backref='submission', cascade='all,delete-orphan')


class SubmissionResult(db.Model):
    __tablename__ = 'submission_results'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('submissions.id'), nullable=False)
    testcase_id = db.Column(db.Integer, db.ForeignKey('test_cases.id'))
    status = db.Column(db.String(50))
    time_ms = db.Column(db.Integer)
    memory_kb = db.Column(db.Integer)
    score = db.Column(db.Integer, default=0)


class DownloadLog(db.Model):
    __tablename__ = 'download_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    problem_id = db.Column(db.Integer, db.ForeignKey('problems.id'), nullable=False)
    testcase_id = db.Column(db.Integer, db.ForeignKey('test_cases.id'), nullable=True)
    downloaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class Contest(db.Model):
    __tablename__ = 'contests'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    mode = db.Column(db.String(10), default='IOI')  # IOI or OI
    is_homework = db.Column(db.Boolean, default=False)

    problems = db.relationship('ContestProblem', backref='contest', cascade='all,delete-orphan')


class ContestProblem(db.Model):
    __tablename__ = 'contest_problems'
    id = db.Column(db.Integer, primary_key=True)
    contest_id = db.Column(db.Integer, db.ForeignKey('contests.id'), nullable=False)
    problem_id = db.Column(db.Integer, db.ForeignKey('problems.id'), nullable=False)
    problem = db.relationship('Problem')


class DistributionLog(db.Model):
    __tablename__ = 'distribution_logs'
    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    file_path = db.Column(db.String(300))
    problems = db.Column(db.Text)  # JSON list of problem ids
