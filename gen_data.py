import pandas as pd
import random
import os

# --- 1. ตั้งค่า ---
NUM_TEACHERS = 200
NUM_SUBJECTS = 400
NUM_ROOMS = 200
STUDENTS_PER_GROUP_MIN = 10
STUDENTS_PER_GROUP_MAX = 40

# --- 2. ตั้งค่าตำแหน่งเซฟไฟล์ (ไว้บน Desktop ให้หาง่ายๆ) ---
desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
output_folder = os.path.join(desktop_path, "Generated_CSV_Files")

if not os.path.exists(output_folder):
    os.makedirs(output_folder)

print(f"📂 กำลังสร้างไฟล์ข้อมูลไว้ที่: {output_folder}")
print("⏳ กำลังประมวลผล... กรุณารอสักครู่")

# --- ข้อมูลตั้งต้น ---
first_names = ["สมชาย", "สมหญิง", "มานะ", "มานี", "ปิติ", "ชูใจ", "วีระ", "สุดา", "อำนาจ", "วารี", "กานดา", "วิชัย", "ณเดชน์", "ญาญ่า", "สมศักดิ์", "ธีรเดช", "พัชราภา", "อารยา", "โทนี่", "บรูซ", "คลาร์ก", "ปีเตอร์", "สตีฟ", "นาตาชา"]
last_names = ["ใจดี", "รักเรียน", "อดทน", "มีสุข", "เจริญ", "มั่นคง", "พากเพียร", "วิชาการ", "เก่งกล้า", "สะอาด", "วงษ์คำเหลา", "มีชัย", "วงศ์สวัสดิ์", "รัตนากร", "จันทร์โอชา", "ชินวัตร", "เวชชาชีวะ", "ลิ้มทองกุล", "ธนาธร", "พิธา"]

departments = {
    "IT": {"code": "401", "name": "Information Tech"},
    "AC": {"code": "201", "name": "Accounting"},
    "MKT": {"code": "202", "name": "Marketing"},
    "EL": {"code": "104", "name": "Electronics"},
    "ME": {"code": "101", "name": "Mechanic"},
    "CV": {"code": "106", "name": "Civil Construction"},
    "LOG": {"code": "203", "name": "Logistics"},
    "ARC": {"code": "108", "name": "Architecture"}
}

group_types = [
    {"code": "M6", "name": "M.6"},
    {"code": "Normal", "name": "Normal"},
    {"code": "Dual", "name": "Dual System"}
]

# --- เริ่มสร้างข้อมูล ---

# 1. TEACHER
teachers = []
for i in range(1, NUM_TEACHERS + 1):
    tid = f"T{i:03d}" # รหัส 3 หลัก T001
    tname = f"{random.choice(first_names)} {random.choice(last_names)}"
    role = "Leader" if i <= (NUM_TEACHERS * 0.1) else "Teacher"
    teachers.append([tid, tname, role])

df_teachers = pd.DataFrame(teachers, columns=["teacher_id", "teacher_name", "role"])
df_teachers.to_csv(os.path.join(output_folder, "teacher.csv"), index=False, encoding='utf-8-sig')

# 2. SUBJECT
subjects = []
for i in range(NUM_SUBJECTS):
    level = random.choice(["2", "3"])
    sType = str(random.randint(0, 3))
    sCode = f"{random.randint(0, 999):03d}"
    sGroup = str(random.randint(1, 9))
    sid = f"{level}{sType}{sCode}-{sGroup}{random.randint(100, 999)}"
    dept_key = random.choice(list(departments.keys()))
    sname = f"วิชา {departments[dept_key]['name']} {sCode}"
    subjects.append([sid, sname, random.randint(1, 3), random.randint(2, 4), random.randint(1, 3)])

df_subjects = pd.DataFrame(subjects, columns=["subject_id", "subject_name", "theory", "practice", "credit"])
df_subjects.to_csv(os.path.join(output_folder, "subject.csv"), index=False, encoding='utf-8-sig')

# 3. ROOM
rooms = []
for i in range(NUM_ROOMS):
    building = random.randint(1, 15)
    floor = random.randint(1, 8)
    room_num = random.randint(1, 20)
    rid = f"{building}{floor}{room_num:02d}"
    rname = rid
    rtype = random.choice(["Lecture Room", "Computer Lab", "Workshop", "Auditorium", "Meeting Room"])
    rooms.append(["R" + rid, rname, rtype])

