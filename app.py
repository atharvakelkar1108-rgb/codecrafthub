"""
CodeCraftHub - Course Tracking REST API

This Flask application provides CRUD operations for courses and stores
course data in a local JSON file named courses.json.

Run with:

    python app.py
"""

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import uuid

from flask import Flask, jsonify, request


# Create the Flask application
app = Flask(__name__)

# Store courses.json in the same directory as this app.py file
DATA_FILE = Path(__file__).parent / "courses.json"

# These are the only valid values for a course's status
VALID_STATUSES = {
    "Not Started",
    "In Progress",
    "Completed",
}

# Every course must include these fields when it is created or replaced
REQUIRED_FIELDS = {
    "name",
    "description",
    "target_date",
    "status",
}


class CourseFileError(Exception):
    """
    Custom exception used when courses.json cannot be read or written.
    """
    pass


def ensure_data_file_exists():
    """
    Create courses.json automatically if it does not already exist.

    The initial contents are an empty JSON array.
    """
    try:
        if not DATA_FILE.exists():
            DATA_FILE.write_text("[]", encoding="utf-8")
    except OSError as error:
        raise CourseFileError(
            f"Could not create {DATA_FILE.name}: {error}"
        ) from error


def read_courses():
    """
    Read and return all courses from courses.json.

    Returns:
        list: A list of course dictionaries.

    Raises:
        CourseFileError: If the file cannot be read or contains invalid JSON.
    """
    ensure_data_file_exists()

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            courses = json.load(file)
    except OSError as error:
        raise CourseFileError(
            f"Could not read {DATA_FILE.name}: {error}"
        ) from error
    except json.JSONDecodeError as error:
        raise CourseFileError(
            f"{DATA_FILE.name} contains invalid JSON: {error}"
        ) from error

    # The JSON file should contain a list of courses
    if not isinstance(courses, list):
        raise CourseFileError(
            f"{DATA_FILE.name} must contain a JSON array"
        )

    return courses


def write_courses(courses):
    """
    Save all courses to courses.json.

    A temporary file is used first. If writing succeeds, it replaces the
    original file. This helps reduce the chance of leaving a partially
    written JSON file if something goes wrong.
    """
    temporary_file = None

    try:
        # Create a temporary file in the same directory as courses.json
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=DATA_FILE.parent,
            prefix="courses_",
            suffix=".tmp",
            delete=False,
        ) as file:
            json.dump(courses, file, indent=2)
            file.write("\n")
            temporary_file = file.name

        # Replace the old file with the newly written file
        os.replace(temporary_file, DATA_FILE)

    except (OSError, TypeError, ValueError) as error:
        # Remove the temporary file if one was created
        if temporary_file and os.path.exists(temporary_file):
            try:
                os.remove(temporary_file)
            except OSError:
                pass

        raise CourseFileError(
            f"Could not write to {DATA_FILE.name}: {error}"
        ) from error


def get_next_course_id(courses):
    """
    Generate the next course ID.

    IDs begin at 1. For example:
    - An empty file produces ID 1.
    - Existing IDs 1 and 2 produce ID 3.

    Using the highest existing ID also prevents reusing an ID after deletion.
    """
    if not courses:
        return 1

    existing_ids = []

    for course in courses:
        course_id = course.get("id")

        # Ignore malformed IDs rather than crashing while calculating
        # the next ID.
        if isinstance(course_id, int) and course_id > 0:
            existing_ids.append(course_id)

    if not existing_ids:
        return 1

    return max(existing_ids) + 1


def validate_course_data(data, require_all_fields=True):
    """
    Validate course data received from a client.

    Args:
        data: JSON object sent by the client.
        require_all_fields: If True, all required fields must be present.
                            This is used for POST and PUT.

    Returns:
        None if the data is valid, otherwise an error message.
    """
    if not isinstance(data, dict):
        return "Request body must be a JSON object"

    if require_all_fields:
        missing_fields = sorted(REQUIRED_FIELDS - set(data.keys()))

        if missing_fields:
            return (
                "Missing required field(s): "
                + ", ".join(missing_fields)
            )

    # Validate fields that were supplied.
    # For POST and PUT, all of these fields are required.
    for field in REQUIRED_FIELDS:
        if field not in data:
            continue

        value = data[field]

        if not isinstance(value, str) or not value.strip():
            return f"'{field}' must be a non-empty string"

    # Validate the course status
    if "status" in data and data["status"] not in VALID_STATUSES:
        allowed_statuses = ", ".join(sorted(VALID_STATUSES))
        return (
            f"Invalid status. Status must be one of: "
            f"{allowed_statuses}"
        )

    # Validate the target date
    if "target_date" in data:
        try:
            # fromisoformat accepts the YYYY-MM-DD format
            parsed_date = date.fromisoformat(data["target_date"])

            # Make sure values such as timestamps are not accepted
            if parsed_date.isoformat() != data["target_date"]:
                return "target_date must use YYYY-MM-DD format"

        except ValueError:
            return "target_date must use YYYY-MM-DD format"

    return None


