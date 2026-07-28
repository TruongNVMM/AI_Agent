from pydantic import BaseModel


class Course(BaseModel):
    semester: str
    code: str
    name: str
    credits: int
    class_id: str | None = None
    process_score: float | None = None
    exam_score: float | None = None
    letter_grade: str


class SemesterResult(BaseModel):
    semester: str
    gpa: float
    cpa: float
    credits_counted: int
    cumulative_credits: int

GRADE_POINTS = {
    "A+": 4.0,
    "A": 4.0,
    "B+": 3.5,
    "B": 3.0,
    "C+": 2.5,
    "C": 2.0,
    "D+": 1.5,
    "D": 1.0,
    "F": 0.0
}