df_rooms = pd.DataFrame(rooms, columns=["room_id", "room_name", "room_type"])
df_rooms.to_csv(os.path.join(output_folder, "room.csv"), index=False, encoding='utf-8-sig')

# 4. GROUP, STUDENT, REGISTER
groups = []
students = []
registers = []
group_counter = 1

for dept_key, dept_val in departments.items():
    for level_name, level_code in [("ปวช.", "2"), ("ปวส.", "3")]:
        years = [1, 2, 3] if level_name == "ปวช." else [1, 2]
        for y in years:
            # เพิ่มจำนวนห้องต่อชั้นปีเป็น 3-6 ห้อง เพื่อให้ได้ข้อมูลเยอะ
            num_groups_in_year = random.randint(3, 6)
            for g_num in range(1, num_groups_in_year + 1): 
                gid = f"G{group_counter}"
                g_type = random.choice(group_types)
                g_name = f"{level_name}{y}/{g_num}-{dept_key}-{g_type['code']}"
                advisor = random.choice(teachers)[1]
                s_count = random.randint(STUDENTS_PER_GROUP_MIN, STUDENTS_PER_GROUP_MAX)
                
                groups.append([gid, g_name, s_count, advisor])
                
                # Students
                for s_idx in range(1, s_count + 1):
                    enroll_year = "67" if y == 1 else ("66" if y == 2 else "65")
                    full_sid = f"{enroll_year}{level_code}1{dept_val['code']}{g_num:02d}{s_idx:02d}"
                    s_name = f"{random.choice(first_names)} {random.choice(last_names)}"
                    reg_sub_name = f"Major {dept_key}"
                    students.append([full_sid, s_name, reg_sub_name, dept_key, f"{level_name}{y}", gid, g_type['code']])

                # Registers (1 group learns 5-8 subjects)
                chosen_subjects = random.sample(subjects, random.randint(5, 8))
                for sub in chosen_subjects:
                    registers.append([gid, sub[0]])

                group_counter += 1

df_groups = pd.DataFrame(groups, columns=["group_id", "group_name", "student_count", "advisor"])
df_groups.to_csv(os.path.join(output_folder, "student_group.csv"), index=False, encoding='utf-8-sig')

df_students = pd.DataFrame(students, columns=["student_id", "student_name", "registered_subject", "department", "year", "group_id", "extra_condition"])
df_students.to_csv(os.path.join(output_folder, "student.csv"), index=False, encoding='utf-8-sig')

df_registers = pd.DataFrame(registers, columns=["group_id", "subject_id"])
df_registers.to_csv(os.path.join(output_folder, "register.csv"), index=False, encoding='utf-8-sig')

# 5. TIMESLOT
timeslots = []
tid_counter = 1
days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
periods = [
    (1, "08:00", "09:00"), (2, "09:00", "10:00"), (3, "10:00", "11:00"), (4, "11:00", "12:00"),
    (5, "13:00", "14:00"), (6, "14:00", "15:00"), (7, "15:00", "16:00"), (8, "16:00", "17:00"),
    (9, "17:00", "18:00")
]
for d in days:
    for p_num, start, end in periods:
        timeslots.append([tid_counter, d, p_num, start, end])
        tid_counter += 1
df_timeslots = pd.DataFrame(timeslots, columns=["timeslot_id", "day", "period", "start", "end"])
df_timeslots.to_csv(os.path.join(output_folder, "timeslot.csv"), index=False, encoding='utf-8-sig')

# 6. TEACH
teach_recs = []
for t in teachers:
    my_subjects = random.sample(subjects, random.randint(1, 5))
    for sub in my_subjects:
        teach_recs.append([t[0], sub[0]])
df_teach = pd.DataFrame(teach_recs, columns=["teacher_id", "subject_id"])
df_teach.to_csv(os.path.join(output_folder, "teach.csv"), index=False, encoding='utf-8-sig')

# --- เสร็จสิ้น ---
print("\n" + "="*50)
print(f"✅ สร้างข้อมูลเสร็จสิ้นเรียบร้อย!")
print(f"📊 สรุปจำนวนข้อมูลที่สร้างได้:")
print(f"   - Students: {len(df_students)} คน")
print(f"   - Groups:   {len(df_groups)} ห้อง")
print(f"   - Teachers: {len(df_teachers)} คน")
print(f"   - Subjects: {len(df_subjects)} วิชา")
print(f"\n📂 ไฟล์ทั้งหมดอยู่ในโฟลเดอร์: {output_folder}")
print("="*50)