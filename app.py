from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from models import db, User, Problem, TestCase, Submission, SubmissionResult, Contest, ContestProblem, DownloadLog, DistributionLog
from models import TestCase as TCModel
from judge import Judge
import io
import zipfile
import json
import sqlite3
from typing import Optional

BASE_DIR = os.path.dirname(__file__)
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-this-secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///'+os.path.join(BASE_DIR, 'oj.db')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
from functools import wraps


def admin_required(func):
    @wraps(func)
    @login_required
    def wrapper(*args, **kwargs):
        if not getattr(current_user, 'is_admin', False):
            abort(403)
        return func(*args, **kwargs)
    return wrapper

judge = Judge(app.config['UPLOAD_FOLDER'])


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


with app.app_context():
    db.create_all()
    # simple migration: add missing columns for sqlite
    db_path = os.path.join(BASE_DIR, 'oj.db')
    def has_column(table, column):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in cur.fetchall()]
            conn.close()
            return column in cols
        except Exception:
            return False

    def add_column(table, column_def):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
            conn.commit()
            conn.close()
        except Exception:
            pass

    if not has_column('users', 'is_admin'):
        add_column('users', "is_admin BOOLEAN DEFAULT 0")
    if not has_column('problems', 'deleted'):
        add_column('problems', "deleted BOOLEAN DEFAULT 0")
    if not has_column('problems', 'deleted_at'):
        add_column('problems', "deleted_at DATETIME")
    if not has_column('problems', 'input_format'):
        add_column('problems', "input_format TEXT")
    if not has_column('problems', 'output_format'):
        add_column('problems', "output_format TEXT")
    if not has_column('problems', 'samples'):
        add_column('problems', "samples TEXT")
    if not has_column('problems', 'data_range'):
        add_column('problems', "data_range TEXT")
    if not has_column('test_cases', 'deleted'):
        add_column('test_cases', "deleted BOOLEAN DEFAULT 0")
    if not has_column('test_cases', 'deleted_at'):
        add_column('test_cases', "deleted_at DATETIME")
    if not has_column('submissions', 'contest_id'):
        add_column('submissions', "contest_id INTEGER")
    if not has_column('contests', 'is_homework'):
        add_column('contests', "is_homework BOOLEAN DEFAULT 0")
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin')
        admin.set_password('admin')
        admin.is_admin = True
        db.session.add(admin)
        db.session.commit()

    # ensure distributed folder exists
    distributed_dir = os.path.join(BASE_DIR, 'distributed')
    os.makedirs(distributed_dir, exist_ok=True)


def load_announcement() -> Optional[dict]:
    cfg_dir = os.path.join(BASE_DIR, 'config')
    os.makedirs(cfg_dir, exist_ok=True)
    path = os.path.join(cfg_dir, 'announcement.json')
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # simple visibility and time window handling
                if not data.get('visible', True):
                    return None
                now = datetime.utcnow()
                start = None
                end = None
                if data.get('start_at'):
                    try:
                        start = datetime.fromisoformat(data.get('start_at'))
                    except Exception:
                        start = None
                if data.get('end_at'):
                    try:
                        end = datetime.fromisoformat(data.get('end_at'))
                    except Exception:
                        end = None
                if (start is None or start <= now) and (end is None or now <= end):
                    return data
    except Exception:
        return None
    return None


@app.context_processor
def inject_announcement():
    return {'announcement': load_announcement()}


