import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import hashlib
import io
import os
import re
import xlsxwriter
from fpdf import FPDF

# ==========================================
# 1. CONFIGURATION & STYLING
# ==========================================
st.set_page_config(page_title="Smart Scheduler System", layout="wide", page_icon="📅")

st.markdown("""
<style>
    /* Table Styling */
    .schedule-table { width: 100%; border-collapse: separate; border-spacing: 2px; font-family: 'Sarabun', sans-serif; margin-bottom: 20px; background-color: #ffffff; }
    .th-time { background-color: #37474f; color: white; padding: 4px; text-align: center; border-radius: 3px; font-size: 0.75rem; }
    .td-day { background-color: #263238; color: white; font-weight: bold; text-align: center; width: 50px; font-size: 0.85rem; border-radius: 3px; }
    .td-free { background-color: #f5f5f5; border: 1px dashed #e0e0e0; border-radius: 3px; }
    .td-lunch { background-color: #ffcdd2; color: #c62828; writing-mode: vertical-rl; text-align: center; font-size: 0.75rem; border-radius: 3px; font-weight: bold; }
    .td-fixed { background-color: #fff9c4; color: #f9a825; border: 1px solid #fdd835; text-align: center; border-radius: 3px; font-size: 0.8rem; font-weight: bold; }
    .td-activity { background-color: #e1bee7; color: #6a1b9a; border: 1px solid #ce93d8; text-align: center; border-radius: 3px; font-size: 0.8rem; font-weight: bold; }
    
    /* Card Styles */
    .class-card { background: #e3f2fd; border-left: 3px solid #1565c0; padding: 3px; border-radius: 3px; font-size: 0.75rem; overflow: hidden; height: 100%; text-align: left; }
    .class-card-sub { background: #e8f5e9; border-left: 3px solid #2e7d32; } /* สีเขียว: ครูแทน */
    .class-card-extra { background: #fff3e0; border-left: 3px solid #ef6c00; } /* สีส้ม: คาบพิเศษ */
    .class-card-conflict { background: #ffebee; border-left: 3px solid #c62828; color: #b71c1c; font-weight: bold; animation: pulse 2s infinite; }
    
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.8; } 100% { opacity: 1; } }

    .subject-title { font-weight: bold; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: inherit; }
    .subject-detail { font-size: 0.7rem; opacity: 0.8; display: block; }
</style>
""", unsafe_allow_html=True)

DAYS = ['จันทร์', 'อังคาร', 'พุธ', 'พฤหัสบดี', 'ศุกร์']
TIMES = [f"{h:02d}:00-{(h+1):02d}:00" for h in range(8, 21)]

LUNCH_SLOT_INDEX = 4        # 12:00-13:00
HOMEROOM_DAY = 0; HOMEROOM_SLOT = 0
ACTIVITY_DAY = 2; ACTIVITY_SLOTS = [7, 8]

# ==========================================
# 2. AUTHENTICATION & MANAGER
# ==========================================
class AuthManager:
    def __init__(self, db_name='users.db'):
        self.db_name = db_name; self.init_db()
    def init_db(self):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS userstable(username TEXT PRIMARY KEY, password TEXT, role TEXT)')
        conn.commit(); conn.close()
    def make_hashes(self, p): return hashlib.sha256(str.encode(p)).hexdigest()
    def login_user(self, u, p):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute('SELECT * FROM userstable WHERE username = ? AND password = ?', (u, self.make_hashes(p)))
        return c.fetchall()
    def register_user(self, u, p, r='user'):
        try:
            conn = sqlite3.connect(self.db_name); c = conn.cursor()
            c.execute('INSERT INTO userstable(username, password, role) VALUES (?,?,?)', (u, self.make_hashes(p), r))
            conn.commit(); conn.close(); return True
        except: return False

