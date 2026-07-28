from models.transcript import Course


def apply_overrides(courses: list[Course], overrides: list[dict]) -> list[Course]:
    result = [c.model_copy() for c in courses]

    for override in overrides:
        for index, course in enumerate(result):
            same_code = course.code == override["code"]
            same_semester = course.semester == override.get("semester", course.semester)

            if same_code and same_semester:
                result[index] = course.model_copy(update={
                    "letter_grade": override["letter_grade"]
                })

    return result