@app.route('/admin/announcement', methods=['GET', 'POST'])
@admin_required
def admin_announcement():
    cfg_dir = os.path.join(BASE_DIR, 'config')
    os.makedirs(cfg_dir, exist_ok=True)
    path = os.path.join(cfg_dir, 'announcement.json')
    data = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}

    if request.method == 'POST':
        title = request.form.get('title', '')
        content = request.form.get('content', '')
        visible = bool(request.form.get('visible'))
        start_at = request.form.get('start_at') or None
        end_at = request.form.get('end_at') or None
        ann = {
            'id': data.get('id', str(int(datetime.utcnow().timestamp()))),
            'title': title,
            'content': content,
            'visible': visible,
            'start_at': start_at,
            'end_at': end_at
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(ann, f, ensure_ascii=False, indent=2)
            flash('公告已保存')
        except Exception:
            flash('保存公告失败')
        return redirect(url_for('admin_index'))

    return render_template('admin/announcement.html', ann=data)


@app.route('/')
def index():
    problems = Problem.query.all()
    contests = Contest.query.all()
    return render_template('index.html', problems=problems, contests=contests)


@app.route('/problem/<int:pid>')
def problem(pid):
    p = Problem.query.get_or_404(pid)
    tests = TestCase.query.filter_by(problem_id=pid).all()
    samples_obj = None
    if p.samples:
        try:
            samples_obj = json.loads(p.samples)
            # ensure it's a list of dicts with input/output
            if not isinstance(samples_obj, list):
                samples_obj = None
        except Exception:
            samples_obj = None
    return render_template('problem.html', problem=p, tests=tests, samples_obj=samples_obj)


@app.route('/submit/<int:pid>', methods=['GET', 'POST'])
@login_required
def submit(pid):
    p = Problem.query.get_or_404(pid)
    # 检查该题是否属于某个有时间限制的竞赛
    cps = ContestProblem.query.filter_by(problem_id=pid).all()
    now = datetime.utcnow()
    contests_with_times = []
    for cp in cps:
        c = Contest.query.get(cp.contest_id)
        if c and c.start_time and c.end_time:
            contests_with_times.append(c)

    if request.method == 'POST':
        # 如果题目属于至少一个有时间限制的竞赛，则只允许在至少一个竞赛的时间窗口内提交
        if contests_with_times:
            allowed = any((c.start_time <= now <= c.end_time) for c in contests_with_times)
            if not allowed:
                flash('该题当前不在允许的竞赛时间段内提交')
                return redirect(url_for('problem', pid=pid))

        lang = request.form['lang']
        code = request.files['code']
        filename = secure_filename(code.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        code.save(file_path)
        # 绑定提交到当前用户，如果处于某个竞赛且该竞赛处于时间窗口，记录 contest_id（选第一个活跃的）
        contest_id = None
        active_contests = [c for c in contests_with_times if c.start_time <= now <= c.end_time]
        if active_contests:
            contest_id = active_contests[0].id
        sub = Submission(problem_id=pid, language=lang, filename=filename, submit_time=datetime.utcnow(), user_id=current_user.id, contest_id=contest_id)
        db.session.add(sub)
        db.session.commit()
        results = judge.judge_submission(sub.id)
        flash('提交已评测')
        return redirect(url_for('submission', sid=sub.id))
    return render_template('submit.html', problem=p)


@app.route('/submission/<int:sid>')
def submission(sid):
    s = Submission.query.get_or_404(sid)
    results = SubmissionResult.query.filter_by(submission_id=sid).all()
    return render_template('submission.html', submission=s, results=results)


@app.route('/submissions')
def submissions():
    subs = Submission.query.order_by(Submission.submit_time.desc()).limit(100).all()
    return render_template('submissions.html', subs=subs)


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('admin_index'))
        flash('用户名或密码错误')
    return render_template('admin_login.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash('登录成功')
            return redirect(url_for('index'))
        flash('用户名或密码错误')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))
        u = User(username=username)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        login_user(u)
        flash('注册并已登录')
        return redirect(url_for('index'))
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已登出')
    return redirect(url_for('index'))


@app.route('/admin/logout')
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/admin')
@login_required
def admin_index():
    problems = Problem.query.filter_by(deleted=False).all()
    contests = Contest.query.all()
    stats = {
        'problems': len(problems),
        'contests': len(contests),
        'submissions': Submission.query.count()
    }
    return render_template('admin/index.html', problems=problems, contests=contests, stats=stats)