class SmartDataManager:
    def __init__(self):
        self.col_mapping = {
            'subject id': ['subject_id', 'course_id', 'รหัสวิชา'], 
            'subject name': ['subject_name', 'course_name', 'ชื่อวิชา'],
            'teacher id': ['teacher_id', 'instructor_id', 'รหัสครู', 'ครูผู้สอน'],
            'credits': ['credits', 'credit', 'หน่วยกิต', 'ท-ป-น'],
            'group': ['group', 'group_id', 'section', 'class', 'กลุ่มเรียน', 'ห้อง'],
            'room': ['room', 'location', 'สถานที่', 'ห้องเรียน'] # เพิ่ม Mapping ห้องเรียน
        }
    def clean_teacher_name(self, name):
        if not isinstance(name, str): return str(name)
        return re.sub(r'^(นาย|นาง|นางสาว|ดร\.|ผศ\.|รศ\.|ว่าที่ร\.ต\.|อาจารย์|อ\.)', '', name).strip()
    def deduplicate_columns(self, df):
        cols = pd.Series(df.columns)
        for dup in cols[cols.duplicated()].unique(): cols[cols == dup] = [dup + '_' + str(i) if i != 0 else dup for i in range(sum(cols == dup))]
        df.columns = cols; return df
    def find_header_row(self, df):
        max_matches = 0; header_idx = 0; all_kw = [k for v in self.col_mapping.values() for k in v]
        for i in range(min(20, len(df))):
            row_str = [str(x).lower() for x in df.iloc[i].tolist()]
            matches = sum(1 for val in row_str if any(k in val for k in all_kw))
            if matches > max_matches: max_matches = matches; header_idx = i
        return header_idx
    def process_file(self, file_obj, manual_header=None):
        try:
            if file_obj.name.endswith('.csv'): df_raw = pd.read_csv(file_obj, header=None)
            else: df_raw = pd.read_excel(file_obj, header=None)
        except: return None
        idx = manual_header if manual_header is not None else self.find_header_row(df_raw)
        file_obj.seek(0)
        if file_obj.name.endswith('.csv'): df = pd.read_csv(file_obj, header=idx)
        else: df = pd.read_excel(file_obj, header=idx)
        new_cols = {}
        for col in df.columns:
            c_str = str(col).strip().lower()
            for std, kws in self.col_mapping.items():
                if any(k in c_str for k in kws): new_cols[col] = std.title(); break
        df.rename(columns=new_cols, inplace=True)
        
        # Standardize Names
        norm_map = {'Subject Id': 'Subject ID', 'Subject Name': 'Subject Name', 'Teacher Id': 'Teacher ID', 'Credits': 'Credits'}
        df.rename(columns=norm_map, inplace=True); df = self.deduplicate_columns(df)
        if 'Teacher ID' in df.columns: df['Teacher ID'] = df['Teacher ID'].apply(self.clean_teacher_name)
        return df
    
    def smart_merge(self, dfs):
        if not dfs: return pd.DataFrame()
        processed_dfs = []
        for df in dfs:
            if 'Group' in df.columns and 'Subject ID' in df.columns and 'Teacher ID' not in df.columns:
                df_agg = df[['Subject ID', 'Group']].drop_duplicates(); processed_dfs.append(df_agg)
            else: processed_dfs.append(df)
        processed_dfs.sort(key=lambda x: 1 if 'Teacher ID' in x.columns else 0, reverse=True)
        base_df = processed_dfs[0]
        for i in range(1, len(processed_dfs)):
            other_df = processed_dfs[i]
            common = list(set(base_df.columns) & set(other_df.columns))
            if common:
                for col in common: base_df[col] = base_df[col].astype(str); other_df[col] = other_df[col].astype(str)
                base_df = pd.merge(base_df, other_df, on=common, how='left')
            else: base_df = pd.concat([base_df, other_df], ignore_index=True)
        
        base_df.drop_duplicates(subset=['Teacher ID', 'Subject ID', 'Group'], inplace=True)
        
        if 'Group' in base_df.columns:
            mask = base_df['Group'].isna() | (base_df['Group'].astype(str) == 'nan') | (base_df['Group'].astype(str).str.strip() == '')
            if mask.any(): base_df.loc[mask, 'Group'] = [f"NoGroup_{i}" for i in range(mask.sum())]
        
        if 'Subject ID' in base_df.columns and 'Subject Name' not in base_df.columns: base_df['Subject Name'] = base_df['Subject ID']
        if 'Credits' not in base_df.columns: base_df['Credits'] = 2
        if 'Group' not in base_df.columns: base_df['Group'] = 'G-Mix'
        
        # Handle Room Default
        if 'Room' not in base_df.columns: base_df['Room'] = '-'
        else: base_df['Room'] = base_df['Room'].fillna('-')
            
        return base_df

