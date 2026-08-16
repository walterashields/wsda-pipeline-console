"""
Render triggering: runs automation/metabase_driver.py then
narration/audit_narrator.py in the sibling wsda-video-engine repo as
subprocesses, in a background thread, with output streamed line-by-line
into an in-memory job log the UI polls -- same simple thread+dict pattern
wsda-video-engine's own studio.py already uses for its production jobs,
reused here rather than reinvented (see run_production/jobs in that
file), just factored into its own module.

Progress granularity is honest about a real limit, not overclaimed:
narration/audit_narrator.py prints per-clip synthesis progress as it
runs (streamed live here), but automation/metabase_driver.py itself only
prints three summary lines at the very end of a recording -- it has no
per-event progress output today. This module does not modify that
sibling-repo file to add it; deliberately out of scope for a UI-only
build. The recording phase's live signal here is genuinely just "still
running, N seconds elapsed," not per-event detail -- shown as such in
the UI, not disguised as more granular than it is.
"""

import subprocess
import threading
import time
import uuid
from pathlib import Path

from console.paths import AUDIT_NARRATOR, METABASE_DRIVER, OUTPUT_DIR, WSDA_VIDEO_ENGINE

JOBS = {}
_LOCK = threading.Lock()


def _new_job(slug: str, video_id: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    with _LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "slug": slug,
            "video_id": video_id,
            "status": "running",
            "phase": "recording",
            "log": [],
            "started_at": time.time(),
            "finished_at": None,
            "result": {},
            "error": None,
        }
    return job_id


def _append_log(job_id: str, line: str) -> None:
    with _LOCK:
        JOBS[job_id]["log"].append(line)