@app.route('/admin/distribute', methods=['GET', 'POST'])
@admin_required
def admin_distribute():
    problems = Problem.query.filter_by(deleted=False).all()
    logs = DistributionLog.query.order_by(DistributionLog.created_at.desc()).limit(50).all()
    if request.method == 'POST':
        ids = request.form.getlist('problem_ids')
        if not ids:
            flash('请选择至少一个题目')
            return redirect(url_for('admin_distribute'))
        # build zip
        fname = f'distributed_{int(datetime.utcnow().timestamp())}.zip'
        outpath = os.path.join(BASE_DIR, 'distributed', fname)
        with zipfile.ZipFile(outpath, 'w') as zf:
            # include inputs of all selected problems
            for pid in ids:
                p = Problem.query.get(int(pid))
                if not p:
                    continue
                tcs = TestCase.query.filter_by(problem_id=p.id, deleted=False).all()
                for idx, tc in enumerate(tcs, start=1):
                    arcname = f'problem_{p.id}_tc_{idx}_input.txt'
                    if getattr(tc, 'input_data', None):
                        zf.writestr(arcname, tc.input_data)
                    else:
                        path = os.path.join(app.config['UPLOAD_FOLDER'], tc.input_file)
                        if os.path.exists(path):
                            zf.write(path, arcname=arcname)
        # record log
        log = DistributionLog(admin_user_id=current_user.id, file_path=os.path.join('distributed', fname), problems=json.dumps(ids))
        db.session.add(log)
        db.session.commit()
        flash('分发包已生成')
        return redirect(url_for('admin_distribute'))
    return render_template('admin/distribute.html', problems=problems, logs=logs)

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/user/<int:uid>/toggle_admin', methods=['POST'])
@admin_required
def admin_toggle_user(uid):
    if current_user.id == uid:
        flash('不能修改自己的管理员权限')
        return redirect(url_for('admin_users'))
    u = User.query.get_or_404(uid)
    # prevent removing last admin
    if u.is_admin:
        admin_count = User.query.filter_by(is_admin=True).count()
        if admin_count <= 1:
            flash('至少需要一个管理员，无法取消最后一个管理员')
            return redirect(url_for('admin_users'))
    u.is_admin = not bool(u.is_admin)
    db.session.commit()
    flash('权限已更新')
    return redirect(url_for('admin_users'))


@app.route('/contests')
def contests():
    contests = Contest.query.order_by(Contest.start_time.desc()).all()
    return render_template('contests.html', contests=contests)


@app.route('/contest/<int:cid>')
def contest_view(cid):
    c = Contest.query.get_or_404(cid)
    cps = ContestProblem.query.filter_by(contest_id=cid).all()
    problems = Problem.query.all()
    return render_template('contest.html', contest=c, cps=cps, problems=problems)


@app.route('/contest/<int:cid>/rank')
def contest_rank(cid):
    c = Contest.query.get_or_404(cid)
    # collect users who have submissions in this contest
    subs = Submission.query.filter_by(contest_id=cid).all()
    user_ids = set(s.user_id for s in subs if s.user_id)
    problems = [cp.problem for cp in ContestProblem.query.filter_by(contest_id=cid).all()]

    # prepare best score per user per problem
    rank = []
    for uid in user_ids:
        total = 0
        details = []
        for p in problems:
            # find best score for this user and problem within contest
            best = 0
            user_subs = Submission.query.filter_by(contest_id=cid, problem_id=p.id, user_id=uid).all()
            for us in user_subs:
                for r in us.results:
                    if r.score and r.score > best:
                        best = r.score
            details.append(best)
            total += best
        rank.append({'user_id': uid, 'total': total, 'details': details})

    rank.sort(key=lambda x: x['total'], reverse=True)
    return render_template('contest_rank.html', contest=c, problems=problems, rank=rank)


@app.route('/admin/contest/new', methods=['GET', 'POST'])
@login_required
def admin_new_contest():
    if request.method == 'POST':
        title = request.form['title']
        mode = request.form.get('mode', 'IOI')
        is_hw = bool(request.form.get('is_homework'))
        start_raw = request.form.get('start_time') or None
        end_raw = request.form.get('end_time') or None
        start = None
        end = None
        try:
            if start_raw:
                start = datetime.fromisoformat(start_raw)
            if end_raw:
                end = datetime.fromisoformat(end_raw)
        except Exception:
            start = None
            end = None
        c = Contest(title=title, mode=mode, is_homework=is_hw, start_time=start, end_time=end)
        db.session.add(c)
        db.session.commit()
        flash('竞赛已创建')
        return redirect(url_for('admin_index'))
    return render_template('admin/new_contest.html')



