"""
Canvas Grade Notifier — iPhone Push Notifications via ntfy.sh
=============================================================
Designed to run on GitHub Actions (free, always-on, no computer needed).

How to get your Canvas API Token:
  1. Log into Canvas → Account (top-left avatar) → Settings
  2. Scroll to "Approved Integrations" → click "+ New Access Token"
  3. Give it a name like "Grade Notifier" and copy the token

How to get your ntfy topic:
  1. Install the free "ntfy" app on your iPhone from the App Store
  2. Tap + and subscribe to a unique topic name e.g. "phoenix123-canvas-8472"
"""

import requests
import json
import os
from datetime import datetime

# ─────────────────────────────────────────────
#  Config — loaded from environment variables
#  (set these as GitHub Actions secrets)
# ─────────────────────────────────────────────

CANVAS_URL            = os.environ["CANVAS_URL"].strip()
CANVAS_API_TOKEN      = os.environ["CANVAS_API_TOKEN"].strip()
NTFY_TOPIC            = os.environ["NTFY_TOPIC"].strip()
SEEN_GRADES_FILE      = "seen_grades.json"
SEEN_ASSIGNMENTS_FILE = "seen_assignments.json"


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def get_headers():
    return {"Authorization": f"Bearer {CANVAS_API_TOKEN}"}


def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return json.load(f)
    return {}


def save_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def send_notification(title, message, priority="default"):
    """Send a push notification to iPhone via ntfy.sh."""
    try:
        response = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": "mortar_board",
            }
        )
        return response.status_code == 200
    except Exception as e:
        print(f"  ✗ Notification error: {e}")
        return False