def _stream_subprocess(job_id: str, cmd: list) -> tuple:
    """Runs cmd with output streamed into the job's log as it's produced,
    not buffered until exit -- so a poller sees real progress during a
    multi-minute run, not silence followed by a wall of text at the end.
    Returns this call's OWN new lines only (not the job's whole
    accumulated log) -- returning the shared, ever-growing log here was a
    real bug (see _render_narration_with_retry's docstring): code that
    scanned "the returned log" for a signal was actually scanning every
    earlier phase's output too, not just this command's."""
    _append_log(job_id, f"$ {' '.join(cmd)}")
    start_index = len(JOBS[job_id]["log"])
    proc = subprocess.Popen(
        cmd, cwd=str(WSDA_VIDEO_ENGINE),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    for line in proc.stdout:
        _append_log(job_id, line.rstrip("\n"))
    proc.wait()
    return proc.returncode, JOBS[job_id]["log"][start_index:]


# narration/audit_narrator.py's own QA step (narration/qa.py's --fix) can
# rewrite a script's pause durations in place. Confirmed live (2026-08-15)
# that whether it then stops short of rendering (the "critical" case,
# genuinely needs a re-record) or still renders successfully anyway (the
# "minor, <5s" case, printed as a warning but not blocking) BOTH print
# the identical "Re-run recording to apply changes" line from
# narration/qa.py's own --fix output -- that string is qa.py saying "I
# changed something," not audit_narrator.py saying "I didn't render."
# An earlier version of this function pattern-matched that string as its
# retry signal and got a real, live false positive from it: a genuinely
# successful first attempt (real Complete panel, real audio, a real
# _FINAL.mp4 on disk) still triggered a needless re-record, which then
# cascaded into new timing mismatches against the freshly re-recorded
# video and burned all retries on a render that never needed retrying at
# all. Fixed by checking the one signal that's actually authoritative:
# does the claimed output file exist on disk after this attempt -- same
# discipline as QA_CHECKLIST.md item 9 (verify real state, not a log
# message or exit code).
MAX_NARRATION_ATTEMPTS = 3


def _render_narration_with_retry(job_id: str, mp4_path: str, audit_path: str, script_path: Path):
    for attempt in range(1, MAX_NARRATION_ATTEMPTS + 1):
        if attempt > 1:
            _append_log(job_id, f"--- narration attempt {attempt}: re-recording against auto-fixed pause durations ---")
            code, log = _stream_subprocess(
                job_id, ["python3", str(METABASE_DRIVER), str(script_path), "--output-dir", str(OUTPUT_DIR)]
            )
            if code != 0:
                _append_log(job_id, f"re-record attempt {attempt} failed (driver exited {code}), stopping retries")
                return None
            for line in log:
                if line.startswith("[metabase_driver] recorded "):
                    mp4_path = line.removeprefix("[metabase_driver] recorded ").strip()
                elif line.startswith("[metabase_driver] audit log "):
                    audit_path = line.removeprefix("[metabase_driver] audit log ").strip()
            JOBS[job_id]["result"]["mp4"] = mp4_path
            JOBS[job_id]["result"]["audit_json"] = audit_path

        final_mp4 = str(Path(mp4_path).with_name(Path(mp4_path).stem + "_FINAL.mp4"))
        _stream_subprocess(
            job_id,
            ["python3", str(AUDIT_NARRATOR), mp4_path, audit_path, str(script_path),
             "--elevenlabs", "--output", final_mp4],
        )
        if Path(final_mp4).exists():
            return final_mp4

        _append_log(job_id, f"no final video produced on attempt {attempt}/{MAX_NARRATION_ATTEMPTS} "
                             f"(narration/qa.py likely hit a blocking timing issue and auto-fixed the "
                             f"script's pause durations in place -- retrying against the fix)")

    return None


def _run(job_id: str, script_path: Path):
    from console import projects  # deferred: avoid a circular import at module load

    job = JOBS[job_id]
    slug, video_id = job["slug"], job["video_id"]

    def set_video_status(**fields):
        project = projects.load_project(slug)
        if project:
            project.update_video(video_id, **fields)
            projects.save_project(project)

    try:
        job["phase"] = "recording"
        set_video_status(status="rendering", job_id=job_id)
        code, log = _stream_subprocess(
            job_id, ["python3", str(METABASE_DRIVER), str(script_path), "--output-dir", str(OUTPUT_DIR)]
        )
        if code != 0:
            raise RuntimeError(f"metabase_driver.py exited {code}, see log")

        mp4_path = audit_path = None
        events_succeeded = None
        for line in log:
            if line.startswith("[metabase_driver] recorded "):
                mp4_path = line.removeprefix("[metabase_driver] recorded ").strip()
            elif line.startswith("[metabase_driver] audit log "):
                audit_path = line.removeprefix("[metabase_driver] audit log ").strip()
            elif line.startswith("[metabase_driver] ") and "events succeeded" in line:
                events_succeeded = line.removeprefix("[metabase_driver] ").strip()
        if not mp4_path or not audit_path:
            raise RuntimeError("could not find recorded mp4/audit paths in metabase_driver.py output")

        job["result"]["mp4"] = mp4_path
        job["result"]["audit_json"] = audit_path
        job["result"]["events_succeeded"] = events_succeeded
        # Recording an event failure (e.g. a locator that didn't resolve)
        # is not itself a hard driver failure -- run_lesson() by design
        # keeps going and writes a full audit log either way, the same
        # way every prior QA pass on this project has treated a clean
        # exit code as necessary but not sufficient. Surfaced here, not
        # hidden, rather than raised as an exception: a generated script
        # this happens on is exactly the kind of thing the review step
        # exists to catch before a real render is trusted.
        if events_succeeded and "/" in events_succeeded.split()[0]:
            done, total = events_succeeded.split()[0].split("/")
            if done != total:
                _append_log(job_id, f"WARNING: only {events_succeeded} -- one or more locators in this "
                                     f"script did not resolve against the live app. Review before trusting this render.")

        job["phase"] = "narrating"
        final_mp4 = _render_narration_with_retry(job_id, mp4_path, audit_path, script_path)

        # Never report success on a claimed output file that isn't
        # actually there -- confirmed real, live gap this exact check
        # exists to catch (2026-08-15): audit_narrator.py's own CLI
        # returns exit code 0 even when it stops short of rendering,
        # after its QA step auto-fixes pause durations and asks for a
        # re-record. Checking the real filesystem, not the exit code,
        # is the only check this project's own history has repeatedly
        # shown actually catches that class of bug.
        if not final_mp4 or not Path(final_mp4).exists():
            raise RuntimeError(
                "audit_narrator.py did not produce a final video after "
                f"{MAX_NARRATION_ATTEMPTS} attempt(s) -- see log. This can mean the "
                "narration is structurally too long for this pause budget even after "
                "auto-fixing timings (the log will say so explicitly); the script "
                "likely needs shortening, not another retry."
            )

        job["result"]["final_mp4"] = final_mp4
        job["status"] = "done"
        set_video_status(status="rendered", render=job["result"])
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        set_video_status(status="render_failed", render=job.get("result", {}), notes=str(exc))
    finally:
        job["finished_at"] = time.time()


def start_render(project, video_id: str) -> str:
    script_path = project.script_path(video_id)
    if not script_path.exists():
        raise RuntimeError(f"no lesson_script.yml for {video_id} yet -- generate or write one first")

    job_id = _new_job(project.slug, video_id)
    thread = threading.Thread(target=_run, args=(job_id, script_path), daemon=True)
    thread.start()
    return job_id


def get_job(job_id: str) -> dict:
    return JOBS.get(job_id)