def get_json_body():
    """
    Return the request body as JSON.

    Returns:
        tuple: (data, error_message)

    This helper gives the API a consistent error response when the client
    does not send valid JSON.
    """
    if not request.is_json:
        return None, "Request Content-Type must be application/json"

    data = request.get_json(silent=True)

    if data is None:
        return None, "Request body must contain valid JSON"

    return data, None


@app.errorhandler(CourseFileError)
def handle_course_file_error(error):
    """
    Return a JSON response when courses.json cannot be read or written.
    """
    return jsonify({
        "error": "File error",
        "message": str(error),
    }), 500


@app.errorhandler(404)
def handle_not_found(error):
    """
    Return JSON instead of Flask's default HTML 404 page.
    """
    return jsonify({
        "error": "Endpoint not found"
    }), 404


@app.errorhandler(405)
def handle_method_not_allowed(error):
    """
    Return JSON when an unsupported HTTP method is used.
    """
    return jsonify({
        "error": "HTTP method not allowed"
    }), 405


@app.route("/api/courses", methods=["POST"])
def create_course():
    """
    Create a new course.

    POST /api/courses
    """
    data, json_error = get_json_body()

    if json_error:
        return jsonify({"error": json_error}), 400

    validation_error = validate_course_data(data)

    if validation_error:
        return jsonify({
            "error": validation_error
        }), 400

    courses = read_courses()

    new_course = {
        "id": get_next_course_id(courses),
        "name": data["name"].strip(),
        "description": data["description"].strip(),
        "target_date": data["target_date"],
        "status": data["status"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    courses.append(new_course)
    write_courses(courses)

    return jsonify(new_course), 201


@app.route("/api/courses", methods=["GET"])
def get_all_courses():
    """
    Return all courses.

    GET /api/courses
    """
    courses = read_courses()

    return jsonify(courses), 200


@app.route("/api/courses/<int:course_id>", methods=["GET"])
def get_course(course_id):
    """
    Return one course by ID.

    GET /api/courses/<id>
    """
    courses = read_courses()

    for course in courses:
        if course.get("id") == course_id:
            return jsonify(course), 200

    return jsonify({
        "error": "Course not found",
        "message": f"No course exists with ID {course_id}",
    }), 404


@app.route("/api/courses/<int:course_id>", methods=["PUT"])
def update_course(course_id):
    """
    Replace an existing course.

    PUT /api/courses/<id>

    PUT requires all course fields except id, which is taken from the URL.
    The original created_at timestamp is preserved.
    """
    data, json_error = get_json_body()

    if json_error:
        return jsonify({"error": json_error}), 400

    validation_error = validate_course_data(data)

    if validation_error:
        return jsonify({
            "error": validation_error
        }), 400

    courses = read_courses()

    for index, existing_course in enumerate(courses):
        if existing_course.get("id") == course_id:
            updated_course = {
                "id": course_id,
                "name": data["name"].strip(),
                "description": data["description"].strip(),
                "target_date": data["target_date"],
                "status": data["status"],
                "created_at": existing_course.get(
                    "created_at",
                    datetime.now(timezone.utc).isoformat(),
                ),
            }

            courses[index] = updated_course
            write_courses(courses)

            return jsonify(updated_course), 200

    return jsonify({
        "error": "Course not found",
        "message": f"No course exists with ID {course_id}",
    }), 404


@app.route("/api/courses/<int:course_id>", methods=["DELETE"])
def delete_course(course_id):
    """
    Delete a course by ID.

    DELETE /api/courses/<id>
    """
    courses = read_courses()

    course_to_delete = None

    for course in courses:
        if course.get("id") == course_id:
            course_to_delete = course
            break

    if course_to_delete is None:
        return jsonify({
            "error": "Course not found",
            "message": f"No course exists with ID {course_id}",
        }), 404

    courses.remove(course_to_delete)
    write_courses(courses)

    return jsonify({
        "message": "Course deleted successfully",
        "course": course_to_delete,
    }), 200


if __name__ == "__main__":
    # This also causes courses.json to be created when the app starts.
    ensure_data_file_exists()

    # debug=True is useful while learning, but should be disabled in production.
    app.run(debug=True)
