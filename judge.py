import os
import subprocess
import shutil
import time
from models import Submission, SubmissionResult, TestCase, db

def docker_available():
    try:
        subprocess.run(['docker', '--version'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


class Judge:
    def __init__(self, upload_folder):
        self.upload_folder = upload_folder
        self.use_docker = docker_available()

    def judge_submission(self, submission_id):
        sub = Submission.query.get(submission_id)
        if not sub:
            return None
        filepath = os.path.join(self.upload_folder, sub.filename)
        lang = sub.language.lower()
        workdir = os.path.join(self.upload_folder, f'sub_{submission_id}')
        os.makedirs(workdir, exist_ok=True)
        # copy source
        src = os.path.join(workdir, sub.filename)
        shutil.copy(filepath, src)

        exe = None
        compile_ok = True
        compile_msg = ''
        if lang == 'cpp' or lang == 'c++':
            exe = os.path.join(workdir, 'a.out')
            try:
                if self.use_docker:
                    # compile inside gcc container
                    cmd = f"docker run --rm -v \"{workdir}:/work\" -w /work gcc:12 bash -lc \"g++ {sub.filename} -O2 -std=c++17 -o a.out\""
                    subprocess.run(cmd, shell=True, check=True, timeout=60)
                else:
                    subprocess.run(['g++', src, '-O2', '-std=c++17', '-o', exe], check=True, capture_output=True, timeout=30)
            except subprocess.CalledProcessError as e:
                compile_ok = False
                compile_msg = e.stderr.decode(errors='ignore')
        elif lang == 'java':
            try:
                if self.use_docker:
                    cmd = f"docker run --rm -v \"{workdir}:/work\" -w /work openjdk:17 bash -lc \"javac {sub.filename}\""
                    subprocess.run(cmd, shell=True, check=True, timeout=60)
                    exe = ['java', os.path.splitext(sub.filename)[0]]
                else:
                    subprocess.run(['javac', src], check=True, capture_output=True, timeout=30, cwd=workdir)
                    exe = ['java', os.path.splitext(sub.filename)[0]]
            except subprocess.CalledProcessError as e:
                compile_ok = False
                compile_msg = e.stderr.decode(errors='ignore')
        elif lang == 'python' or lang == 'py':
            exe = ['python', src]
        else:
            compile_ok = False
            compile_msg = 'Unsupported language'

        testcases = TestCase.query.filter_by(problem_id=sub.problem_id).all()
        results = []
        total_score = 0

        if not compile_ok:
            # record a single compile-fail result
            r = SubmissionResult(submission_id=sub.id, testcase_id=None, status='CE', time_ms=0, memory_kb=0, score=0)
            db.session.add(r)
            db.session.commit()
            return [{'status': 'CE', 'message': compile_msg}]

        for tc in testcases:
            in_path = os.path.join(self.upload_folder, tc.input_file)
            expected_path = os.path.join(self.upload_folder, tc.output_file)
            start = time.time()
            try:
                if self.use_docker:
                    # run each test in a fresh container for better isolation
                    if lang in ('cpp', 'c++'):
                        # execute compiled a.out inside gcc image
                        run_cmd = f"docker run --rm -v \"{workdir}:/work\" -w /work gcc:12 bash -lc \"timeout 5s ./a.out < /work/{os.path.basename(in_path)}\""
                        subprocess.run(run_cmd, shell=True, check=True, timeout=10, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        # read output from file if produced
                        # instead capture stdout directly
                        proc = subprocess.run(run_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                        out = proc.stdout.decode(errors='ignore')
                    elif lang == 'java':
                        run_cmd = f"docker run --rm -v \"{workdir}:/work\" -w /work openjdk:17 bash -lc \"timeout 5s java {os.path.splitext(sub.filename)[0]} < /work/{os.path.basename(in_path)}\""
                        proc = subprocess.run(run_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                        out = proc.stdout.decode(errors='ignore')
                    else:
                        # python
                        run_cmd = f"docker run --rm -v \"{workdir}:/work\" -w /work python:3.11-slim bash -lc \"timeout 5s python {sub.filename} < /work/{os.path.basename(in_path)}\""
                        proc = subprocess.run(run_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                        out = proc.stdout.decode(errors='ignore')
                    elapsed = time.time() - start
                else:
                    if isinstance(exe, list):
                        proc = subprocess.run(exe, stdin=open(in_path, 'rb'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, cwd=workdir)
                    else:
                        proc = subprocess.run([exe], stdin=open(in_path, 'rb'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, cwd=workdir)
                    elapsed = time.time() - start
                    out = proc.stdout.decode(errors='ignore')

                with open(expected_path, 'r', encoding='utf-8', errors='ignore') as f:
                    expected = f.read()
                # simple normalization
                if out.strip() == expected.strip():
                    status = 'AC'
                    score = tc.score
                else:
                    status = 'WA'
                    score = 0
            except subprocess.TimeoutExpired:
                elapsed = time.time() - start
                status = 'TLE'
                score = 0
            except subprocess.CalledProcessError:
                elapsed = time.time() - start
                status = 'RE'
                score = 0
            except Exception as e:
                elapsed = time.time() - start
                status = 'RE'
                score = 0

            total_score += score
            r = SubmissionResult(submission_id=sub.id, testcase_id=tc.id, status=status, time_ms=int(elapsed*1000), memory_kb=0, score=score)
            db.session.add(r)
            db.session.commit()
            results.append({'tc': tc.id, 'status': status, 'time_ms': int(elapsed*1000), 'score': score})

        return results
