import sqlite3
import re
import hashlib
import secrets
import hmac
import os
import streamlit as st

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="School Health Passport", page_icon="🏥", layout="wide"
)

# --- DATABASE SETUP & MIGRATION ---
DB_NAME = os.environ.get("SCHOOL_HEALTH_DB_PATH", "school_health.db")
# Password for the pre-login emergency lookup.
EMERGENCY_LOOKUP_PASSWORD = "HealthSOS"


def get_connection():
  # Keep the database at the same configured path between app sessions.
  # Set SCHOOL_HEALTH_DB_PATH to a persistent mounted volume when hosting.
  os.makedirs(os.path.dirname(os.path.abspath(DB_NAME)), exist_ok=True)
  conn = sqlite3.connect(DB_NAME, check_same_thread=False, timeout=30)
  conn.execute("PRAGMA busy_timeout = 30000")
  return conn


def log_activity(action, details="", actor=None):
  """Append a privacy-conscious audit event; never store passwords or health details."""
  current = actor or st.session_state.get("user") or {}
  actor_name = current.get("name", "Unauthenticated user")
  actor_email = current.get("email", "")
  actor_role = current.get("role", "Guest")
  conn = get_connection()
  conn.execute(
      """INSERT INTO activity_history
         (actor_name, actor_email, actor_role, action, details)
         VALUES (?, ?, ?, ?, ?)""",
      (actor_name, actor_email, actor_role, str(action)[:100], str(details)[:500])
  )
  conn.commit()
  conn.close()


def generate_roll_id(roll_number, grade, section):
  """Generates ID: gj_roll no._class.section (e.g., 'gj_14_6d')"""
  return f"gj_{str(roll_number).strip()}_{grade}{section.lower()}"


def normalize_indian_phone(value):
  """Return an Indian mobile number in the +91XXXXXXXXXX format."""
  digits = re.sub(r"\D", "", str(value or ""))
  if len(digits) == 10:
    return "+91" + digits
  if len(digits) == 12 and digits.startswith("91"):
    return "+" + digits
  if len(digits) == 11 and digits.startswith("0"):
    return "+91" + digits[1:]
  return None


def init_db():
  conn = get_connection()
  cursor = conn.cursor()

  cursor.execute(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='students'"
  )
  table_exists = cursor.fetchone()

  if table_exists:
    cursor.execute("PRAGMA table_info(students)")
    columns = [col[1] for col in cursor.fetchall()]
    if "roll_number" not in columns or "id_number" not in columns:
      cursor.execute("DROP TABLE IF EXISTS students")
      cursor.execute("DROP TABLE IF EXISTS messages")
      cursor.execute("DROP TABLE IF EXISTS parents")

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_number TEXT UNIQUE,
            roll_number INTEGER,
            name TEXT,
            grade INTEGER,
            section TEXT,
            blood_group TEXT,
            allergies TEXT,
            emergency_contact TEXT,
            vaccination_history TEXT,
            medications TEXT,
            photo BLOB
        )
    """)

  # Safely migrate existing databases without deleting student records.
  cursor.execute("PRAGMA table_info(students)")
  student_columns = [col[1] for col in cursor.fetchall()]
  if "photo" not in student_columns:
    cursor.execute("ALTER TABLE students ADD COLUMN photo BLOB")

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            grade INTEGER,
            section TEXT,
            target TEXT,
            student_name TEXT,
            message TEXT,
            date TEXT
        )
    """)

  # One-time refresh of the starter student records.
  # The previous version only inserted sample students when the table was empty,
  # so existing SQLite databases kept displaying the old names and details.
  cursor.execute("""
      CREATE TABLE IF NOT EXISTS app_migrations (
          migration_key TEXT PRIMARY KEY,
          applied_at TEXT DEFAULT CURRENT_TIMESTAMP
      )
  """)
  migration_key = "replace_old_sample_students_v1"
  cursor.execute(
      "SELECT 1 FROM app_migrations WHERE migration_key = ?",
      (migration_key,),
  )
  migration_already_applied = cursor.fetchone() is not None

  sample_students = [
      {
          "old_name": "Aarav Sharma",
          "roll": 7, "name": "Kabir Malhotra", "grade": 5, "section": "A",
          "blood": "B+", "allergies": "Peanuts", "emergency": "+919876543210",
          "vax": "Fully Vaccinated", "meds": "None",
      },
      {
          "old_name": "Isha V Prasad",
          "roll": 12, "name": "Diya Mehta", "grade": 6, "section": "D",
          "blood": "O+", "allergies": "None", "emergency": "+919123456789",
          "vax": "Fully Vaccinated", "meds": "None",
      },
      {
          "old_name": "Noopura Nambiar",
          "roll": 18, "name": "Meera Iyer", "grade": 6, "section": "D",
          "blood": "A+", "allergies": "Dust", "emergency": "+919988776655",
          "vax": "Fully Vaccinated", "meds": "None",
      },
      {
          "old_name": "Ananya Rao",
          "roll": 23, "name": "Rohan Kapoor", "grade": 3, "section": "B",
          "blood": "O-", "allergies": "Dairy", "emergency": "+919555544444",
          "vax": "Fully Vaccinated", "meds": "None",
      },
  ]

  if not migration_already_applied:
    cursor.execute("SELECT COUNT(*) FROM students")
    existing_count = cursor.fetchone()[0]

    if existing_count == 0:
      for student in sample_students:
        new_id = generate_roll_id(
            student["roll"], student["grade"], student["section"]
        )
        cursor.execute(
            """
            INSERT INTO students
            (id_number, roll_number, name, grade, section, blood_group,
             allergies, emergency_contact, vaccination_history, medications)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id, student["roll"], student["name"], student["grade"],
                student["section"], student["blood"], student["allergies"],
                student["emergency"], student["vax"], student["meds"],
            ),
        )
    else:
      # Update the old starter rows in place. This preserves their database row IDs,
      # while clearing any old photo so it is not shown beside a different name.
      for student in sample_students:
        new_id = generate_roll_id(
            student["roll"], student["grade"], student["section"]
        )
        cursor.execute(
            """
            UPDATE students
            SET id_number = ?, roll_number = ?, name = ?, grade = ?,
                section = ?, blood_group = ?, allergies = ?,
                emergency_contact = ?, vaccination_history = ?,
                medications = ?, photo = NULL
            WHERE name = ?
            """,
            (
                new_id, student["roll"], student["name"], student["grade"],
                student["section"], student["blood"], student["allergies"],
                student["emergency"], student["vax"], student["meds"],
                student["old_name"],
            ),
        )

      # If the database had no matching old sample rows, add the starter records
      # only when there are no student records to avoid duplicating custom data.
      cursor.execute("SELECT COUNT(*) FROM students")
      if cursor.fetchone()[0] == 0:
        for student in sample_students:
          new_id = generate_roll_id(
              student["roll"], student["grade"], student["section"]
          )
          cursor.execute(
              """
              INSERT INTO students
              (id_number, roll_number, name, grade, section, blood_group,
               allergies, emergency_contact, vaccination_history, medications)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
              """,
              (
                  new_id, student["roll"], student["name"], student["grade"],
                  student["section"], student["blood"], student["allergies"],
                  student["emergency"], student["vax"], student["meds"],
              ),
          )

    cursor.execute(
        "INSERT INTO app_migrations (migration_key) VALUES (?)",
        (migration_key,),
    )

  # Keep all valid saved student contacts in the same +91XXXXXXXXXX format.
  cursor.execute("SELECT id, emergency_contact FROM students")
  for student_row_id, saved_contact in cursor.fetchall():
    formatted_contact = normalize_indian_phone(saved_contact)
    if formatted_contact:
      cursor.execute(
          "UPDATE students SET emergency_contact = ? WHERE id = ?",
          (formatted_contact, student_row_id),
      )

  # Rebuild old account table safely to support Admin and approval status.
  cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
  old_table = cursor.fetchone()
  old_columns = []
  if old_table:
    cursor.execute("PRAGMA table_info(users)")
    old_columns = [col[1] for col in cursor.fetchall()]

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS users_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          full_name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE COLLATE NOCASE,
          role TEXT NOT NULL CHECK(role IN ('Nurse', 'Teacher', 'Parent', 'Admin')),
          password_salt TEXT NOT NULL,
          password_hash TEXT NOT NULL,
          child_id TEXT,
          employee_id TEXT,
          assigned_grade INTEGER,
          assigned_section TEXT,
          status TEXT NOT NULL DEFAULT 'Pending',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
      )
  """)
  if old_table:
    cursor.execute("SELECT COUNT(*) FROM users_new")
    if cursor.fetchone()[0] == 0:
      cursor.execute("SELECT * FROM users")
      for row in cursor.fetchall():
        old = dict(zip(old_columns, row))
        role = old.get("role", "Parent")
        status = old.get("status") or ("Approved" if role == "Admin" else "Pending")
        cursor.execute(
            """INSERT OR IGNORE INTO users_new
               (id, full_name, email, role, password_salt, password_hash,
                child_id, employee_id, assigned_grade, assigned_section, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (old.get("id"), old.get("full_name", "User"), old.get("email"),
             role, old.get("password_salt", ""), old.get("password_hash", ""),
             old.get("child_id"), old.get("employee_id"),
             old.get("assigned_grade"), old.get("assigned_section"), status,
             old.get("created_at"))
        )
    cursor.execute("DROP TABLE users")
  cursor.execute("ALTER TABLE users_new RENAME TO users")
  cursor.execute("DROP INDEX IF EXISTS one_admin_account")
  cursor.execute("CREATE UNIQUE INDEX one_admin_account ON users(role) WHERE role='Admin'")

  # Employee IDs are unique across Nurses and Teachers, ignoring letter case.
  # Preserve older accounts if duplicate IDs exist; clear duplicate values so
  # the Principal can review and correct those accounts.
  duplicate_ids = cursor.execute(
      """SELECT employee_id FROM users
         WHERE employee_id IS NOT NULL AND TRIM(employee_id) != ''
         GROUP BY employee_id COLLATE NOCASE HAVING COUNT(*) > 1"""
  ).fetchall()
  for (duplicate_id,) in duplicate_ids:
    duplicate_rows = cursor.execute(
        """SELECT id FROM users WHERE employee_id = ? COLLATE NOCASE
           ORDER BY id""", (duplicate_id,)
    ).fetchall()
    for (duplicate_user_id,) in duplicate_rows[1:]:
      cursor.execute("UPDATE users SET employee_id=NULL WHERE id=?", (duplicate_user_id,))
  cursor.execute(
      """CREATE UNIQUE INDEX IF NOT EXISTS unique_employee_id
         ON users(employee_id COLLATE NOCASE)
         WHERE employee_id IS NOT NULL AND TRIM(employee_id) != ''"""
  )

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS activity_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          actor_name TEXT NOT NULL,
          actor_email TEXT,
          actor_role TEXT,
          action TEXT NOT NULL,
          details TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
      )
  """)

  conn.commit()
  conn.close()