# ==========================================
# 3. DATA INSPECTOR
# ==========================================
def inspect_data(df):
    issues = []
    if 'Group' in df.columns:
        nan_groups = df[df['Group'].isna()]
        if not nan_groups.empty: issues.append({'type': 'Error', 'msg': f"พบวิชากลุ่มเรียนเป็นค่าว่าง (NaN) {len(nan_groups)} รายการ", 'data': nan_groups})
    if 'Teacher ID' in df.columns:
        nan_teachers = df[df['Teacher ID'].isna()]
        if not nan_teachers.empty: issues.append({'type': 'Warning', 'msg': f"พบวิชาไม่มีครูผู้สอน {len(nan_teachers)} รายการ", 'data': nan_teachers})
    return issues

# ==========================================
# 4. SCHEDULER ENGINE
# ==========================================
class CSPScheduler:
    def __init__(self, register_df):
        self.reg_df = register_df.copy()
        self.reg_df['Hours'] = pd.to_numeric(self.reg_df['Credits'], errors='coerce').fillna(2).astype(int)
        
        self.teachers = self.reg_df['Teacher ID'].unique()
        self.groups = self.reg_df['Group'].unique()
        self.t_sched = {t: np.zeros(65, dtype=int) for t in self.teachers}
        self.g_sched = {g: np.zeros(65, dtype=int) for g in self.groups}
        
        self.group_daily_load = {g: np.zeros(5, dtype=int) for g in self.groups}
        self.teacher_load_realtime = self.reg_df.groupby('Teacher ID')['Hours'].sum().to_dict()
        self.subject_teachers_map = self.reg_df.groupby('Subject ID')['Teacher ID'].unique().to_dict()
        
        self.assignments = []
        self.failed = []

    def check(self, tid, gid, slots, allow_lunch=False):
        for s in slots:
            day = s // 13; period = s % 13
            if day == ACTIVITY_DAY and period in ACTIVITY_SLOTS: return False
            if day == HOMEROOM_DAY and period == HOMEROOM_SLOT: return False
            if not allow_lunch and period == LUNCH_SLOT_INDEX: return False
        
        if tid not in self.t_sched: self.t_sched[tid] = np.zeros(65, dtype=int)
        if not all(self.t_sched[tid][s] == 0 for s in slots): return False
        if not all(self.g_sched[gid][s] == 0 for s in slots): return False
        return True

    def book(self, task, slots, actual_tid=None, suffix="", is_extra=False):
        tid = actual_tid if actual_tid else task['Teacher ID']
        gid = task['Group']
        room = task.get('Room', '-')
        
        if tid not in self.t_sched: self.t_sched[tid] = np.zeros(65, dtype=int)
        self.t_sched[tid][slots] = 1; self.g_sched[gid][slots] = 1
        day = slots[0] // 13; period = slots[0] % 13
        self.group_daily_load[gid][day] += len(slots)
        self.teacher_load_realtime[tid] = self.teacher_load_realtime.get(tid, 0) + len(slots)
        
        self.assignments.append({
            'Day': DAYS[day], 'Period': period, 'Time': TIMES[period],
            'Subject Name': str(task.get('Subject Name', '?')) + suffix,
            'Teacher ID': tid, 'Group': gid, 'Room': room,
            'Duration': len(slots),
            'IsSub': True if actual_tid and actual_tid != task['Teacher ID'] else False,
            'IsExtra': is_extra
        })

    def apply_constraints(self):
        for d in range(5):
            idx = d * 13 + LUNCH_SLOT_INDEX
            for t in self.t_sched: self.t_sched[t][idx] = 1
            for g in self.g_sched: self.g_sched[g][idx] = 1
        hr = HOMEROOM_DAY * 13 + HOMEROOM_SLOT
        for t in self.t_sched: self.t_sched[t][hr] = 1
        for g in self.g_sched: self.g_sched[g][hr] = 1
        for s in ACTIVITY_SLOTS:
            act = ACTIVITY_DAY * 13 + s
            for t in self.t_sched: self.t_sched[t][act] = 1
            for g in self.g_sched: self.g_sched[g][act] = 1

    def find_substitute(self, subject_id, original_tid):
        candidates = self.subject_teachers_map.get(subject_id, [])
        candidates = [t for t in candidates if t != original_tid]
        if not candidates: return []
        candidates.sort(key=lambda t: self.teacher_load_realtime.get(t, 0))
        return candidates

    def try_allocate(self, task, tid, gid, dur, allow_split=True, allow_lunch=False, max_period=12):
        days_sorted = sorted(range(5), key=lambda d: self.group_daily_load[gid][d])
        for day in days_sorted:
            start = day * 13
            for p in range(max_period - dur + 1):
                slots = range(start + p, start + p + dur)
                if self.check(tid, gid, slots, allow_lunch): return slots, None
        
        if allow_split and dur > 2:
            half = dur // 2; rem = dur - half
            s1 = None; s2 = None
            days_split = sorted(range(5), key=lambda d: self.group_daily_load[gid][d])
            for d1 in days_split:
                st1 = d1 * 13
                for p in range(max_period - half + 1):
                    sl = range(st1 + p, st1 + p + half)
                    if self.check(tid, gid, sl, allow_lunch): s1 = sl; break
                if s1: break
            if s1:
                if tid not in self.t_sched: self.t_sched[tid] = np.zeros(65, dtype=int)
                t_orig = self.t_sched[tid][s1].copy(); g_orig = self.g_sched[gid][s1].copy()
                self.t_sched[tid][s1] = 1; self.g_sched[gid][s1] = 1
                for d2 in days_split:
                    st2 = d2 * 13
                    for p in range(max_period - rem + 1):
                        sl = range(st2 + p, st2 + p + rem)
                        if self.check(tid, gid, sl, allow_lunch): s2 = sl; break
                    if s2: break
                self.t_sched[tid][s1] = t_orig; self.g_sched[gid][s1] = g_orig
                if s2: return s1, s2
        return None, None

    def analyze_failure(self, task):
        tid, gid = task['Teacher ID'], task['Group']
        t_free = 65 - np.sum(self.t_sched[tid]) if tid in self.t_sched else 65
        g_free = 65 - np.sum(self.g_sched[gid])
        if t_free < task['Hours']: return f"Teacher Full (Free {t_free})"
        elif g_free < task['Hours']: return f"Group Full (Free {g_free})"
        else: return "Time Conflict"

    def solve(self):
        self.apply_constraints()
        tasks = self.reg_df.to_dict('records')
        group_load_map = self.reg_df.groupby('Group')['Hours'].sum().to_dict()
        tasks.sort(key=lambda x: (self.teacher_load_realtime.get(x['Teacher ID'], 0), group_load_map.get(x['Group'], 0), x['Hours']), reverse=True)

        for task in tasks:
            org_tid, gid, dur = task['Teacher ID'], task['Group'], task['Hours']
            allocated = False
            
            # 1. Standard
            s1, s2 = self.try_allocate(task, org_tid, gid, dur)
            if s1 or s2:
                if s1 and not s2: self.book(task, s1)
                else: self.book(task, s1, suffix=" (1)"); self.book(task, s2, suffix=" (2)")
                allocated = True
            
            # 2. Substitute
            if not allocated:
                substitutes = self.find_substitute(task['Subject ID'], org_tid)
                for sub_tid in substitutes:
                    s1_sub, s2_sub = self.try_allocate(task, sub_tid, gid, dur)
                    if s1_sub or s2_sub:
                        sub_suf = f" (แทน {sub_tid})"
                        if s1_sub and not s2_sub: self.book(task, s1_sub, actual_tid=sub_tid, suffix=sub_suf)
                        else: self.book(task, s1_sub, actual_tid=sub_tid, suffix=sub_suf+"(1)"); self.book(task, s2_sub, actual_tid=sub_tid, suffix=sub_suf+"(2)")
                        allocated = True; break
            
            # 3. Liquid Fill
            if not allocated:
                slots_collected = []
                temp_sched_t = self.t_sched[org_tid].copy() if org_tid in self.t_sched else np.zeros(65, int)
                temp_sched_g = self.g_sched[gid].copy()
                for _ in range(dur):
                    found_slot = None
                    for d in range(5):
                        st_idx = d * 13
                        for p in range(13): 
                            curr = st_idx + p
                            if self.check(org_tid, gid, [curr], allow_lunch=False) and temp_sched_t[curr] == 0 and temp_sched_g[curr] == 0:
                                found_slot = [curr]; temp_sched_t[curr] = 1; temp_sched_g[curr] = 1; break
                        if found_slot: break
                    if found_slot: slots_collected.append(found_slot)
                if len(slots_collected) == dur:
                    for idx, slot in enumerate(slots_collected): self.book(task, slot, suffix=f"({idx+1}/{dur})", is_extra=True)
                    allocated = True
            
            # 4. Desperate (Lunch/Evening)
            if not allocated:
                s1, s2 = self.try_allocate(task, org_tid, gid, dur, allow_lunch=True, max_period=13)
                if s1 or s2:
                    suffix_extra = " (พิเศษ)"
                    if s1 and not s2: self.book(task, s1, suffix=suffix_extra, is_extra=True)
                    else: self.book(task, s1, suffix=suffix_extra+"(1)", is_extra=True); self.book(task, s2, suffix=suffix_extra+"(2)", is_extra=True)
                    allocated = True

            # 5. Ext Substitute
            if not allocated:
                substitutes = self.find_substitute(task['Subject ID'], org_tid)
                for sub_tid in substitutes:
                    s1_sub, s2_sub = self.try_allocate(task, sub_tid, gid, dur, allow_lunch=True, max_period=13)
                    if s1_sub or s2_sub:
                        sub_suf = f" (แทน {sub_tid} พิเศษ)"
                        if s1_sub and not s2_sub: self.book(task, s1_sub, actual_tid=sub_tid, suffix=sub_suf, is_extra=True)
                        else: self.book(task, s1_sub, actual_tid=sub_tid, suffix=sub_suf+"(1)", is_extra=True); self.book(task, s2_sub, actual_tid=sub_tid, suffix=sub_suf+"(2)", is_extra=True)
                        allocated = True; break

            if not allocated:
                task['Reason'] = self.analyze_failure(task)
                self.failed.append(task)
            
        return pd.DataFrame(self.assignments), self.failed