@app.route('/admin/contest/<int:cid>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_contest(cid):
    c = Contest.query.get_or_404(cid)
    if request.method == 'POST':
        c.title = request.form['title']
        c.mode = request.form.get('mode', c.mode)
        c.is_homework = bool(request.form.get('is_homework'))
        start_raw = request.form.get('start_time') or None
        end_raw = request.form.get('end_time') or None
        try:
            c.start_time = datetime.fromisoformat(start_raw) if start_raw else None
            c.end_time = datetime.fromisoformat(end_raw) if end_raw else None
        except Exception:
            pass
        db.session.commit()
        flash('竞赛已更新')
        return redirect(url_for('admin_index'))
    return render_template('admin/edit_contest.html', c=c)


@app.route('/admin/contest/<int:cid>/delete', methods=['POST'])
@login_required
def admin_delete_contest(cid):
    c = Contest.query.get_or_404(cid)
    # 删除相关 ContestProblem
    for cp in ContestProblem.query.filter_by(contest_id=cid).all():
        db.session.delete(cp)
    db.session.delete(c)
    db.session.commit()
    flash('竞赛已删除')
    return redirect(url_for('admin_index'))


@app.route('/admin/contest/<int:cid>/remove_problem/<int:pid>', methods=['POST'])
@login_required
def admin_remove_problem_from_contest(cid, pid):
    cp = ContestProblem.query.filter_by(contest_id=cid, problem_id=pid).first()
    if cp:
        db.session.delete(cp)
        db.session.commit()
        flash('已从竞赛移除题目')
    return redirect(url_for('contest_view', cid=cid))


@app.route('/admin/recycle')
@admin_required
def admin_recycle():
    problems = Problem.query.filter_by(deleted=True).all()
    testcases = TCModel.query.filter_by(deleted=True).all()
    return render_template('admin/recycle.html', problems=problems, testcases=testcases)


@app.route('/admin/recycle/restore/problem/<int:pid>', methods=['POST'])
@admin_required
def admin_restore_problem(pid):
    p = Problem.query.get_or_404(pid)
    p.deleted = False
    p.deleted_at = None
    db.session.commit()
    flash('题目已恢复')
    return redirect(url_for('admin_recycle'))


@app.route('/admin/recycle/restore/testcase/<int:tid>', methods=['POST'])
@admin_required
def admin_restore_testcase(tid):
    tc = TCModel.query.get_or_404(tid)
    tc.deleted = False
    tc.deleted_at = None
    db.session.commit()
    flash('测试点已恢复')
    return redirect(url_for('admin_recycle'))


@app.route('/admin/recycle/delete/problem/<int:pid>', methods=['POST'])
@admin_required
def admin_permanent_delete_problem(pid):
    p = Problem.query.get_or_404(pid)
    # delete related test files
    for tc in p.testcases:
        try:
            inpath = os.path.join(app.config['UPLOAD_FOLDER'], tc.input_file)
            outpath = os.path.join(app.config['UPLOAD_FOLDER'], tc.output_file)
            if os.path.exists(inpath):
                os.remove(inpath)
            if os.path.exists(outpath):
                os.remove(outpath)
        except Exception:
            pass
    db.session.delete(p)
    db.session.commit()
    flash('题目已永久删除')
    return redirect(url_for('admin_recycle'))


@app.route('/admin/recycle/delete/testcase/<int:tid>', methods=['POST'])
@admin_required
def admin_permanent_delete_testcase(tid):
    tc = TCModel.query.get_or_404(tid)
    try:
        inpath = os.path.join(app.config['UPLOAD_FOLDER'], tc.input_file)
        outpath = os.path.join(app.config['UPLOAD_FOLDER'], tc.output_file)
        if os.path.exists(inpath):
            os.remove(inpath)
        if os.path.exists(outpath):
            os.remove(outpath)
    except Exception:
        pass
    db.session.delete(tc)
    db.session.commit()
    flash('测试点已永久删除')
    return redirect(url_for('admin_recycle'))


@app.route('/admin/import_export')
@admin_required
def admin_import_export():
    return render_template('admin/import_export.html')


@app.route('/admin/export')
@admin_required
def admin_export():
    # Build JSON description
    data = {'problems': []}
    problems = Problem.query.all()
    for p in problems:
        item = {'id': p.id, 'title': p.title, 'statement': p.statement}
        item['input_format'] = p.input_format
        item['output_format'] = p.output_format
        item['samples'] = p.samples
        item['data_range'] = p.data_range
        tcs = []
        for tc in p.testcases:
            tcs.append({'id': tc.id, 'input_file': tc.input_file, 'output_file': tc.output_file, 'score': tc.score})
        item['testcases'] = tcs
        data['problems'].append(item)

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w') as zf:
        zf.writestr('export.json', json.dumps(data, ensure_ascii=False))
        # add test files
        for p in problems:
            for tc in p.testcases:
                for fname in [tc.input_file, tc.output_file]:
                    path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                    if os.path.exists(path):
                        zf.write(path, arcname=os.path.join('files', fname))
    mem.seek(0)
    return send_file(mem, download_name='export.zip', as_attachment=True)


@app.route('/admin/import', methods=['POST'])
@admin_required
def admin_import():
    f = request.files.get('zipfile')
    if not f:
        flash('未上传文件')
        return redirect(url_for('admin_import_export'))
    mem = io.BytesIO(f.read())
    try:
        with zipfile.ZipFile(mem) as zf:
            json_bytes = zf.read('export.json')
            data = json.loads(json_bytes.decode('utf-8'))
            # extract files to upload folder
            for name in zf.namelist():
                if name.startswith('files/'):
                    fname = os.path.basename(name)
                    zf.extract(name, app.config['UPLOAD_FOLDER'])
                    # extracted path will be uploads/files/<fname>, move to uploads/<fname>
                    src = os.path.join(app.config['UPLOAD_FOLDER'], name)
                    dst = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                    os.replace(src, dst)
            # create problems and testcases
            for p in data.get('problems', []):
                prob = Problem(title=p.get('title',''), statement=p.get('statement',''), input_format=p.get('input_format'), output_format=p.get('output_format'), samples=p.get('samples'), data_range=p.get('data_range'))
                db.session.add(prob)
                db.session.flush()
                for tc in p.get('testcases', []):
                    in_name = tc.get('input_file')
                    out_name = tc.get('output_file')
                    score = tc.get('score', 100)
                    newtc = TCModel(problem_id=prob.id, input_file=in_name, output_file=out_name, score=score)
                    db.session.add(newtc)
            db.session.commit()
    except Exception as e:
        flash('导入失败: ' + str(e))
        return redirect(url_for('admin_import_export'))
    flash('导入完成')
    return redirect(url_for('admin_index'))


@app.route('/admin/contest/<int:cid>/add_problem', methods=['POST'])
@login_required
def admin_add_problem_to_contest(cid):
    pid = int(request.form['problem_id'])
    cp = ContestProblem(contest_id=cid, problem_id=pid)
    db.session.add(cp)
    db.session.commit()
    flash('题目已加入竞赛')
    return redirect(url_for('contest_view', cid=cid))


@app.route('/me')
@login_required
def me():
    return redirect(url_for('user_profile', uid=current_user.id))


@app.route('/user/<int:uid>')
def user_profile(uid):
    user = User.query.get_or_404(uid)
    subs = Submission.query.filter_by(user_id=uid).order_by(Submission.submit_time.desc()).all()
    return render_template('user_profile.html', user=user, submissions=subs)


@app.route('/admin/problem/new', methods=['GET', 'POST'])
@admin_required
def admin_new_problem():
    if request.method == 'POST':
        title = request.form['title']
        statement = request.form['statement']
        input_format = request.form.get('input_format')
        output_format = request.form.get('output_format')
        # samples can be provided as JSON in textarea or uploaded as a .json file
        samples = request.form.get('samples_json')
        samples_file = request.files.get('samples_file')
        if samples_file and samples_file.filename:
            try:
                samples = samples_file.read().decode('utf-8')
            except Exception:
                samples = None
        data_range = request.form.get('data_range')
        p = Problem(title=title, statement=statement, input_format=input_format, output_format=output_format, samples=samples, data_range=data_range)
        db.session.add(p)
        db.session.commit()
        flash('题目已创建')
        return redirect(url_for('admin_index'))
    return render_template('admin/new_problem.html')


@app.route('/admin/problem/<int:pid>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_problem(pid):
    p = Problem.query.get_or_404(pid)
    if request.method == 'POST':
        p.title = request.form['title']
        p.statement = request.form['statement']
        p.input_format = request.form.get('input_format')
        p.output_format = request.form.get('output_format')
        # accept JSON samples from textarea or uploaded file
        samples = request.form.get('samples_json')
        samples_file = request.files.get('samples_file')
        if samples_file and samples_file.filename:
            try:
                samples = samples_file.read().decode('utf-8')
            except Exception:
                samples = None
        p.samples = samples
        p.data_range = request.form.get('data_range')
        db.session.commit()
        flash('题目已更新')
        return redirect(url_for('admin_index'))
    return render_template('admin/edit_problem.html', p=p)


@app.route('/admin/problem/<int:pid>/delete', methods=['POST'])
@admin_required
def admin_delete_problem(pid):
    p = Problem.query.get_or_404(pid)
    p.deleted = True
    p.deleted_at = datetime.utcnow()
    db.session.commit()
    flash('题目已移入回收站')
    return redirect(url_for('admin_index'))


@app.route('/admin/problem/<int:pid>/testcase/new', methods=['GET', 'POST'])
@admin_required
def admin_new_testcase(pid):
    p = Problem.query.get_or_404(pid)
    if request.method == 'POST':
        infile = request.files['input']
        outfile = request.files['output']
        score = int(request.form.get('score', '100'))
        in_name = secure_filename(infile.filename)
        out_name = secure_filename(outfile.filename)
        infile.save(os.path.join(app.config['UPLOAD_FOLDER'], in_name))
        outfile.save(os.path.join(app.config['UPLOAD_FOLDER'], out_name))
        tc = TestCase(problem_id=pid, input_file=in_name, output_file=out_name, score=score)
        db.session.add(tc)
        db.session.commit()
        flash('测试点已上传')
        return redirect(url_for('problem', pid=pid))
    return render_template('admin/new_testcase.html', p=p)


@app.route('/admin/testcase/<int:tid>/delete', methods=['POST'])
@admin_required
def admin_delete_testcase(tid):
    tc = TCModel.query.get_or_404(tid)
    # 删除文件
    inpath = os.path.join(app.config['UPLOAD_FOLDER'], tc.input_file)
    outpath = os.path.join(app.config['UPLOAD_FOLDER'], tc.output_file)
    try:
        if os.path.exists(inpath):
            os.remove(inpath)
        if os.path.exists(outpath):
            os.remove(outpath)
    except Exception:
        pass
    pid = tc.problem_id
    tc.deleted = True
    tc.deleted_at = datetime.utcnow()
    db.session.commit()
    flash('测试点已移入回收站')
    return redirect(url_for('admin_edit_problem', pid=pid))


@app.route('/problem/<int:pid>/testcases')
@login_required
def testcase_info(pid):
    p = Problem.query.get_or_404(pid)
    tcs = TestCase.query.filter_by(problem_id=pid, deleted=False).all()
    downloads = DownloadLog.query.filter_by(user_id=current_user.id, problem_id=pid).first()
    tc_info = []
    for tc in tcs:
        path = os.path.join(app.config['UPLOAD_FOLDER'], tc.input_file)
        size_kb = None
        if os.path.exists(path):
            size_kb = round(os.path.getsize(path) / 1024, 2)
        tc_info.append({'id': tc.id, 'score': tc.score, 'input_file': tc.input_file, 'size_kb': size_kb})
    return render_template('testcases.html', problem=p, testcases=tc_info, downloaded=bool(downloads), total_score=sum(tc.score for tc in tcs), count=len(tcs))


@app.route('/download/problem/<int:pid>')
@login_required
def download_problem_testcases(pid):
    p = Problem.query.get_or_404(pid)
    existing = DownloadLog.query.filter_by(user_id=current_user.id, problem_id=pid).first()
    if existing:
        flash('每用户每道题只能下载一次测试点')
        return redirect(url_for('testcase_info', pid=pid))
    tcs = TestCase.query.filter_by(problem_id=pid, deleted=False).all()
    if not tcs:
        flash('该题暂无测试点可下载')
        return redirect(url_for('testcase_info', pid=pid))
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w') as zf:
        for tc in tcs:
            path = os.path.join(app.config['UPLOAD_FOLDER'], tc.input_file)
            if os.path.exists(path):
                zf.write(path, arcname=os.path.basename(tc.input_file))
    mem.seek(0)
    log = DownloadLog(user_id=current_user.id, problem_id=pid)
    db.session.add(log)
    db.session.commit()
    return send_file(mem, download_name=f'problem_{pid}_inputs.zip', as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True)
