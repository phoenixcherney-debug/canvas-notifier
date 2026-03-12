

# ─────────────────────────────────────────────

if **name** == “**main**”:
print(”=” * 55)
print(”  Canvas Grade Notifier”)
print(”=” * 55)

```
try:
    courses = get_active_courses()
except Exception as e:
    print(f"✗ Could not fetch Canvas courses: {e}")
    exit(1)

check_for_new_grades(courses)
check_for_new_assignments(courses)
print("\nDone.")