# ==========================================
# 5. REPORT GENERATOR (Enhanced for Room View)
# ==========================================
class ReportGenerator:
    def export_excel(self, df):
        output = io.BytesIO(); writer = pd.ExcelWriter(output, engine='xlsxwriter')
        df.to_excel(writer, sheet_name='All', index=False)
        for t in df['Teacher ID'].unique():
            safe = re.sub(r'[\\/*?:\[\]]', "", str(t))[:30]
            df[df['Teacher ID'] == t].to_excel(writer, sheet_name=safe, index=False)
        writer.close(); return output
    
    def _create_pdf_page(self, pdf, df, title, mode, font_ready):
        pdf.add_page()
        margin = 10; day_w = 20; col_w = 19; row_h = 22; header_h = 8
        
        pdf.set_font_size(16); pdf.cell(0, 10, title, ln=True, align='C')
        pdf.set_font_size(10 if font_ready else 8)
        
        pdf.set_x(margin + day_w)
        for t in TIMES[:13]: pdf.cell(col_w, header_h, t.split('-')[0], 1, 0, 'C')
        pdf.ln(header_h)
        
        for d_idx, day in enumerate(DAYS):
            pdf.set_x(margin); pdf.cell(day_w, row_h, day, 1, 0, 'C')
            skip = 0
            for p in range(13):
                if skip > 0: skip -= 1; continue
                is_lunch = (p == LUNCH_SLOT_INDEX); is_hr = (d_idx == HOMEROOM_DAY and p == HOMEROOM_SLOT); is_act = (d_idx == ACTIVITY_DAY and p in ACTIVITY_SLOTS)
                match = df[(df['Day'] == day) & (df['Period'] == p)]
                x_curr = pdf.get_x(); y_curr = pdf.get_y()
                
                if not match.empty:
                    info = match.iloc[0]; dur = info['Duration']
                    subj = str(info['Subject Name'])[:15]
                    
                    # Logic for displaying text based on mode
                    line2 = ""
                    if mode == "Teacher": line2 = str(info['Group'])
                    elif mode == "Group": line2 = str(info['Teacher ID'])
                    elif mode == "Room": line2 = f"{str(info['Teacher ID'])}\n{str(info['Group'])}"
                    
                    if len(line2) > 12 and mode != "Room": line2 = line2[:10] + ".." 
                    
                    pdf.set_fill_color(220, 240, 255)
                    pdf.cell(col_w * dur, row_h, "", 1, 0, 'C', fill=True)
                    pdf.set_xy(x_curr, y_curr + 4)
                    pdf.multi_cell(col_w * dur, 4, f"{subj}\n{line2}", 0, 'C')
                    pdf.set_xy(x_curr + (col_w * dur), y_curr)
                    skip = dur - 1
                elif is_hr:
                    pdf.set_fill_color(255, 249, 196); pdf.cell(col_w, row_h, "HR", 1, 0, 'C', fill=True)
                elif is_act:
                    pdf.set_fill_color(225, 190, 231); pdf.cell(col_w, row_h, "Act", 1, 0, 'C', fill=True)
                elif is_lunch:
                    pdf.set_fill_color(255, 205, 210); pdf.cell(col_w, row_h, "Lunch", 1, 0, 'C', fill=True)
                else:
                    pdf.cell(col_w, row_h, "", 1, 0, 'C')
            pdf.ln(row_h)

    def export_pdf_grid(self, df, title, mode):
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        font_path = 'THSarabunNew.ttf'
        font_ready = os.path.exists(font_path)
        if font_ready: 
            pdf.add_font('THSarabunNew', '', font_path, uni=True); pdf.set_font('THSarabunNew', '', 10)
        else: pdf.set_font('Arial', '', 8)
        
        self._create_pdf_page(pdf, df, title, mode, font_ready)
        return pdf.output(dest='S').encode('latin-1')

    def export_all_pdfs(self, df):
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        font_path = 'THSarabunNew.ttf'
        font_ready = os.path.exists(font_path)
        if font_ready: 
            pdf.add_font('THSarabunNew', '', font_path, uni=True); pdf.set_font('THSarabunNew', '', 10)
        else: pdf.set_font('Arial', '', 8)
        
        # 1. Teachers
        teachers = sorted(df['Teacher ID'].unique())
        for t in teachers:
            sub = df[df['Teacher ID'] == t]
            self._create_pdf_page(pdf, sub, f"Schedule: Teacher {t}", "Teacher", font_ready)
            
        # 2. Groups
        groups = sorted(df['Group'].unique())
        for g in groups:
            sub = df[df['Group'] == g]
            self._create_pdf_page(pdf, sub, f"Schedule: Group {g}", "Group", font_ready)
            
        return pdf.output(dest='S').encode('latin-1')

