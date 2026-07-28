from models.transcript import Course
from models.transcript import GRADE_POINTS
from services.parserPDF import parse_courses
from pathlib import Path

def calculate_cpa(courses: list[Course], up_to_semester: str | None = None) -> dict:
    filtered = [
        c for c in courses
        if c.credits > 0
        and c.letter_grade in GRADE_POINTS
        and (up_to_semester is None or c.semester <= up_to_semester)
    ]

    filtered.sort(key=lambda c: c.semester)

    best_by_code: dict[str, Course] = {}
    for course in filtered:
        existing = best_by_code.get(course.code)
        if existing is None or GRADE_POINTS[course.letter_grade] > GRADE_POINTS[existing.letter_grade]:
            best_by_code[course.code] = course

    counted = list(best_by_code.values())
    credits = sum(c.credits for c in counted)
    points = sum(c.credits * GRADE_POINTS[c.letter_grade] for c in counted)

    return {
        "up_to_semester": up_to_semester,
        "cpa": round(points / credits, 2) if credits else 0,
        "cumulative_credits": credits,
        "courses": [c.model_dump() for c in counted],
    }