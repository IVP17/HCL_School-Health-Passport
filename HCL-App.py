import sqlite3
import streamlit as st

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="School Health Passport", page_icon="🏥", layout="wide"
)

# --- DATABASE SETUP & MIGRATION ---
DB_NAME = "school_health.db"


def get_connection():
  return sqlite3.connect(DB_NAME, check_same_thread=False)


def generate_roll_id(roll_number, grade, section):
  """Generates ID: gj_roll no._class.section (e.g., 'gj_12_6b')"""
  return f"gj_{str(roll_number).strip()}_{grade}{section.lower()}"


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

  # Fictional demo records. All fields are intentionally different from the
  # original sample data so the displayed demo profiles are fully refreshed.
  initial_students = [
      (8, "Kabir Malhotra", 5, "C", "A+", "None recorded", "DEMO-EMERGENCY-001", "Dose records up to date (demo)", "None recorded"),
      (12, "Diya Mehta", 6, "B", "B-", "Pollen (demo)", "DEMO-EMERGENCY-002", "Booster due (demo)", "None recorded"),
      (18, "Meera Iyer", 7, "A", "AB+", "None recorded", "DEMO-EMERGENCY-003", "Records pending verification (demo)", "None recorded"),
      (6, "Rohan Kapoor", 4, "C", "O-", "Dust (demo)", "DEMO-EMERGENCY-004", "Dose records up to date (demo)", "None recorded"),
  ]

  # Identify the original built-in demo rows by their old names, their newer
  # demo names, or their original class/roll combinations. Then update every
  # field in place (including roll, grade, section, ID and health details).
  # This preserves each row's primary key and uploaded photo.
  old_demo_names = ["Aarav Sharma", "Isha V Prasad", "Noopura Nambiar", "Ananya Rao"]
  new_demo_names = ["Kabir Malhotra", "Diya Mehta", "Meera Iyer", "Rohan Kapoor"]
  original_demo_positions = [(1, 5, "A"), (14, 6, "D"), (15, 6, "D"), (3, 3, "B")]
  for index, (roll, name, grade, section, blood, allergies, emergency, vax, meds) in enumerate(initial_students):
    old_roll, old_grade, old_section = original_demo_positions[index]
    old_name = old_demo_names[index]
    new_name = new_demo_names[index]
    cursor.execute(
        """SELECT id, name, photo FROM students
           WHERE name IN (?, ?)
              OR (roll_number = ? AND grade = ? AND section = ?)
           ORDER BY id""",
        (old_name, new_name, old_roll, old_grade, old_section),
    )
    matches = cursor.fetchall()
    id_num = generate_roll_id(roll, grade, section)

    if matches:
      canonical_id = matches[0][0]
      cursor.execute(
          """UPDATE students
             SET id_number=?, roll_number=?, name=?, grade=?, section=?,
                 blood_group=?, allergies=?, emergency_contact=?,
                 vaccination_history=?, medications=?
             WHERE id=?""",
          (id_num, roll, name, grade, section, blood, allergies, emergency,
           vax, meds, canonical_id),
      )
      # Remove only extra rows that are recognisable as these built-in demo
      # records; retain any unrelated student records.
      for duplicate_id, duplicate_name, duplicate_photo in matches[1:]:
        if duplicate_name in (old_name, new_name):
          if duplicate_photo:
            cursor.execute(
                "UPDATE students SET photo = COALESCE(photo, ?) WHERE id = ?",
                (duplicate_photo, canonical_id),
            )
          cursor.execute("DELETE FROM students WHERE id = ?", (duplicate_id,))
    else:
      cursor.execute(
          """INSERT OR IGNORE INTO students
             (id_number, roll_number, name, grade, section, blood_group,
              allergies, emergency_contact, vaccination_history, medications)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
          (id_num, roll, name, grade, section, blood, allergies, emergency, vax, meds),
      )

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


# --- LOGIN PAGE ---
def login_page():
  st.markdown("<h1 style='text-align: center;'>🏥 School Health Passport</h1>", unsafe_allow_html=True)
  st.markdown("<p style='text-align: center; color: #666;'>School Health & Wellness Portal</p>", unsafe_allow_html=True)

  _, col2, _ = st.columns([1, 2, 1])

  with col2:
    st.markdown("### Sign In Portal")
    with st.expander("ℹ️ Demo Accounts / Hints"):
      st.markdown("""
            **Nurse:** \`nurse@school.com\` / \`password123\`  
            **Teacher:** \`teacher@school.com\` / \`password123\`  
            **Parent:** Select **Parent** and enter your child's **Student ID** (e.g., \`gj_12_6b\`) directly to view their health passport.
            """)

    # Use a callback or session-state bound selectbox to prevent form caching issues
    selected_role = st.selectbox("Select Role", ["Nurse", "Teacher", "Parent"], key="login_role_select")

    with st.form("login_form"):
      if selected_role == "Parent":
        student_id_input = st.text_input("Child's Student ID (e.g., gj_12_6b)", value="gj_12_6b")
      else:
        email = st.text_input("Email Address", value="nurse@school.com" if selected_role == "Nurse" else "teacher@school.com")
        password = st.text_input("Password", type="password", value="password123")

      submit = st.form_submit_button("Sign In")

      if submit:
        conn = get_connection()
        if selected_role == "Nurse":
          st.session_state.user = {"name": "School Nurse", "role": "Nurse", "email": email}
          st.session_state.logged_in = True
          st.rerun()
        elif selected_role == "Teacher":
          st.session_state.user = {"name": "Teacher Portal", "role": "Teacher", "email": email}
          st.session_state.logged_in = True
          st.rerun()
        else:
          # Parent login using Student ID
          student_record = conn.execute("SELECT * FROM students WHERE id_number = ?", (student_id_input.strip().lower(),)).fetchone()
          if student_record:
            st.session_state.user = {
                "name": f"Parent of {student_record[3]}", 
                "role": "Parent", 
                "child_id": student_record[1]
            }
            st.session_state.logged_in = True
            st.rerun()
          else:
            st.error("Invalid Student ID. Please check your child's ID and try again.")
        conn.close()


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
      edit_emergency = st.text_input("Emergency Contact", value=student[8] or "")
      edit_vax = st.text_area("Vaccination History", value=student[9] or "")
      edit_meds = st.text_area("Medications", value=student[10] or "")
      edit_photo = st.file_uploader(
          "Replace Student Photo (optional)",
          type=["jpg", "jpeg", "png", "webp"],
          key=f"{key_prefix}_edit_photo_{student[0]}"
      )
      submitted = st.form_submit_button("Save Changes")
      if submitted:
        if not edit_name.strip():
          st.error("Student name is required.")
        elif edit_photo:
          conn.execute(
              """UPDATE students SET name=?, blood_group=?, allergies=?,
                 emergency_contact=?, vaccination_history=?, medications=?, photo=? WHERE id=?""",
              (edit_name.strip(), edit_blood, edit_allergies, edit_emergency,
               edit_vax, edit_meds, edit_photo.getvalue(), student[0])
          )
          conn.commit()
          st.success("Student health record and photo updated.")
          st.rerun()
        else:
          conn.execute(
              """UPDATE students SET name=?, blood_group=?, allergies=?,
                 emergency_contact=?, vaccination_history=?, medications=? WHERE id=?""",
              (edit_name.strip(), edit_blood, edit_allergies, edit_emergency,
               edit_vax, edit_meds, student[0])
          )
          conn.commit()
          st.success("Student health record updated.")
          st.rerun()


# --- SHARED STUDENT SEARCH ---
def render_student_search(conn, grade=None, section=None, key_prefix="search"):
  """Search student records across all visible health-record fields."""
  st.subheader("Search Student Records")
  st.caption("Search by name, student ID, roll number, grade, section, blood group, allergies, or other health details.")

  query = st.text_input(
      "Search students",
      placeholder="e.g. Diya, Grade 6, B-, pollen, gj_12_6b",
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
          - **Emergency Contact:** {student[8] or 'Not provided'}
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
                    st.success("Student photo updated.")
                    st.rerun()
                  else:
                    st.warning("Choose an image first.")
                st.markdown(f"""
                  - **Student ID:** `{student[1]}`
                  - **Roll Number:** {student[2]}
                  - **Blood Group:** {student[6]}
                  - **Allergies:** {student[7]}
                  - **Emergency Contact:** {student[8]}
                  - **Vaccinations:** {student[9]}
                  - **Medications:** {student[10]}
                """)
              render_student_editor(conn, student, "nurse")
              if st.button("Remove Student (Left School)", key=f"nurse_rem_{student[0]}"):
                conn.execute("DELETE FROM students WHERE id = ?", (student[0],))
                conn.commit()
                st.success(f"Removed {student[3]}")
                st.rerun()
        else:
          st.info(f"No students registered in Grade {g}{sec}.")

  with tab2:
    st.subheader("Add Student Health Record")
    with st.form("add_student_form"):
      s_name = st.text_input("Student Name (e.g., Kabir Malhotra)")
      col_r, col_g, col_s = st.columns(3)
      with col_r:
        s_roll = st.number_input("Roll Number", min_value=1, step=1, value=1)
      with col_g:
        s_grade = st.selectbox("Grade", list(range(1, 13)))
      with col_s:
        s_section = st.selectbox("Section", ["A", "B", "C", "D", "E"])

      s_blood = st.text_input("Blood Group")
      s_emergency = st.text_input("Emergency Contact")
      s_allergies = st.text_area("Allergies")
      s_vax = st.text_area("Vaccination History")
      s_meds = st.text_area("Medications")
      s_photo = st.file_uploader(
          "Upload Student Photo (JPG, JPEG, PNG or WEBP)",
          type=["jpg", "jpeg", "png", "webp"],
          help="Choose a clear photo to help authorised staff identify the student."
      )

      if st.form_submit_button("Save Student Record"):
        if s_name.strip():
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
                 s_allergies, s_emergency, s_vax, s_meds,
                 s_photo.getvalue() if s_photo else None),
            )
            conn.commit()
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
            st.success(f"Message sent to {target_audience} successfully!")
            st.rerun()

  conn.close()


# --- TEACHER DASHBOARD ---
def teacher_dashboard():
  st.markdown("## 📚 Teacher Dashboard — Class Roster & Health Records")

  with st.container():
    st.markdown("### ⚙️ Select Your Assigned Class")
    col1, col2 = st.columns(2)
    with col1:
      selected_grade = st.selectbox(
          "Select Grade", list(range(1, 13)),
          index=st.session_state.teacher_grade - 1, key="t_grade_sel"
      )
    with col2:
      sections_list = ["A", "B", "C", "D", "E"]
      selected_section = st.selectbox(
          "Select Section", sections_list,
          index=sections_list.index(st.session_state.teacher_section), key="t_sec_sel"
      )

    st.session_state.teacher_grade = selected_grade
    st.session_state.teacher_section = selected_section

  grade = st.session_state.teacher_grade
  section = st.session_state.teacher_section
  st.markdown("---")
  st.markdown(f"### Currently Managing: **Grade {grade}{section}**")

  conn = get_connection()
  tab1, tab2, tab3, tab4 = st.tabs([
      "👥 Class Roster",
      "➕ Add/Remove Students",
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
            updated_photo = st.file_uploader(
              "Upload / Replace Student Photo",
              type=["jpg", "jpeg", "png", "webp"],
                key=f"teacher_photo_{student[0]}"
            )
            if st.button("Save Photo", key=f"teacher_save_photo_{student[0]}"):
              if updated_photo:
                conn.execute("UPDATE students SET photo = ? WHERE id = ?", (updated_photo.getvalue(), student[0]))
                conn.commit()
                st.success("Student photo updated.")
                st.rerun()
              else:
                st.warning("Choose an image first.")
            st.markdown(f"""
              - **Student ID:** `{student[1]}`
              - **Roll Number:** {student[2]}
              - **Allergies:** {student[7]}
              - **Emergency Contact:** {student[8]}
            """)
            render_student_editor(conn, student, "teacher")
    else:
      st.info(f"No students found in Grade {grade}{section}. Use the 'Add/Remove Students' tab to add your class list.")

  with tab2:
    st.subheader(f"Manage Students in Grade {grade}{section}")
    with st.form("teacher_add_student"):
      t_name = st.text_input("Student Name")
      t_roll = st.number_input("Roll Number", min_value=1, step=1, value=1)
      t_blood = st.text_input("Blood Group")
      t_emergency = st.text_input("Emergency Contact")
      t_allergies = st.text_area("Allergies")
      t_vax = st.text_area("Vaccination History")
      t_meds = st.text_area("Medications")
      t_photo = st.file_uploader(
          "Upload Student Photo (JPG, JPEG, PNG or WEBP)",
          type=["jpg", "jpeg", "png", "webp"],
          help="Choose a clear photo to help authorised staff identify the student.",
          key="teacher_student_photo"
      )

      if st.form_submit_button("Add Student to My Class"):
        if t_name.strip():
          t_id_num = generate_roll_id(t_roll, grade, section)
          try:
            conn.execute(
                """
                INSERT INTO students
                (id_number, roll_number, name, grade, section, blood_group,
                 allergies, emergency_contact, vaccination_history, medications, photo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (t_id_num, t_roll, t_name.strip(), grade, section, t_blood,
                 t_allergies, t_emergency, t_vax, t_meds,
                 t_photo.getvalue() if t_photo else None),
            )
            conn.commit()
            st.success(f"Added {t_name} with ID `{t_id_num}` to Grade {grade}{section}!")
            st.rerun()
          except sqlite3.IntegrityError:
            st.error(f"Error: Roll number {t_roll} already exists in Grade {grade}{section}.")
        else:
          st.error("Student Name is required.")

    st.markdown("#### Remove Student from Roster")
    students_to_remove = conn.execute(
        "SELECT id, name FROM students WHERE grade = ? AND section = ?",
        (grade, section)
    ).fetchall()
    if students_to_remove:
      student_options = {student[1]: student[0] for student in students_to_remove}
      to_remove = st.selectbox("Select Student to Remove", list(student_options.keys()))
      if st.button("Remove Selected Student"):
        conn.execute("DELETE FROM students WHERE id = ?", (student_options[to_remove],))
        conn.commit()
        st.success(f"Removed {to_remove}")
        st.rerun()

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
          - **Emergency Contact:** {student[8]}
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
      st.session_state.logged_in = False
      st.session_state.user = None
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


if __name__ == "__main__":
  main()