init_db()

# --- DESIGN & STYLING ---
st.markdown(
    """
    <style>
    .stApp {
        background-color: #FFFFFF;
        color: #2C2C2C;
        font-family: sans-serif;
    }
    div.stMarkdown, div.stForm, div.stExpander, div[data-testid="stMetric"] {
        background-color: #F7F4EF;
        padding: 1.2rem;
        border-radius: 10px;
        border: 1px solid #E6E0D8;
        margin-bottom: 1rem;
    }
    .stButton>button {
        background-color: #EFECE6;
        color: #2C2C2C;
        border: 1px solid #D5CEC7;
        border-radius: 6px;
        padding: 0.5rem 1rem;
        font-weight: bold;
        width: 100%;
    }
    .stButton>button:hover {
        background-color: #E2DDD5;
        border-color: #BCB4AB;
    }
    h1, h2, h3 {
        color: #3E3832;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# --- SESSION STATE INITIALIZATION ---
if "logged_in" not in st.session_state:
  st.session_state.logged_in = False
if "user" not in st.session_state:
  st.session_state.user = None
if "nurse_selected_grade" not in st.session_state:
  st.session_state.nurse_selected_grade = None
if "nurse_selected_section" not in st.session_state:
  st.session_state.nurse_selected_section = None
if "teacher_grade" not in st.session_state:
  st.session_state.teacher_grade = 5
if "teacher_section" not in st.session_state:
  st.session_state.teacher_section = "A"


# --- PRE-LOGIN EMERGENCY STUDENT LOOKUP ---
def show_emergency_student(student):
  """Display the selected student's health details and photo."""
  st.markdown(f"### 🚨 {student[3]}")
  photo_col, info_col = st.columns([1, 3], gap="large")
  with photo_col:
    show_student_photo(student[11] if len(student) > 11 else None, student[3])
  with info_col:
    st.markdown(f"""
    - **Student ID:** `{student[1]}`
    - **Roll Number:** {student[2]}
    - **Grade / Section:** {student[4]}{student[5]}
    - **Blood Group:** {student[6] or 'Not provided'}
    - **Allergies:** {student[7] or 'None recorded'}
    - **Emergency Contact:** {normalize_indian_phone(student[8]) or student[8] or 'Not provided'}
    - **Vaccinations:** {student[9] or 'Not provided'}
    - **Medications:** {student[10] or 'None recorded'}
    """)


def emergency_lookup_section():
  """Password-gated, Gmail-style emergency student search."""
  st.markdown("## 🚨 Emergency Student Lookup")
  st.caption(
      "Search by student name, roll number or ID. Use the filter button "
      "to narrow the results with additional details."
  )

  if not st.session_state.get("emergency_lookup_unlocked", False):
    with st.form("emergency_lookup_password_form"):
      entered_password = st.text_input(
          "Emergency Access Password", type="password"
      )
      unlock = st.form_submit_button("Unlock Emergency Lookup")
    if unlock:
      if entered_password == EMERGENCY_LOOKUP_PASSWORD:
        st.session_state.emergency_lookup_unlocked = True
        log_activity("Emergency lookup unlocked", "Emergency lookup access granted")
        st.rerun()
      else:
        log_activity("Emergency lookup unlock failed", "Incorrect emergency access password")
        st.error("Incorrect password. Please try again.")
    return

  # A single Gmail-style search bar with optional advanced-search filters.
  search_col, filter_col = st.columns([8, 1])
  with search_col:
    search_query = st.text_input(
        "Search students",
        placeholder="Search by name, roll number or student ID...",
        key="emergency_main_search",
        label_visibility="collapsed",
    ).strip()

  with filter_col:
    with st.popover("⚙️", use_container_width=True):
      st.markdown("**Advanced search**")
      filter_name = st.text_input(
          "Student name", key="emergency_filter_name",
          placeholder="Full or part of name"
      ).strip()
      filter_roll = st.text_input(
          "Roll number", key="emergency_filter_roll",
          placeholder="Enter roll number"
      ).strip()
      filter_grade = st.selectbox(
          "Grade", ["Any"] + [str(g) for g in range(1, 13)],
          key="emergency_filter_grade"
      )
      filter_section = st.selectbox(
          "Section", ["Any", "A", "B", "C", "D", "E"],
          key="emergency_filter_section"
      )

  if st.button("🔎 Search", key="emergency_search_button"):
    st.session_state.emergency_search_submitted = True
    log_activity("Emergency student search", f"Search submitted: {search_query or 'Advanced filters'}")

  if st.session_state.get("emergency_search_submitted", False):
    conditions = []
    params = []

    if search_query:
      pattern = f"%{search_query}%"
      conditions.append(
          "(name LIKE ? COLLATE NOCASE "
          "OR CAST(roll_number AS TEXT) LIKE ? "
          "OR id_number LIKE ? COLLATE NOCASE)"
      )
      params.extend([pattern, pattern, pattern])

    if filter_name:
      conditions.append("name LIKE ? COLLATE NOCASE")
      params.append(f"%{filter_name}%")
    if filter_roll:
      conditions.append("CAST(roll_number AS TEXT) LIKE ?")
      params.append(f"%{filter_roll}%")
    if filter_grade != "Any":
      conditions.append("grade = ?")
      params.append(int(filter_grade))
    if filter_section != "Any":
      conditions.append("section = ?")
      params.append(filter_section)

    if not conditions:
      st.info("Type something in the search bar or choose a filter first.")
    else:
      sql = "SELECT * FROM students WHERE " + " AND ".join(conditions)
      sql += " ORDER BY grade, section, roll_number"
      conn = get_connection()
      rows = conn.execute(sql, params).fetchall()
      conn.close()

      if rows:
        st.success(f"Found {len(rows)} matching student record(s).")
        if len(rows) == 1:
          single_result_key = f"single:{rows[0][0]}"
          if st.session_state.get("last_emergency_viewed") != single_result_key:
            log_activity("Emergency student record viewed", "A student health card was opened through emergency lookup")
            st.session_state.last_emergency_viewed = single_result_key
          show_emergency_student(rows[0])
        else:
          choices = {
              f"{r[3]} — Grade {r[4]}{r[5]}, Roll No. {r[2]}": r
              for r in rows
          }
          selected_label = st.selectbox(
              "Select the student", list(choices.keys()),
              key="emergency_search_result"
          )
          if st.session_state.get("last_emergency_viewed") != selected_label:
            log_activity("Emergency student record viewed", "A student health card was opened through emergency lookup")
            st.session_state.last_emergency_viewed = selected_label
          show_emergency_student(choices[selected_label])
      else:
        st.warning("No matching student found. Try changing your search or filters.")

  if st.button("🔒 Lock Emergency Lookup", key="lock_emergency_lookup"):
    log_activity("Emergency lookup locked", "Emergency lookup session was locked")
    st.session_state.emergency_lookup_unlocked = False
    st.session_state.emergency_search_submitted = False
    st.rerun()


# --- ACCOUNT SECURITY HELPERS ---
def hash_password(password, salt=None):
  """Create a salted PBKDF2-HMAC-SHA256 password hash."""
  salt_bytes = salt if salt is not None else secrets.token_bytes(16)
  password_hash = hashlib.pbkdf2_hmac(
      "sha256", password.encode("utf-8"), salt_bytes, 310000
  )
  return salt_bytes.hex(), password_hash.hex()


def normalize_employee_id(value):
  """Normalize school-issued employee IDs such as EMP001."""
  return re.sub(r"\s+", "", str(value or "")).upper()


def valid_employee_id(value):
  """Accept the school's EMP followed by at least three digits format."""
  return bool(re.fullmatch(r"EMP\d{3,}", normalize_employee_id(value)))


def verify_password(password, saved_salt, saved_hash):
  """Verify a password against its saved salt and hash."""
  try:
    salt_bytes = bytes.fromhex(saved_salt)
    _, candidate_hash = hash_password(password, salt_bytes)
    return hmac.compare_digest(candidate_hash, saved_hash)
  except (TypeError, ValueError):
    return False



# --- DEFAULT PRINCIPAL / ADMIN ACCOUNT ---

def ensure_default_admin():
  """Create or synchronise the Admin account with Streamlit Secrets."""

  admin_email = str(
      st.secrets.get("ADMIN_EMAIL", os.environ.get("ADMIN_EMAIL", ""))
  ).strip().lower()

  admin_password = str(
      st.secrets.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", ""))
  )

  admin_name = str(
      st.secrets.get(
          "ADMIN_NAME",
          os.environ.get("ADMIN_NAME", "School Principal")
      )
  ).strip() or "School Principal"

  if not admin_email or not admin_password:
    return

  conn = get_connection()

  try:
    admin = conn.execute(
        """SELECT id, full_name, email, password_salt, password_hash
           FROM users WHERE role = 'Admin' LIMIT 1"""
    ).fetchone()

    # Create the Admin account if it does not exist.
    if not admin:
      salt, pw_hash = hash_password(admin_password)

      conn.execute(
          """INSERT INTO users
             (full_name, email, role, password_salt, password_hash, status)
             VALUES (?, ?, 'Admin', ?, ?, 'Approved')""",
          (admin_name, admin_email, salt, pw_hash)
      )
      conn.commit()
      return

    admin_id, old_name, old_email, old_salt, old_hash = admin

    # Prevent changing the Admin email to one already used by another account.
    email_in_use = conn.execute(
        """SELECT id FROM users
           WHERE email = ? COLLATE NOCASE AND id != ?""",
        (admin_email, admin_id)
    ).fetchone()

    if email_in_use:
      st.error(
          "Admin credentials could not be updated: "
          "the configured Admin email is already used by another account."
      )
      return

    # Check whether the configured password matches the saved password.
    password_matches = verify_password(
        admin_password, old_salt, old_hash
    )

    # Update only when something has actually changed.
    if (
        old_name != admin_name
        or old_email.lower() != admin_email
        or not password_matches
    ):
      salt, pw_hash = hash_password(admin_password)

      conn.execute(
          """UPDATE users
             SET full_name = ?,
                 email = ?,
                 password_salt = ?,
                 password_hash = ?,
                 status = 'Approved'
             WHERE id = ? AND role = 'Admin'""",
          (admin_name, admin_email, salt, pw_hash, admin_id)
      )
      conn.commit()
    else:
      conn.execute(
          "UPDATE users SET status = 'Approved' WHERE id = ?",
          (admin_id,)
      )
      conn.commit()

  except sqlite3.IntegrityError:
    st.error("Could not update the Admin account because of a database conflict.")

  finally:
    conn.close()


ensure_default_admin()


def admin_dashboard():
  st.markdown("## 🛡️ Principal / Admin Dashboard")
  st.caption("Approve staff and parent accounts, and manage registered users.")
  conn = get_connection()

  st.subheader("Pending Account Approvals")
  pending = conn.execute(
      """SELECT id,full_name,email,role,employee_id,child_id,assigned_grade,
                assigned_section,created_at
         FROM users WHERE status='Pending' AND role!='Admin' ORDER BY created_at"""
  ).fetchall()
  if not pending:
    st.info("No accounts are waiting for approval.")
  for account in pending:
    uid,name,email,role,emp_id,child_id,grade,section,created = account
    with st.expander(f"{role} — {name} ({email})"):
      if role in ("Nurse", "Teacher"):
        st.write(f"Employee ID: {emp_id or 'Not provided'}")
      elif role == "Parent":
        st.write(f"Child's Student ID: {child_id or 'Not provided'}")
      if role == "Teacher":
        st.write(f"Assigned class: Grade {grade}{section}")
      st.caption(f"Registered: {created or 'Date unavailable'}")
      c1,c2=st.columns(2)
      with c1:
        if st.button("Approve",key=f"approve_{uid}",use_container_width=True):
          conn.execute("UPDATE users SET status='Approved' WHERE id=? AND role!='Admin'",(uid,))
          conn.commit()
          log_activity("Account approved", f"Approved {role} account: {email}")
          st.rerun()
      with c2:
        if st.button("Reject & Delete",key=f"reject_{uid}",use_container_width=True):
          conn.execute("DELETE FROM users WHERE id=? AND role!='Admin'",(uid,))
          conn.commit()
          log_activity("Account rejected and deleted", f"Deleted {role} account: {email}")
          st.rerun()

  st.divider()
  st.subheader("All Accounts")
  accounts=conn.execute(
      """SELECT id,full_name,email,role,status,employee_id,child_id,
                assigned_grade,assigned_section FROM users ORDER BY role,full_name"""
  ).fetchall()
  for row in accounts:
    uid,name,email,role,status,emp_id,child_id,grade,section=row
    if role == "Admin":
      st.markdown(f"**{name}** · {email} · Principal Admin (fixed account)")
      continue
    detail=f"{role} · {status}"
    if role in ("Nurse", "Teacher"):
      detail += f" · Employee ID: {emp_id or 'Needs correction'}"
    if role == "Teacher":
      detail += f" · Grade {grade}{section}"
    st.markdown(f"**{name}** · {email} · {detail}")
    with st.expander(f"Manage {name}"):
      if status == "Pending" and st.button("Approve account",key=f"allapprove_{uid}"):
        conn.execute("UPDATE users SET status='Approved' WHERE id=?",(uid,))
        conn.commit()
        log_activity("Account approved", f"Approved {role} account: {email}")
        st.rerun()
      if st.button("Delete account",key=f"delete_{uid}"):
        conn.execute("DELETE FROM users WHERE id=? AND role!='Admin'",(uid,))
        conn.commit()
        log_activity("Account deleted", f"Deleted {role} account: {email}")
        st.rerun()

  st.divider()
  st.subheader("Create an Account")
  # Outside the form so the ID field changes immediately with the selected role.
  role=st.selectbox("Role",["Nurse","Teacher","Parent"],key="admin_create_role")
  with st.form("admin_create_account"):
    name=st.text_input("Full Name")
    email=st.text_input("Email Address")
    employee_id=""
    child_id=""
    grade=None
    section=None
    if role in ("Nurse","Teacher"):
      employee_id=st.text_input(
          "Employee ID", placeholder="e.g. EMP001",
          help="Enter a unique Employee ID issued by the school."
      )
    if role=="Teacher":
      c1,c2=st.columns(2)
      with c1:
        grade=st.selectbox("Assigned Grade",list(range(1,13)),key="admin_grade")
      with c2:
        section=st.selectbox("Assigned Section",["A","B","C","D","E"],key="admin_section")
    if role=="Parent":
      child_id=st.text_input("Child's Student ID")
    password=st.text_input("Temporary Password",type="password")
    submit=st.form_submit_button("Create Approved Account")
  if submit:
    clean_email=email.strip().lower()
    if not name.strip() or not clean_email or len(password)<8:
      st.error("Enter a name, email, and password of at least 8 characters.")
    elif role in ("Nurse","Teacher") and not employee_id.strip():
      st.error("Employee ID is required.")
    elif role in ("Nurse","Teacher") and not valid_employee_id(employee_id):
      st.error("Use the school Employee ID format, for example EMP001.")
    else:
      clean_employee_id = normalize_employee_id(employee_id)
      employee_id_taken = (
          conn.execute(
              "SELECT 1 FROM users WHERE employee_id = ? COLLATE NOCASE",
              (clean_employee_id,)
          ).fetchone()
          if role in ("Nurse","Teacher") else None
      )
      linked=True
      if role=="Parent":
        linked=conn.execute("SELECT 1 FROM students WHERE id_number=? COLLATE NOCASE",(child_id.strip().lower(),)).fetchone()
      if employee_id_taken:
        st.error("That Employee ID is already linked to another account.")
      elif not linked:
        st.error("Student ID not found.")
      else:
        salt,pw_hash=hash_password(password)
        try:
          conn.execute(
              """INSERT INTO users
                 (full_name,email,role,password_salt,password_hash,child_id,
                  employee_id,assigned_grade,assigned_section,status)
                 VALUES (?,?,?,?,?,?,?,?,?,'Approved')""",
              (name.strip(),clean_email,role,salt,pw_hash,
               child_id.strip().lower() if role=="Parent" else None,
               clean_employee_id or None,grade,section)
          )
          conn.commit()
          log_activity("Account created by Admin", f"Created approved {role} account: {clean_email}")
          st.success("Approved account created.")
          st.rerun()
        except sqlite3.IntegrityError:
          st.error("That email address is already registered.")

  st.divider()
  st.subheader("📜 Activity History / Audit Log")
  st.caption("A record of account and app actions. Passwords and medical details are never recorded here.")
  history_rows = conn.execute(
      """SELECT created_at, actor_name, actor_email, actor_role, action, details
         FROM activity_history ORDER BY id DESC LIMIT 300"""
  ).fetchall()
  if history_rows:
    st.dataframe(
        [{"Date & Time": r[0], "User": r[1], "Email": r[2] or "—",
          "Role": r[3] or "—", "Action": r[4], "Details": r[5] or "—"}
         for r in history_rows],
        use_container_width=True, hide_index=True
    )
    st.caption("Showing the latest 300 events.")
  else:
    st.info("No activity has been recorded yet.")
  conn.close()


# --- LOGIN AND REGISTRATION PAGE ---
def login_page():
  st.markdown(
      "<h1 style='text-align: center;'>🏥 School Health Passport</h1>",
      unsafe_allow_html=True
  )
  st.markdown(
      "<p style='text-align: center; color: #666;'>School Health & Wellness Portal</p>",
      unsafe_allow_html=True
  )

  with st.expander("🚨 Emergency Student Lookup (Before Login)", expanded=False):
    emergency_lookup_section()

  _, col2, _ = st.columns([1, 2, 1])
  with col2:
    st.markdown("### Welcome")
    st.caption("Create an account first, then sign in using your registered email and password.")
    if not st.secrets.get("ADMIN_EMAIL", os.environ.get("ADMIN_EMAIL", "")) or not st.secrets.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", "")):
      st.info("Principal Admin login is not configured. Set ADMIN_EMAIL and ADMIN_PASSWORD in Streamlit Secrets before deployment.")

    if st.session_state.pop("switch_to_signin", False):
      st.session_state.auth_view = "Sign In"

    auth_view = st.radio(
        "Choose an option",
        ["Sign In", "Create Account"],
        horizontal=True,
        key="auth_view",
        label_visibility="collapsed"
    )

    if auth_view == "Sign In":
      with st.form("login_form"):
        login_email = st.text_input("Registered Email Address", placeholder="name@example.com")
        st.caption("Principal: Sign in using the Admin email and password configured by the school.")
        login_password = st.text_input("Password", type="password")
        login_submit = st.form_submit_button("Sign In", use_container_width=True)

      if login_submit:
        clean_email = login_email.strip().lower()
        if not clean_email or not login_password:
          st.error("Enter both your registered email address and password.")
        else:
          conn = get_connection()
          account = conn.execute(
              """SELECT full_name, email, role, password_salt,
                        password_hash, child_id, assigned_grade,
                        assigned_section, employee_id, status
                 FROM users WHERE email = ? COLLATE NOCASE""",
              (clean_email,)
          ).fetchone()
          conn.close()

          if account and verify_password(login_password, account[3], account[4]) and account[9] == 'Approved':
            st.session_state.user = {
                "name": account[0],
                "email": account[1],
                "role": account[2],
            }
            if account[2] == "Parent":
              st.session_state.user["child_id"] = account[5]
            elif account[2] == "Teacher":
              st.session_state.user["employee_id"] = account[8]
              st.session_state.user["assigned_grade"] = account[6]
              st.session_state.user["assigned_section"] = account[7]
            elif account[2] == "Nurse":
              st.session_state.user["employee_id"] = account[8]
            elif account[2] == "Admin":
              st.session_state.user["is_principal_admin"] = True
            st.session_state.logged_in = True
            log_activity("Successful login", f"Signed in as {account[2]}")
            st.rerun()
          elif account and account[9] != "Approved" and verify_password(login_password, account[3], account[4]):
            st.warning("Your account is awaiting approval by the School Principal.")
          else:
            log_activity("Failed login attempt", f"Attempted email: {clean_email}",
                         actor={"name": "Unknown user", "email": clean_email, "role": "Guest"})
            st.error("Incorrect email or password. If you are new, create an account first.")

    else:
      # Keep the role selector outside the form so Streamlit reruns immediately
      # and displays the correct ID field when the role changes.
      register_role = st.selectbox(
          "Account Role", ["Parent", "Nurse", "Teacher"], key="registration_role"
      )
      with st.form("register_form"):
        school_code = st.text_input(
            "School Code",
            placeholder="Enter the school registration code",
            type="password"
        )
        full_name = st.text_input("Full Name", placeholder="Enter your full name")
        register_email = st.text_input("Email Address", placeholder="name@example.com")

        child_id = ""
        employee_id = ""
        assigned_grade = None
        assigned_section = None

        if register_role == "Parent":
          child_id = st.text_input(
              "Child's Student ID",
              placeholder="e.g. gj_12_6d",
              help="Enter the Student ID provided by your school."
          )
        elif register_role in ("Nurse", "Teacher"):
          employee_id = st.text_input(
              "Employee ID",
              placeholder="e.g. EMP001 (provided by your school)"
          )
          if register_role == "Teacher":
            class_col, section_col = st.columns(2)
            with class_col:
              assigned_grade = st.selectbox("Assigned Grade", list(range(1, 13)))
            with section_col:
              assigned_section = st.selectbox("Assigned Section", ["A", "B", "C", "D", "E"])

        new_password = st.text_input("Create Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")
        register_submit = st.form_submit_button("Create Account", use_container_width=True)

      if register_submit:
        clean_name = full_name.strip()
        clean_email = register_email.strip().lower()
        clean_child_id = child_id.strip().lower() if register_role == "Parent" else None
        clean_employee_id = normalize_employee_id(employee_id) if register_role in ("Nurse", "Teacher") else None

        correct_school_code = str(
          st.secrets.get("SCHOOL_CODE", "")
        ).strip()

        if not school_code.strip():
          st.error("Please enter the School Code.")
        elif not correct_school_code:
          st.error("School registration is not configured. Contact the Principal.")
        elif school_code.strip() != correct_school_code:
          st.error("Invalid School Code. Please contact your school.")
        elif not clean_name or not clean_email or not new_password or not confirm_password:
          st.error("Please complete all required fields.")
        elif register_role in ("Nurse", "Teacher") and not clean_employee_id:
          st.error("Employee ID is required for Nurses and Teachers.")
        elif register_role in ("Nurse", "Teacher") and not valid_employee_id(clean_employee_id):
          st.error("Enter your school-issued Employee ID, for example EMP001.")
        elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", clean_email):
          st.error("Enter a valid email address.")
        elif len(new_password) < 8:
          st.error("Choose a password with at least 8 characters.")
        elif new_password != confirm_password:
          st.error("The passwords do not match.")
        else:
          conn = get_connection()
          existing_account = conn.execute(
              "SELECT 1 FROM users WHERE email = ? COLLATE NOCASE",
              (clean_email,)
          ).fetchone()
          existing_employee_id = None
          if register_role in ("Nurse", "Teacher"):
            existing_employee_id = conn.execute(
                "SELECT 1 FROM users WHERE employee_id = ? COLLATE NOCASE",
                (clean_employee_id,)
            ).fetchone()
          linked_student = None
          if register_role == "Parent":
            linked_student = conn.execute(
                "SELECT id_number FROM students WHERE id_number = ? COLLATE NOCASE",
                (clean_child_id,)
            ).fetchone()

          if existing_account:
            st.error("An account with this email already exists. Please sign in instead.")
          elif existing_employee_id:
            st.error("That Employee ID is already registered. Contact the School Principal if this is your ID.")
          elif register_role == "Parent" and not linked_student:
            st.error("Student ID not found. Check the ID provided by your school.")
          else:
            salt, password_hash = hash_password(new_password)
            try:
              conn.execute(
                  """INSERT INTO users
                     (full_name, email, role, password_salt, password_hash,
                      child_id, employee_id, assigned_grade, assigned_section, status)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending')""",
                  (clean_name, clean_email, register_role, salt, password_hash,
                   clean_child_id, clean_employee_id, assigned_grade, assigned_section)
              )
              conn.commit()
              log_activity("Account registration", f"New {register_role} account requested: {clean_email}",
                           actor={"name": clean_name, "email": clean_email, "role": register_role})
              st.success("Account request submitted. Please sign in after the School Principal approves it.")
              st.session_state.switch_to_signin = True
              st.rerun()
            except sqlite3.IntegrityError:
              st.error("This email is already registered. Please sign in.")
          conn.close()

    st.caption(
        "For a real school deployment, employee IDs and parent–student links must be verified "
        "by the school before accounts are trusted."
    )


# --- STUDENT PHOTO DISPLAY ---
def show_student_photo(photo, caption="Student photo"):
  if photo:
    st.image(photo, caption=caption, width=180)
  else:
    st.caption("No student photo uploaded yet.")


# --- STUDENT RECORD EDITOR ---
def render_student_editor(conn, student, key_prefix="edit"):
  """Show a pre-filled edit form for an authorised staff member."""
  with st.expander("✏️ Edit Student Health Record"):
    with st.form(f"{key_prefix}_student_form_{student[0]}"):
      edit_name = st.text_input("Student Name", value=student[3] or "")
      edit_blood = st.text_input("Blood Group", value=student[6] or "")
      edit_allergies = st.text_area("Allergies", value=student[7] or "")
      edit_emergency = st.text_input("Emergency Contact", value=student[8] or "", placeholder="+91XXXXXXXXXX", help="Enter a 10-digit Indian mobile number; +91 will be added automatically.")
      edit_vax = st.text_area("Vaccination History", value=student[9] or "")
      edit_meds = st.text_area("Medications", value=student[10] or "")
      edit_photo = st.file_uploader(
          "Replace Student Photo (optional)",
          type=["jpg", "jpeg", "png", "webp"],
          key=f"{key_prefix}_edit_photo_{student[0]}"
      )
      submitted = st.form_submit_button("Save Changes")
      if submitted:
        formatted_emergency = normalize_indian_phone(edit_emergency)
        if not edit_name.strip():
          st.error("Student name is required.")
        elif edit_emergency.strip() and not formatted_emergency:
          st.error("Enter a valid 10-digit Indian mobile number.")
        elif edit_photo:
          conn.execute(
              """UPDATE students SET name=?, blood_group=?, allergies=?,
                 emergency_contact=?, vaccination_history=?, medications=?, photo=? WHERE id=?""",
              (edit_name.strip(), edit_blood, edit_allergies, formatted_emergency or '',
               edit_vax, edit_meds, edit_photo.getvalue(), student[0])
          )
          conn.commit()
          log_activity("Student record edited", f"Updated health card for {student[3]} (Student ID: {student[1]})")
          st.success("Student health record and photo updated.")
          st.rerun()
        else:
          conn.execute(
              """UPDATE students SET name=?, blood_group=?, allergies=?,
                 emergency_contact=?, vaccination_history=?, medications=? WHERE id=?""",
              (edit_name.strip(), edit_blood, edit_allergies, formatted_emergency or '',
               edit_vax, edit_meds, student[0])
          )
          conn.commit()
          log_activity("Student record edited", f"Updated health card for {student[3]} (Student ID: {student[1]})")
          st.success("Student health record updated.")
          st.rerun()


# --- SHARED STUDENT SEARCH ---
def render_student_search(conn, grade=None, section=None, key_prefix="search"):
  """Search student records across all visible health-record fields."""
  st.subheader("Search Student Records")
  st.caption("Search by name, student ID, roll number, grade, section, blood group, allergies, or other health details.")

  query = st.text_input(
      "Search students",
      placeholder="e.g. Isha, Grade 6, O+, peanuts, gj_14_6d",
      key=f"{key_prefix}_query",
  ).strip()

  if not query:
    st.info("Enter any student detail above to begin searching.")
    return

  pattern = f"%{query}%"
  sql = """
      SELECT * FROM students
      WHERE (
          name LIKE ? COLLATE NOCASE
          OR id_number LIKE ? COLLATE NOCASE
          OR CAST(roll_number AS TEXT) LIKE ? COLLATE NOCASE
          OR CAST(grade AS TEXT) LIKE ? COLLATE NOCASE
          OR section LIKE ? COLLATE NOCASE
          OR blood_group LIKE ? COLLATE NOCASE
          OR allergies LIKE ? COLLATE NOCASE
          OR emergency_contact LIKE ? COLLATE NOCASE
          OR vaccination_history LIKE ? COLLATE NOCASE
          OR medications LIKE ? COLLATE NOCASE
      )
  """
  params = [pattern] * 10

  # Teachers can search only within their currently assigned class.
  if grade is not None and section is not None:
    sql += " AND grade = ? AND section = ?"
    params.extend([grade, section])

  sql += " ORDER BY grade, section, roll_number"
  results = conn.execute(sql, params).fetchall()

  if results:
    st.success(f"Found {len(results)} matching student record(s).")
    for student in results:
      with st.expander(
          f"Grade {student[4]}{student[5]} • Roll No. {student[2]} — {student[3]} "
          f"(Blood Group: {student[6] or 'Not provided'})"
      ):
        photo_col, info_col = st.columns([1, 3], gap="large")
        with photo_col:
          show_student_photo(student[11] if len(student) > 11 else None, student[3])
        with info_col:
          st.markdown(f"""
          - **Student ID:** `{student[1]}`
          - **Name:** {student[3]}
          - **Grade / Section:** {student[4]}{student[5]}
          - **Blood Group:** {student[6] or 'Not provided'}
          - **Allergies:** {student[7] or 'None recorded'}
          - **Emergency Contact:** {normalize_indian_phone(student[8]) or student[8] or 'Not provided'}
          - **Vaccinations:** {student[9] or 'Not provided'}
          - **Medications:** {student[10] or 'None recorded'}
          """)
  else:
    st.warning("No students matched your search. Try another name or detail.")


# --- NURSE DASHBOARD ---
def nurse_dashboard():
  st.markdown("## 🩺 Nurse Dashboard — Grades 1 to 12 Directory")
  conn = get_connection()

  tab1, tab2, tab3, tab4 = st.tabs([
      "📋 Student Directory",
      "➕ Add Student Record",
      "🔎 Search Students",
      "📨 Inbox & Messages"
  ])

  with tab1:
    st.subheader("Select Grade (1 to 12)")
    grades = list(range(1, 13))
    for i in range(0, len(grades), 4):
      row_grades = grades[i:i+4]
      row_cols = st.columns(4)
      for col_idx, g in enumerate(row_grades):
        with row_cols[col_idx]:
          if st.button(f"Grade {g}", key=f"grade_btn_{g}"):
            st.session_state.nurse_selected_grade = g
            st.session_state.nurse_selected_section = None

    if st.session_state.nurse_selected_grade is not None:
      g = st.session_state.nurse_selected_grade
      st.markdown(f"### Grade {g} — Select Section (A, B, C, D, E)")
      sections = ["A", "B", "C", "D", "E"]
      sec_cols = st.columns(5)
      for idx, sec in enumerate(sections):
        count = conn.execute(
            "SELECT COUNT(*) FROM students WHERE grade = ? AND section = ?",
            (g, sec)
        ).fetchone()[0]
        with sec_cols[idx]:
          if st.button(f"Sec {sec} ({count})", key=f"sec_btn_{g}_{sec}"):
            st.session_state.nurse_selected_section = sec

      if st.session_state.nurse_selected_section is not None:
        sec = st.session_state.nurse_selected_section
        st.markdown(f"#### Students in Grade {g}{sec}")
        students = conn.execute(
            "SELECT * FROM students WHERE grade = ? AND section = ? ORDER BY roll_number ASC",
            (g, sec)
        ).fetchall()

        if students:
          for student in students:
            with st.expander(
                f"Roll No. {student[2]} — {student[3]} (ID: `{student[1]}`)"
            ):
              photo_col, info_col = st.columns([1, 3], gap="large")
              with photo_col:
                show_student_photo(student[11] if len(student) > 11 else None, student[3])
              with info_col:
                new_photo = st.file_uploader(
                  "Upload / Replace Student Photo",
                  type=["jpg", "jpeg", "png", "webp"],
                    key=f"nurse_photo_{student[0]}"
                )
                if st.button("Save Photo", key=f"nurse_save_photo_{student[0]}"):
                  if new_photo:
                    conn.execute("UPDATE students SET photo = ? WHERE id = ?", (new_photo.getvalue(), student[0]))
                    conn.commit()
                    log_activity("Student photo updated", f"Photo updated for {student[3]} (Student ID: {student[1]})")
                    st.success("Student photo updated.")
                    st.rerun()
                  else:
                    st.warning("Choose an image first.")
                st.markdown(f"""
                  - **Student ID:** `{student[1]}`
                  - **Roll Number:** {student[2]}
                  - **Blood Group:** {student[6]}
                  - **Allergies:** {student[7]}
                  - **Emergency Contact:** {normalize_indian_phone(student[8]) or student[8] or 'Not provided'}
                  - **Vaccinations:** {student[9]}
                  - **Medications:** {student[10]}
                """)
              render_student_editor(conn, student, "nurse")
              if st.button("Remove Student (Left School)", key=f"nurse_rem_{student[0]}"):
                conn.execute("DELETE FROM students WHERE id = ?", (student[0],))
                conn.commit()
                log_activity("Student record deleted", f"Removed {student[3]} (Student ID: {student[1]})")
                st.success(f"Removed {student[3]}")
                st.rerun()
        else:
          st.info(f"No students registered in Grade {g}{sec}.")

  with tab2:
    st.subheader("Add Student Health Record")
    with st.form("add_student_form"):
      s_name = st.text_input("Student Name (e.g., Isha V Prasad)")
      col_r, col_g, col_s = st.columns(3)
      with col_r:
        s_roll = st.number_input("Roll Number", min_value=1, step=1, value=1)
      with col_g:
        s_grade = st.selectbox("Grade", list(range(1, 13)))
      with col_s:
        s_section = st.selectbox("Section", ["A", "B", "C", "D", "E"])

      s_blood = st.text_input("Blood Group")
      s_emergency = st.text_input("Emergency Contact", placeholder="+91XXXXXXXXXX", help="Enter a 10-digit Indian mobile number; +91 will be added automatically.")
      s_allergies = st.text_area("Allergies")
      s_vax = st.text_area("Vaccination History")
      s_meds = st.text_area("Medications")
      s_photo = st.file_uploader(
          "Upload Student Photo (JPG, JPEG, PNG or WEBP)",
          type=["jpg", "jpeg", "png", "webp"],
          help="Choose a clear photo to help authorised staff identify the student."
      )

      if st.form_submit_button("Save Student Record"):
        formatted_s_emergency = normalize_indian_phone(s_emergency)
        if s_emergency.strip() and not formatted_s_emergency:
          st.error("Enter a valid 10-digit Indian mobile number.")
        elif s_name.strip():
          s_id_num = generate_roll_id(s_roll, s_grade, s_section)
          try:
            conn.execute(
                """
                INSERT INTO students
                (id_number, roll_number, name, grade, section, blood_group,
                 allergies, emergency_contact, vaccination_history, medications, photo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (s_id_num, s_roll, s_name.strip(), s_grade, s_section, s_blood,
                 s_allergies, formatted_s_emergency or '', s_vax, s_meds,
                 s_photo.getvalue() if s_photo else None),
            )
            conn.commit()
            log_activity("Student record added", f"Added {s_name} (Student ID: {s_id_num})")
            st.success(f"Added {s_name} with ID `{s_id_num}` to Grade {s_grade}{s_section}!")
            st.rerun()
          except sqlite3.IntegrityError:
            st.error(f"Error: Roll number {s_roll} already exists in Grade {s_grade}{s_section}.")
        else:
          st.error("Student Name is required.")

  with tab3:
    render_student_search(conn, key_prefix="nurse_student_search")

  with tab4:
    st.subheader("Inbox")
    nurse_messages = conn.execute(
        """
        SELECT sender, grade, section, target, student_name, message, date
        FROM messages
        WHERE target IN ('Nurse', 'All')
        ORDER BY id DESC
        """
    ).fetchall()

    if nurse_messages:
      for message in nurse_messages:
        with st.container():
          st.markdown(
              f"**From:** {message[0]} · **Grade:** {message[1]}{message[2]} "
              f"· **Student:** {message[4]} · **Date:** {message[6]}"
          )
          st.markdown(f"**Message:** {message[5]}")
          st.caption(f"Sent to: {message[3]}")
          st.divider()
    else:
      st.info("Your inbox is empty.")

    with st.expander("✉️ Compose a Message", expanded=False):
      sel_g = st.selectbox("Grade", list(range(1, 13)), key="nurse_msg_grade")
      sel_sec = st.selectbox("Section", ["A", "B", "C", "D", "E"], key="nurse_msg_sec")
      students_in_class = conn.execute(
          "SELECT name FROM students WHERE grade = ? AND section = ? ORDER BY name",
          (sel_g, sel_sec)
      ).fetchall()
      student_names = [student[0] for student in students_in_class]

      with st.form("nurse_send_msg_form"):
        target_student = st.selectbox(
            "Select Student",
            student_names if student_names else ["No students available"]
        )
        target_audience = st.selectbox("Send To", ["Parent", "Teacher", "All"])
        msg_text = st.text_area("Message / Note")
        if st.form_submit_button("Send Message"):
          if target_student == "No students available":
            st.error("There are no students in this class.")
          elif not msg_text.strip():
            st.error("Please enter a message before sending.")
          else:
            conn.execute(
                """
                INSERT INTO messages
                (sender, grade, section, target, student_name, message, date)
                VALUES (?, ?, ?, ?, ?, ?, date('now'))
                """,
                ("School Nurse", sel_g, sel_sec, target_audience, target_student, msg_text.strip()),
            )
            conn.commit()
            log_activity("Message sent", f"Message about {target_student} sent to {target_audience}")
            st.success(f"Message sent to {target_audience} successfully!")
            st.rerun()

  conn.close()


# --- TEACHER DASHBOARD ---
def teacher_dashboard():
  st.markdown("## 📚 Teacher Dashboard — Class Roster & Health Records")

  grade = st.session_state.user.get("assigned_grade")
  section = st.session_state.user.get("assigned_section")
  if grade is None or section not in ["A", "B", "C", "D", "E"]:
    st.error("Your account does not have a valid assigned class. Contact the school administrator.")
    return
  st.markdown("---")
  st.markdown(f"### Currently Managing: **Grade {grade}{section}**")

  conn = get_connection()
  tab1, tab3, tab4 = st.tabs([
      "👥 Class Roster",
      "🔎 Search Students",
      "📨 Inbox & Messages"
  ])

  with tab1:
    st.subheader(f"Students in Grade {grade}{section}")
    students = conn.execute(
        """
        SELECT * FROM students WHERE grade = ? AND section = ?
        ORDER BY roll_number ASC
        """,
        (grade, section)
    ).fetchall()

    if students:
      for student in students:
        with st.expander(
            f"Roll No. {student[2]} — {student[3]} (ID: `{student[1]}` | Blood: {student[6]})"
        ):
          photo_col, info_col = st.columns([1, 3], gap="large")
          with photo_col:
            show_student_photo(student[11] if len(student) > 11 else None, student[3])
          with info_col:
            st.markdown(f"""
              - **Student ID:** `{student[1]}`
              - **Roll Number:** {student[2]}
              - **Allergies:** {student[7]}
              - **Emergency Contact:** {normalize_indian_phone(student[8]) or student[8] or 'Not provided'}
            """)
    else:
      st.info(f"No students found in Grade {grade}{section}. Use the 'Add/Remove Students' tab to add your class list.")

  with tab3:
    render_student_search(
        conn, grade=grade, section=section, key_prefix="teacher_student_search"
    )

  with tab4:
    st.subheader(f"Inbox — Grade {grade}{section}")
    teacher_messages = conn.execute(
        """
        SELECT sender, target, student_name, message, date
        FROM messages
        WHERE grade = ? AND section = ? AND target IN ('Teacher', 'All')
        ORDER BY id DESC
        """,
        (grade, section)
    ).fetchall()

    if teacher_messages:
      for message in teacher_messages:
        with st.container():
          st.markdown(
              f"**From:** {message[0]} · **Student:** {message[2]} "
              f"· **Date:** {message[4]}"
          )
          st.markdown(f"**Message:** {message[3]}")
          st.caption(f"Sent to: {message[1]}")
          st.divider()
    else:
      st.info("Your inbox is empty.")

    with st.expander("✉️ Compose a Message", expanded=False):
      students_in_class = conn.execute(
          "SELECT name FROM students WHERE grade = ? AND section = ? ORDER BY name",
          (grade, section)
      ).fetchall()
      student_names = [student[0] for student in students_in_class]

      with st.form("teacher_msg_form"):
        target_student = st.selectbox(
            "Select Student",
            student_names if student_names else ["No students available"]
        )
        target_audience = st.selectbox("Send To", ["Nurse", "Parent", "All"])
        msg_text = st.text_area("Message / Note")
        if st.form_submit_button("Send Message"):
          if target_student == "No students available":
            st.error("There are no students in your class.")
          elif not msg_text.strip():
            st.error("Please enter a message before sending.")
          else:
            conn.execute(
                """
                INSERT INTO messages
                (sender, grade, section, target, student_name, message, date)
                VALUES (?, ?, ?, ?, ?, ?, date('now'))
                """,
                (f"Teacher (Grade {grade}{section})", grade, section,
                 target_audience, target_student, msg_text.strip()),
            )
            conn.commit()
            log_activity("Message sent", f"Message about {target_student} sent to {target_audience}")
            st.success(f"Message sent to {target_audience} successfully!")
            st.rerun()

  conn.close()


# --- PARENT DASHBOARD ---
def parent_dashboard():
  st.markdown("## 👨‍👩‍👧 Parent Health Passport Portal")
  conn = get_connection()

  child_id = st.session_state.user["child_id"]
  student = conn.execute("SELECT * FROM students WHERE id_number = ?", (child_id,)).fetchone()

  if student:
    st.markdown(f"### 📋 Health Passport for: **{student[3]}** (ID: \`{student[1]}\` | Roll No: {student[2]})")
    photo_col, info_col = st.columns([1, 3], gap="large")
    with photo_col:
      show_student_photo(student[11] if len(student) > 11 else None, student[3])
    with info_col:
      st.markdown(f"""
          - **Grade / Section:** Grade {student[4]}{student[5]}
          - **Blood Group:** {student[6]}
          - **Allergies:** {student[7]}
          - **Emergency Contact:** {normalize_indian_phone(student[8]) or student[8] or 'Not provided'}
          - **Vaccination History:** {student[9]}
          - **Medications:** {student[10]}
          """)

    st.markdown("### 📨 Messages & Updates for This Child")
    parent_messages = conn.execute(
        """
        SELECT sender, target, message, date 
        FROM messages 
        WHERE student_name = ? AND (target = 'Parent' OR target = 'All')
        """,
        (student[3],)
    ).fetchall()

    if parent_messages:
      for pm in parent_messages:
        st.markdown(f"""
            **From:** {pm[0]} | **Audience:** {pm[1]} | **Date:** {pm[3]}  
            **Message:** {pm[2]}
            """)
    else:
      st.info("No messages for this student yet.")
  else:
    st.error("Student record not found.")

  conn.close()


# --- MAIN ROUTER ---
def main():
  if not st.session_state.logged_in:
    login_page()
  else:
    st.sidebar.markdown(f"**User:** {st.session_state.user['name']}")
    st.sidebar.markdown(f"**Role:** {st.session_state.user['role']}")
    if st.sidebar.button("Logout"):
      log_activity("Logout", "User signed out")
      st.session_state.logged_in = False
      st.session_state.user = None
      st.session_state.emergency_lookup_unlocked = False
      st.session_state.pop("emergency_roll_result_id", None)
      st.session_state.nurse_selected_grade = None
      st.session_state.nurse_selected_section = None
      st.rerun()

    st.sidebar.markdown("---")
    role = st.session_state.user["role"]
    if role == "Nurse":
      nurse_dashboard()
    elif role == "Teacher":
      teacher_dashboard()
    elif role == "Parent":
      parent_dashboard()
    elif role == "Admin":
      admin_dashboard()


if __name__ == "__main__":
  main()