def render_timetable_html(df, title, mode):
    html_rows = ""
    for day_idx, day in enumerate(DAYS):
        html_rows += f"<tr><td class='td-day'>{day}</td>"
        skip = 0
        for p in range(13):
            if skip > 0: skip -= 1; continue
            match = df[(df['Day'] == day) & (df['Period'] == p)]
            if match.empty:
                if p == LUNCH_SLOT_INDEX: html_rows += "<td class='td-lunch'>พัก</td>"; continue
                if day_idx == HOMEROOM_DAY and p == HOMEROOM_SLOT: html_rows += "<td class='td-fixed'>โฮมรูม</td>"; continue
                if day_idx == ACTIVITY_DAY and p in ACTIVITY_SLOTS:
                    if p == ACTIVITY_SLOTS[0]: html_rows += f"<td class='td-activity' colspan='{len(ACTIVITY_SLOTS)}'>กิจกรรม</td>"; skip = len(ACTIVITY_SLOTS) - 1
                    continue
                html_rows += "<td class='td-free'></td>"
            else:
                info = match.iloc[0]; dur = info['Duration']
                subj = info['Subject Name']
                
                # Show Details based on View
                if mode == "ครูผู้สอน": det = info['Group']
                elif mode == "กลุ่มเรียน": det = info['Teacher ID']
                elif mode == "ห้องเรียน": det = f"{info['Teacher ID']} / {info['Group']}"
                
                is_sub = info.get('IsSub', False); is_extra = info.get('IsExtra', False)
                card_class = "class-card"
                if is_sub: card_class += " class-card-sub"
                if is_extra: card_class += " class-card-extra"
                card = f"<div class='{card_class}'><span class='subject-title'>{subj}</span><span class='subject-detail'>{det}</span></div>"
                html_rows += f"<td class='td-cell' colspan='{dur}' style='padding:0;'>{card}</td>"; skip = dur - 1
        html_rows += "</tr>"
    st.markdown(f"<div style='margin-bottom:10px;font-weight:bold;font-size:1.2rem;color:#2c3e50;'>{title}</div><table class='schedule-table'><thead><tr><th class='th-time' style='width:80px;'>Day/Time</th>{''.join([f"<th class='th-time'>{t.split('-')[0]}</th>" for t in TIMES[:13]])}</tr></thead><tbody>{html_rows}</tbody></table>", unsafe_allow_html=True)

