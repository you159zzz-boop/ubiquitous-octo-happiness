import streamlit as st
import pandas as pd
import numpy as np
import io
import time
from fpdf import FPDF
import xlsxwriter

# ==========================================
# 1. CONFIGURATION & STYLING
# ==========================================
st.set_page_config(page_title="Pro AI Scheduler (Final Fix)", layout="wide", page_icon="📅")

st.markdown("""
<style>
    .reportview-container { background: #f0f2f6 }
    table { width: 100%; border-collapse: collapse; }
    th { background-color: #2c3e50; color: white; padding: 10px; text-align: center; }
    td { border: 1px solid #ddd; padding: 8px; text-align: center; vertical-align: middle; }
    tr:nth-child(even) { background-color: #f8f9fa; }
    tr:hover { background-color: #e9ecef; }
    .stAlert { padding: 10px; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

# Default Constants (Will be overwritten if timeslot file is present)
DEFAULT_DAYS = ['จันทร์', 'อังคาร', 'พุธ', 'พฤหัสบดี', 'ศุกร์']
DEFAULT_TIMES = ["08:30-09:30", "09:30-10:30", "10:30-11:30", "11:30-12:30", 
                 "12:30-13:30", "13:30-14:30", "14:30-15:30", "15:30-16:30"]
DEFAULT_ROOMS = [f"R-{101+i}" for i in range(10)]

# ==========================================
# 2. INTELLIGENT DATA MANAGER (Collision Fixed)
# ==========================================
class DataManager:
    def __init__(self):
        self.logs = []
        self.raw_preview = {}
        self.timeslot_config = {'labels': DEFAULT_TIMES, 'count': 8}
        
        # Mapping Dictionary: เรียงลำดับคำที่ "ยาวกว่า/เฉพาะเจาะจงกว่า" ไว้ด้านบน
        # เพื่อป้องกันการ map ผิด (เช่น เจอ teacher_name แล้วไป map เป็น teacher_id)
        self.col_mapping_rules = [
            ('teacher_name', ['teacher_name', 't_name', 'instructor_name', 'ชื่อสกุล', 'ชื่อครู', 'ชื่ออาจารย์', 'ชื่อผู้สอน']),
            ('teacher_id', ['teacher_id', 't_id', 'instructor_id', 'teacher', 'instructor', 'ครู', 'อาจารย์', 'รหัสครู', 'ผู้สอน']),
            ('subject_name', ['subject_name', 'course_name', 'subj_name', 'ชื่อวิชา', 'รายวิชา', 'ชื่อ']),
            ('subject_id', ['subject_id', 'course_id', 'subj_id', 'code', 'subject', 'วิชา', 'รหัสวิชา']),
            ('group_id', ['group_id', 'class_id', 'sec', 'section', 'group', 'กลุ่ม', 'รหัสกลุ่ม', 'ชั้นเรียน', 'ห้องเรียน']),
            ('room_id', ['room_id', 'room_name', 'room', 'place', 'location', 'สถานที่', 'รหัสห้อง', 'ห้อง']),
            ('theory', ['theory', 'ทฤษฎี', 'ท']),
            ('practice', ['practice', 'ปฏิบัติ', 'ป']),
            # Timeslot specific
            ('start_time', ['start', 'begin', 'เวลาเริ่ม', 'เริ่ม']),
            ('end_time', ['end', 'finish', 'เวลาสิ้นสุด', 'เลิก', 'ถึง'])
        ]

    def log(self, msg, type='info'):
        timestamp = time.strftime("%H:%M:%S")
        self.logs.append((timestamp, type, msg))

    def clean_text(self, text):
        if isinstance(text, str): return text.strip()
        return text

    def remove_prefixes(self, name):
        if not isinstance(name, str): return name
        prefixes = ['นาย', 'นางสาว', 'นาง', 'ว่าที่ร.ต.', 'ดร.', 'ผศ.', 'รศ.', 'อ.', 'อาจารย์', 'Mr.', 'Ms.', 'Mrs.']
        for p in prefixes:
            if name.startswith(p): return name.replace(p, '').strip()
        return name.strip()

    def find_header_row(self, df):
        # Scan first 15 rows for header keywords
        keywords = ['group', 'teacher', 'subject', 'รหัส', 'ที่', 'ชื่อ', 'id', 'วิชา', 'start', 'time']
        for i in range(min(15, len(df))):
            row_str = df.iloc[i].astype(str).str.lower().tolist()
            matches = sum(1 for val in row_str for kw in keywords if kw in val)
            if matches >= 2: return i
        return 0

    def deduplicate_columns(self, cols):
        """เติมเลขต่อท้ายคอลัมน์ที่ชื่อซ้ำกัน"""
        counts = {}
        new_cols = []
        for col in cols:
            col_str = str(col).strip()
            if col_str in counts:
                counts[col_str] += 1
                new_cols.append(f"{col_str}_{counts[col_str]}")
            else:
                counts[col_str] = 0
                new_cols.append(col_str)
        return new_cols

    def normalize_df(self, df):
        # 1. Header Detection
        idx = self.find_header_row(df)
        if idx > 0:
            raw_header = df.iloc[idx].tolist()
            df.columns = self.deduplicate_columns(raw_header)
            df = df.iloc[idx+1:].reset_index(drop=True)
        else:
            df.columns = self.deduplicate_columns(df.columns)
            
        # 2. Rename Columns (Priority Match)
        current_cols = [str(c).strip().lower() for c in df.columns]
        new_cols = []
        
        # ใช้ set เพื่อกันการ map ซ้ำซ้อนใน 1 ไฟล์
        mapped_indices = set()
        
        # สร้าง list เปล่าเท่าจำนวนคอลัมน์
        final_col_names = list(current_cols) 

        # วนลูปตามกฎ (Rules) ที่เรียงลำดับความสำคัญไว้แล้ว
        for std_name, variants in self.col_mapping_rules:
            for i, col in enumerate(current_cols):
                if i in mapped_indices: continue # คอลัมน์นี้ถูกเปลี่ยนชื่อไปแล้ว ข้ามเลย
                
                # เช็คว่าชื่อคอลัมน์มีคำใน variants หรือไม่
                if any(v in col for v in variants):
                    final_col_names[i] = std_name
                    mapped_indices.add(i)

        df.columns = self.deduplicate_columns(final_col_names)
        
        # 3. Clean Content
        df = df.map(self.clean_text)
        return df

    def process_upload(self, files):
        data_store = {}
        for file in files:
            try:
                fname = file.name.lower()
                dfs = {}
                if fname.endswith(('.xlsx', '.xls')):
                    dfs = pd.read_excel(file, sheet_name=None)
                elif fname.endswith('.csv'):
                    try: dfs = {file.name: pd.read_csv(file, encoding='utf-8-sig')}
                    except: 
                        file.seek(0)
                        dfs = {file.name: pd.read_csv(file, encoding='cp874')}

                for sheet, df in dfs.items():
                    if df.empty: continue
                    clean_df = self.normalize_df(df)
                    cols = clean_df.columns.tolist()
                    
                    # --- Identification Logic ---
                    dtype = None
                    
                    # Timeslot Check (New)
                    if 'start_time' in cols: dtype = 'timeslot'
                    # Standard Checks
                    elif 'group_id' in cols and 'teacher_id' in cols: dtype = 'teach'
                    elif 'group_id' in cols and 'subject_id' in cols: dtype = 'register'
                    elif 'subject_id' in cols and 'subject_name' in cols: dtype = 'subject'
                    elif 'room_id' in cols: dtype = 'room'
                    # Relaxed Teacher Check
                    elif 'teacher_id' in cols: dtype = 'teacher' 
                    # Fallback checks
                    elif 'subject_id' in cols: dtype = 'subject'
                    elif 'group_id' in cols: dtype = 'teach'
                    
                    if dtype:
                        # Teacher Name Cleaning
                        if dtype == 'teacher' and 'teacher_name' in clean_df.columns:
                            clean_df['teacher_name'] = clean_df['teacher_name'].apply(self.remove_prefixes)
                        
                        # Handle Timeslot Configuration immediately
                        if dtype == 'timeslot':
                            if 'start_time' in clean_df.columns and 'end_time' in clean_df.columns:
                                times = clean_df['start_time'].astype(str) + '-' + clean_df['end_time'].astype(str)
                                self.timeslot_config = {
                                    'labels': times.tolist(),
                                    'count': len(times)
                                }
                                self.log(f"🕒 Configured {len(times)} timeslots from file", "success")

                        if dtype in data_store and dtype != 'timeslot':
                            data_store[dtype] = pd.concat([data_store[dtype], clean_df], ignore_index=True)
                        else:
                            data_store[dtype] = clean_df
                        
                        self.log(f"✅ Loaded '{dtype.upper()}' from {sheet}", "success")
                        self.raw_preview[f"{dtype.upper()}"] = clean_df.head(3)
                    else:
                        self.log(f"⚠️ Unrecognized structure in {sheet}", "warning")
                        self.raw_preview[f"UNKNOWN ({sheet})"] = clean_df.head(3)

            except Exception as e:
                self.log(f"❌ Error reading {file.name}: {e}", "error")
        return data_store

# ==========================================
# 3. ADVANCED CSP ENGINE (Using Configured Timeslots)
# ==========================================
class CSPScheduler:
    def __init__(self, data, timeslot_cfg):
        self.data = data
        self.timeslot_labels = timeslot_cfg['labels']
        self.n_periods = timeslot_cfg['count']
        self.failed_tasks = []
        
        if 'room' in data:
            self.rooms = data['room']['room_id'].dropna().astype(str).unique().tolist()
        else:
            self.rooms = DEFAULT_ROOMS

    def solve(self):
        tasks = []
        
        # --- PHASE 1: Data Prep ---
        if 'register' in self.data:
            df = self.data['register'].copy()
            if 'subject' in self.data: df = df.merge(self.data['subject'], on='subject_id', how='left')
            else: df['theory'] = 2; df['practice'] = 0; df['subject_name'] = df['subject_id']
            
            if 'teach' in self.data: df = df.merge(self.data['teach'], on='group_id', how='left')
            else: df['teacher_id'] = 'T_Auto'
        elif 'teach' in self.data:
            df = self.data['teach'].copy()
            df['subject_id'] = 'ACTIVITY'; df['subject_name'] = 'กิจกรรม'; df['theory'] = 2; df['practice'] = 0
        else:
            return pd.DataFrame()

        if 'teacher_id' not in df.columns: df['teacher_id'] = 'T_Unknown'
        df['teacher_id'] = df['teacher_id'].fillna('T_Unknown').astype(str)
        df['group_id'] = df['group_id'].astype(str).replace('nan', 'Unknown')
        
        for _, row in df.iterrows():
            try:
                th = float(row.get('theory', 2))
                pr = float(row.get('practice', 0))
                hours = int(th + pr)
                if hours <= 0: hours = 2
            except: hours = 2
            
            tasks.append({
                'id': f"{row['group_id']}_{row.get('subject_id')}",
                'group': str(row['group_id']),
                'teacher': str(row['teacher_id']),
                'subject': str(row.get('subject_id', 'N/A')),
                'name': str(row.get('subject_name', 'N/A')),
                'hours': hours
            })

        # --- PHASE 2: Solve ---
        tasks.sort(key=lambda x: x['hours'], reverse=True)

        # Dynamic Grid Size based on Timeslot File
        t_sched = {} 
        g_sched = {}
        r_sched = {r: np.zeros((5, self.n_periods)) for r in self.rooms}
        
        assignments = []
        start_time = time.time()
        
        for task in tasks:
            if task['teacher'] not in t_sched: t_sched[task['teacher']] = np.zeros((5, self.n_periods))
            if task['group'] not in g_sched: g_sched[task['group']] = np.zeros((5, self.n_periods))
            
            assigned = False
            strategies = [[task['hours']]]
            if task['hours'] >= 4: strategies = [[4], [2,2], [1,1,1,1]]
            elif task['hours'] == 3: strategies = [[3], [2,1], [1,1,1]]
            elif task['hours'] == 2: strategies = [[2], [1,1]]
            if time.time() - start_time > 5: strategies.append([1]*task['hours'])

            for strat in strategies:
                temp_asns = []
                possible = True
                
                for duration in strat:
                    slot_found = False
                    for d in range(5):
                        if slot_found: break
                        # Limit period loop based on loaded timeslots
                        for p in range(self.n_periods - duration + 1):
                            if np.sum(t_sched[task['teacher']][d, p:p+duration]) > 0: continue
                            if np.sum(g_sched[task['group']][d, p:p+duration]) > 0: continue
                            
                            sel_room = None
                            for room in self.rooms:
                                if np.sum(r_sched[room][d, p:p+duration]) == 0:
                                    sel_room = room
                                    break
                            
                            if sel_room:
                                temp_asns.append({
                                    'group_id': task['group'],
                                    'subject_id': task['subject'],
                                    'subject_name': task['name'],
                                    'teacher_id': task['teacher'],
                                    'room_id': sel_room,
                                    'day': d,
                                    'start_period': p,
                                    'duration': duration
                                })
                                t_sched[task['teacher']][d, p:p+duration] = 1
                                g_sched[task['group']][d, p:p+duration] = 1
                                r_sched[sel_room][d, p:p+duration] = 1
                                slot_found = True
                                break
                    if not slot_found:
                        possible = False
                        # Rollback
                        for a in temp_asns:
                            d, p, dur = a['day'], a['start_period'], a['duration']
                            t_sched[task['teacher']][d, p:p+dur] = 0
                            g_sched[task['group']][d, p:p+dur] = 0
                            r_sched[a['room_id']][d, p:p+dur] = 0
                        break
                
                if possible:
                    assignments.extend(temp_asns)
                    assigned = True
                    break
            
            if not assigned: self.failed_tasks.append(task)
                
        return pd.DataFrame(assignments)

# ==========================================
# 4. EXPORT ENGINE
# ==========================================
class ReportGenerator:
    def __init__(self, time_labels):
        self.time_labels = time_labels

    def export_excel(self, df):
        out = io.BytesIO()
        writer = pd.ExcelWriter(out, engine='xlsxwriter')
        wb = writer.book
        fmt_head = wb.add_format({'bold':True, 'bg_color':'#DDEBF7', 'border':1, 'align':'center'})
        fmt_cell = wb.add_format({'border':1, 'align':'center', 'valign':'vcenter', 'text_wrap':True})
        
        for grp in sorted(df['group_id'].unique().astype(str)):
            ws = wb.add_worksheet(str(grp)[:30])
            ws.write_row(0, 0, ["Day"] + self.time_labels, fmt_head)
            sub = df[df['group_id'] == grp]
            for d, day in enumerate(DEFAULT_DAYS):
                ws.write(d+1, 0, day, fmt_head)
                for _, r in sub[sub['day'] == d].iterrows():
                    txt = f"{r['subject_id']}\n{r['teacher_id']}\n{r['room_id']}"
                    if r['duration'] > 1:
                        ws.merge_range(d+1, r['start_period']+1, d+1, r['start_period']+r['duration'], txt, fmt_cell)
                    else:
                        ws.write(d+1, r['start_period']+1, txt, fmt_cell)
        writer.close()
        return out.getvalue()

    def export_pdf(self, df, col, val):
        pdf = FPDF('L', 'mm', 'A4')
        pdf.add_page()
        try:
            pdf.add_font('THSarabunNew', '', 'THSarabunNew.ttf', uni=True)
            pdf.set_font('THSarabunNew', '', 14)
            th = True
        except:
            pdf.set_font('Arial', '', 10)
            th = False
            
        pdf.cell(0, 10, f"Class Schedule: {val}", 0, 1, 'C')
        x, y, w, h = 10, 30, 30, 20
        
        pdf.set_xy(x, y); pdf.cell(w, 10, "Day", 1, 0, 'C')
        for t in self.time_labels: 
            label = t.split('-')[0] if '-' in t else t
            pdf.cell(w, 10, label, 1, 0, 'C')
        
        data = df[df[col] == val]
        for d, day in enumerate(DEFAULT_DAYS):
            cy = y + 10 + (d*h)
            pdf.set_xy(x, cy); pdf.cell(w, h, day if th else f"D{d+1}", 1, 0, 'C')
            for p in range(len(self.time_labels)):
                pdf.set_xy(x+w+(p*w), cy); pdf.cell(w, h, "", 1)
            
            for _, r in data[data['day'] == d].iterrows():
                bx = x+w+(r['start_period']*w)
                bw = r['duration']*w
                pdf.set_xy(bx, cy)
                pdf.set_fill_color(240, 248, 255)
                pdf.cell(bw, h, "", 1, 0, fill=True)
                pdf.set_xy(bx, cy+5)
                pdf.multi_cell(bw, 5, f"{r['subject_id']}\n{r['room_id']}", 0, 'C')
        return pdf.output(dest='S').encode('latin-1')

# ==========================================
# 5. MAIN UI
# ==========================================
def main():
    st.title("🤖 Pro AI Scheduler: Final Fix")
    st.markdown("---")
    
    with st.sidebar:
        st.header("📂 Data Input")
        files = st.file_uploader("Upload Excel/CSV", accept_multiple_files=True)
        dm = DataManager()
        data = {}
        if files:
            data = dm.process_upload(files)
            st.success(f"Loaded {len(data)} datasets")
            
        st.divider()
        st.info("Supported: Teach, Register, Subject, Room, Teacher, Timeslot")

    tab1, tab2, tab3 = st.tabs(["🚀 Dashboard & Run", "📅 Interactive Schedule", "🔍 Data Inspector"])
    
    with tab1:
        if not data:
            st.warning("Please upload data files in the sidebar.")
        else:
            c1, c2 = st.columns([2,1])
            with c1:
                st.subheader("Control Panel")
                st.write(f"**Detected Timeslots:** {dm.timeslot_config['count']} periods")
                if st.button("Start AI Scheduling", type="primary", use_container_width=True):
                    with st.spinner("AI Computing..."):
                        solver = CSPScheduler(data, dm.timeslot_config)
                        res = solver.solve()
                        if not res.empty:
                            st.session_state['result'] = res
                            st.session_state['failed'] = solver.failed_tasks
                            st.session_state['time_labels'] = dm.timeslot_config['labels']
                            st.success("Scheduling Completed!")
                        else:
                            st.error("No schedule generated.")
            with c2:
                st.subheader("Logs")
                with st.container(height=200):
                    for t, ty, msg in dm.logs:
                        c = "red" if ty=="error" else "orange" if ty=="warning" else "green"
                        st.markdown(f":{c}[{msg}]")
            
            if 'result' in st.session_state:
                st.divider()
                m1, m2, m3 = st.columns(3)
                m1.metric("Scheduled", len(st.session_state['result']))
                m2.metric("Failed", len(st.session_state['failed']))
                m3.metric("Rooms", st.session_state['result']['room_id'].nunique())

    with tab2:
        if 'result' in st.session_state:
            df = st.session_state['result']
            labels = st.session_state['time_labels']
            
            c1, c2 = st.columns([1, 3])
            with c1:
                view = st.radio("View:", ["Group", "Teacher", "Room"])
                key = 'group_id' if view == "Group" else 'teacher_id' if view == "Teacher" else 'room_id'
                vals = sorted(df[key].astype(str).unique())
                val = st.selectbox(f"Select {view}", vals)
            
            with c2:
                sub = df[df[key] == val]
                html = "<div style='overflow-x:auto;'><table>"
                html += f"<tr><th>Day</th>{''.join([f'<th>{t}</th>' for t in labels])}</tr>"
                for d, day in enumerate(DEFAULT_DAYS):
                    html += f"<tr><td style='font-weight:bold;'>{day}</td>"
                    p = 0
                    while p < len(labels):
                        match = sub[(sub['day']==d) & (sub['start_period']==p)]
                        if not match.empty:
                            r = match.iloc[0]
                            info = f"<b>{r['subject_id']}</b>"
                            if view != "Room": info += f"<br>{r['room_id']}"
                            if view != "Group": info += f"<br>G:{r['group_id']}"
                            html += f"<td colspan='{r['duration']}' style='background:#E3F2FD;'>{info}</td>"
                            p += r['duration']
                        else:
                            html += "<td>-</td>"
                            p += 1
                    html += "</tr>"
                html += "</table></div>"
                st.markdown(html, unsafe_allow_html=True)
            
            st.divider()
            rg = ReportGenerator(labels)
            b1, b2 = st.columns(2)
            b1.download_button("Download PDF", rg.export_pdf(df, key, val), f"{val}.pdf", "application/pdf")
            b2.download_button("Download Excel", rg.export_excel(df), "Schedule.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab3:
        if dm.raw_preview:
            for k, v in dm.raw_preview.items():
                with st.expander(k, expanded=False): st.dataframe(v)
        else: st.info("No data.")

if __name__ == "__main__":
    main()