def format_due_date(due_at_str):
    if not due_at_str:
        return "No due date"
    try:
        dt = datetime.strptime(due_at_str, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%a %b %-d at %-I:%M %p") + " UTC"
    except Exception:
        return due_at_str


# ─────────────────────────────────────────────
#  Canvas API
# ─────────────────────────────────────────────

def get_active_courses():
    url = f"{CANVAS_URL}/api/v1/courses"
    params = {"enrollment_state": "active", "per_page": 50}
    response = requests.get(url, headers=get_headers(), params=params)
    response.raise_for_status()
    return response.json()


def get_course_grade(course_id):
    url = f"{CANVAS_URL}/api/v1/courses/{course_id}/enrollments"
    params = {"type[]": "StudentEnrollment", "state[]": "active"}
    response = requests.get(url, headers=get_headers(), params=params)
    if response.status_code != 200:
        return None, None
    enrollments = response.json()
    if not enrollments:
        return None, None
    grades = enrollments[0].get("grades", {})
    return grades.get("current_score"), grades.get("current_grade")


def get_graded_submissions(course_id):
    url = f"{CANVAS_URL}/api/v1/courses/{course_id}/students/submissions"
    params = {
        "student_ids[]": "self",
        "workflow_state": "graded",
        "include[]": ["assignment", "submission_comments"],
        "per_page": 50,
    }
    response = requests.get(url, headers=get_headers(), params=params)
    if response.status_code == 401:
        raise Exception("Invalid Canvas API token.")
    if response.status_code != 200:
        return []
    return response.json()


def get_assignments(course_id):
    url = f"{CANVAS_URL}/api/v1/courses/{course_id}/assignments"
    params = {"per_page": 50, "order_by": "due_at"}
    response = requests.get(url, headers=get_headers(), params=params)
    if response.status_code != 200:
        return []
    return response.json()


# ─────────────────────────────────────────────
#  Grade checker
# ─────────────────────────────────────────────

def check_for_new_grades(courses):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for new grades...")
    seen = load_json(SEEN_GRADES_FILE)
    found = 0

    for course in courses:
        course_id   = str(course.get("id"))
        course_name = course.get("name", "Unknown Course")

        try:
            submissions = get_graded_submissions(course_id)
        except Exception as e:
            print(f"  ✗ Skipping {course_name}: {e}")
            continue

        course_score, course_grade = get_course_grade(course_id)
        if course_score is not None and course_grade:
            overall_str = f"{course_score}% ({course_grade})"
        elif course_score is not None:
            overall_str = f"{course_score}%"
        elif course_grade:
            overall_str = course_grade
        else:
            overall_str = "N/A"

        for submission in submissions:
            submission_id   = str(submission.get("id"))
            assignment      = submission.get("assignment", {})
            assignment_name = assignment.get("name", "Unknown Assignment")
            score           = submission.get("score")
            points_possible = assignment.get("points_possible")
            grade           = submission.get("grade", "N/A")
            key             = f"{course_id}_{submission_id}"

            raw_comments = submission.get("submission_comments", [])
            comment_lines = [
                f"{c['author']['display_name']}: {c['comment'].strip()}"
                for c in raw_comments
                if c.get("comment", "").strip()
                and c.get("author", {}).get("id") != submission.get("user_id")
            ]

            stored               = seen.get(key)
            stored_comment_count = stored.get("comment_count", 0) if stored else 0
            is_new_grade         = key not in seen
            has_new_comments     = len(comment_lines) > stored_comment_count

            if is_new_grade or has_new_comments:
                seen[key] = {
                    "assignment": assignment_name,
                    "course": course_name,
                    "grade": grade,
                    "comment_count": len(comment_lines),
                    "notified_at": datetime.now().isoformat(),
                }

                score_str = f"{score}/{points_possible} ({grade})" if score is not None and points_possible else str(grade)

                message_parts = [
                    f"Assignment: {score_str}",
                    f"Course grade: {overall_str}",
                ]
                if comment_lines:
                    message_parts.append("")
                    message_parts.append("Instructor comments:")
                    message_parts.extend(f"  {line}" for line in comment_lines)

                if send_notification(
                    title=f"Grade Posted: {course_name}",
                    message=f"{assignment_name}\n" + "\n".join(message_parts),
                    priority="high"
                ):
                    print(f"  ✓ Notified: [{course_name}] {assignment_name} → {score_str}")
                    found += 1

    save_json(SEEN_GRADES_FILE, seen)
    print(f"  → {found} new grade(s) found." if found else "  → No new grades.")


# ─────────────────────────────────────────────
#  Assignment checker
# ─────────────────────────────────────────────

def check_for_new_assignments(courses):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for new/updated assignments...")
    seen = load_json(SEEN_ASSIGNMENTS_FILE)
    found = 0

    for course in courses:
        course_id   = str(course.get("id"))
        course_name = course.get("name", "Unknown Course")

        for assignment in get_assignments(course_id):
            assignment_id   = str(assignment.get("id"))
            assignment_name = assignment.get("name", "Unknown Assignment")
            due_at          = assignment.get("due_at")
            points_possible = assignment.get("points_possible")
            key             = f"{course_id}_{assignment_id}"
            due_str         = format_due_date(due_at)
            points_str      = f"{int(points_possible)} pts" if points_possible else "ungraded"

            if key not in seen:
                seen[key] = {
                    "name": assignment_name,
                    "course": course_name,
                    "due_at": due_at,
                    "first_seen": datetime.now().isoformat(),
                }
                if send_notification(
                    title=f"New Assignment: {course_name}",
                    message=f"{assignment_name}\nDue: {due_str}\nWorth: {points_str}",
                    priority="default"
                ):
                    print(f"  ✓ New assignment: [{course_name}] {assignment_name}")
                    found += 1

            else:
                stored_due = seen[key].get("due_at")
                if due_at != stored_due:
                    old_due_str                 = format_due_date(stored_due)
                    seen[key]["due_at"]         = due_at
                    seen[key]["due_changed_at"] = datetime.now().isoformat()

                    if send_notification(
                        title=f"Deadline Changed: {course_name}",
                        message=f"{assignment_name}\nOld due: {old_due_str}\nNew due: {due_str}",
                        priority="high"
                    ):
                        print(f"  ✓ Deadline changed: [{course_name}] {assignment_name}")
                        found += 1

    save_json(SEEN_ASSIGNMENTS_FILE, seen)
    print(f"  → {found} assignment notification(s) sent." if found else "  → No new assignments or changes.")


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  Canvas Grade Notifier")
    print("=" * 55)

    try:
        courses = get_active_courses()
    except Exception as e:
        print(f"✗ Could not fetch Canvas courses: {e}")
        exit(1)

    check_for_new_grades(courses)
    check_for_new_assignments(courses)
    print("\nDone.")