# ==========================================
# 6. MAIN APP
# ==========================================
def main():
    if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
    auth = AuthManager()

    if not st.session_state['logged_in']:
        st.title("🔐 Smart Scheduler System")
        tab1, tab2 = st.tabs(["เข้าสู่ระบบ", "สมัครสมาชิก"])
        with tab1:
            u, p = st.text_input("Username"), st.text_input("Password", type="password")
            if st.button("เข้าสู่ระบบ"):
                user = auth.login_user(u, p)
                if user: st.session_state['logged_in'] = True; st.session_state['username'] = u; st.rerun()
                else: st.error("ไม่ถูกต้อง")
        with tab2:
            nu, np_ = st.text_input("New User"), st.text_input("New Pass", type="password")
            if st.button("สมัครสมาชิก"):
                if auth.register_user(nu, np_): st.success("สำเร็จ")
                else: st.warning("ซ้ำ")
        return

    st.sidebar.title(f"👤 {st.session_state['username']}")
    if st.sidebar.button("Logout"): st.session_state['logged_in'] = False; st.rerun()

    st.title("📅 Smart Scheduler System")

    uploaded_files = st.file_uploader("1. อัปโหลดไฟล์", type=['xlsx','csv'], accept_multiple_files=True)
    with st.expander("🛠️ ตั้งค่าการอ่านไฟล์"):
        manual_header = st.number_input("เลือกบรรทัดหัวตาราง", 0, 20, 0)
        force_load = st.checkbox("บังคับใช้")

    if uploaded_files:
        dm = SmartDataManager()
        all_dfs = []
        for f in uploaded_files:
            h_idx = manual_header if force_load else None
            d = dm.process_file(f, manual_header=h_idx)
            if d is not None: all_dfs.append(d)
        
        if all_dfs:
            combined_df = dm.smart_merge(all_dfs)
            # FIX: Auto-Name NaN Groups
            if 'Group' in combined_df.columns:
                mask = combined_df['Group'].isna() | (combined_df['Group'].astype(str) == 'nan') | (combined_df['Group'].astype(str).str.strip() == '')
                if mask.any():
                    st.toast(f"Auto-fixing {mask.sum()} missing groups", icon="🔧")
                    combined_df.loc[mask, 'Group'] = [f"NoGroup_{i}" for i in range(mask.sum())]

            req = ['Subject ID', 'Teacher ID']
            missing = [c for c in req if c not in combined_df.columns]
            
            if missing:
                st.error(f"❌ ข้อมูลไม่ครบ: {missing}")
                cols = ["(เลือก)"] + list(combined_df.columns); mapping = {}
                with st.form("map_form"):
                    for m in missing: mapping[m] = st.selectbox(f"{m} คือคอลัมน์ไหน?", cols)
                    if st.form_submit_button("ยืนยัน"):
                        rename = {v:k for k,v in mapping.items() if v != "(เลือก)"}
                        combined_df.rename(columns=rename, inplace=True); st.session_state['fixed_df'] = combined_df; st.rerun()
            else: st.session_state['fixed_df'] = combined_df

    if 'fixed_df' in st.session_state:
        df = st.session_state['fixed_df']
        st.divider(); st.subheader("📊 วิเคราะห์ความสมบูรณ์")
        
        # INSPECT DATA
        issues = inspect_data(df)
        if issues:
            for issue in issues:
                if issue['type'] == 'Error': st.error(issue['msg']); st.dataframe(issue['data'].head())
                else: st.warning(issue['msg'])
        
        if 'Credits' not in df.columns: df['Credits'] = 2
        if 'Group' not in df.columns: df['Group'] = 'G-' + df['Teacher ID'].astype(str)
        
        df['Hours'] = pd.to_numeric(df['Credits'], errors='coerce').fillna(2)
        load_t = df.groupby('Teacher ID')['Hours'].sum().sort_values(ascending=False)
        overloaded_t = load_t[load_t > 50]
        load_g = df.groupby('Group')['Hours'].sum().sort_values(ascending=False)
        overloaded_g = load_g[load_g > 45]

        c1, c2 = st.columns(2)
        c1.metric("จำนวนวิชา", len(df)); c2.metric("จำนวนครู", len(load_t))
        
        if not overloaded_t.empty:
            st.error(f"🚨 พบครูสอนหนักเกิน 50 คาบ: {len(overloaded_t)} คน")
            st.dataframe(overloaded_t, use_container_width=True)
        if not overloaded_g.empty:
            st.error(f"🚨 พบกลุ่มเรียนหนักเกิน 45 คาบ: {len(overloaded_g)} กลุ่ม")
            st.dataframe(overloaded_g, use_container_width=True)
        if overloaded_t.empty and overloaded_g.empty:
            st.success("✅ ภาระงานปกติ")
        
        st.write("---")
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        
        if st.button("🚀 เริ่มจัดตารางสอน (Smart Mode)", type="primary", use_container_width=True):
            with st.spinner("AI กำลังจัดตาราง... (Substitute + Liquid Fill + Extended)"):
                scheduler = CSPScheduler(edited_df)
                res, failed = scheduler.solve()
                st.session_state['res'] = res; st.session_state['fail'] = failed; st.success("เสร็จสิ้น!")

    if 'res' in st.session_state:
        res, fail = st.session_state['res'], st.session_state['fail']
        st.divider(); st.subheader("ผลลัพธ์การจัดตาราง")
        c1, c2 = st.columns(2)
        c1.metric("✅ จัดได้ (คาบ)", len(res)); c2.metric("❌ ตกหล่น (วิชา)", len(fail))
        
        if fail:
            with st.expander("🔍 ดูสาเหตุวิชาที่ตกหล่น"):
                st.dataframe(pd.DataFrame(fail)[['Subject Name', 'Teacher ID', 'Group', 'Reason']], use_container_width=True)
        
        if not res.empty:
            res['Teacher ID'] = res['Teacher ID'].astype(str); res['Group'] = res['Group'].astype(str)
            # Added "ห้องเรียน" Mode
            mode = st.radio("เลือกมุมมอง", ["ครูผู้สอน", "กลุ่มเรียน", "ห้องเรียน"], horizontal=True)
            
            # View Selection Logic
            if mode == "ครูผู้สอน":
                items = sorted(res['Teacher ID'].unique())
                sel = st.selectbox("เลือกครู:", items); subset = res[res['Teacher ID'] == sel]
                pdf_mode = "Teacher"
            elif mode == "กลุ่มเรียน":
                items = sorted(res['Group'].unique())
                sel = st.selectbox("เลือกกลุ่ม:", items); subset = res[res['Group'] == sel]
                pdf_mode = "Group"
            else: # ห้องเรียน
                if 'Room' in res.columns:
                    items = sorted(res['Room'].unique())
                    sel = st.selectbox("เลือกห้อง:", items); subset = res[res['Room'] == sel]
                    pdf_mode = "Room"
                else:
                    st.warning("ไม่พบข้อมูลห้องเรียนในไฟล์ที่อัปโหลด"); subset = pd.DataFrame()
                    pdf_mode = None

            if not subset.empty:
                render_timetable_html(subset, f"ตารางสอน: {sel}", mode)
                
                # Context-specific Buttons
                rg = ReportGenerator()
                c1, c2 = st.columns(2)
                c1.download_button(f"📄 โหลด PDF ({sel})", rg.export_pdf_grid(subset, f"Table: {sel}", pdf_mode), f"{sel}.pdf")
                c2.download_button("💾 โหลด Excel", rg.export_excel(subset), f"{sel}.xlsx")
            
            st.write("---")
            # Global Export Button
            st.download_button("📥 ดาวน์โหลดตารางสอนทั้งหมด (All PDF)", ReportGenerator().export_all_pdfs(res), "all_schedules.pdf", type="primary", use_container_width=True)

if __name__ == "__main__":
    main()

