from models.transcript import Course
from models.transcript import GRADE_POINTS
from services.parserPDF import parse_courses
from pathlib import Path

def calculate_gpa(courses: list[Course], semester: str) -> dict:
    selected = [
        c for c in courses
        if c.semester == semester and c.credits > 0 and c.letter_grade in GRADE_POINTS
    ]

    credits = sum(c.credits for c in selected)
    points = sum(c.credits * GRADE_POINTS[c.letter_grade] for c in selected)

    return {
        "semester": semester,
        "gpa": round(points / credits, 2) if credits else 0,
        "credits_counted": credits,
        "courses": selected,
    }
    