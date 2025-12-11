import streamlit as st, pandas as pd, re, time
from scheduler_logic import SchedulerCSP
from io import BytesIO
from fpdf import FPDF
from openpyxl.styles import Alignment, Font, Border, Side, PatternFill

st.set_page_config(page_title="ระบบจัดตารางสอน (Time Added)", layout="wide")
st.markdown("<style>thead tr th:first-child {display:none} tbody th {display:none} table {text-align:center !important}</style>", unsafe_allow_html=True)

# --- Config & Time Slots ---
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
PERIODS = [1, 2, 3, 4, 'Lunch', 5, 6, 7, 8]

# กำหนดช่วงเวลา (แก้ไขเวลาตรงนี้ได้)
TIME_MAP = {
    1: "08:30-09:30",
    2: "09:30-10:30",
    3: "10:30-11:30",
    4: "11:30-12:30",
    'Lunch': "12:30-13:30",
    5: "13:30-14:30",
    6: "14:30-15:30",
    7: "15:30-16:30",
    8: "16:30-17:30"
}

VIEWS = {
    'Student': {'lbl': 'นักเรียน (Student)', 'id': 'Group_ID', 'cols': ['Room_ID', 'Subject_ID', 'Teacher_Name'], 'leg': ['รหัส', 'ชื่อ', 'ห้อง', 'ครู'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Room_ID', 'Teacher_Name'], 'pfx': 'G-'},
    'Teacher': {'lbl': 'ครูผู้สอน (Teacher)', 'id': 'Teacher_ID', 'cols': ['Room_ID', 'Subject_ID', 'Group_ID'], 'leg': ['รหัส', 'ชื่อ', 'ห้อง', 'นร.'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Room_ID', 'Group_ID'], 'pfx': 'T-'},
    'Room':    {'lbl': 'ห้องเรียน (Room)', 'id': 'Room_ID', 'cols': ['Teacher_Name', 'Subject_ID', 'Group_ID'], 'leg': ['รหัส', 'ชื่อ', 'ครู', 'นร.'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Teacher_Name', 'Group_ID'], 'pfx': 'R-'}
}

# --- Validator Core ---
def clean(n): return re.sub(r'^(ว่าที่\s?ร\.?ต\.?|ดร\.|ผศ\.|นางสาว|นาย|นาง|Mr\.|Ms\.)\s*', '', str(n).strip()) if pd.notna(n) else ""

def validate(df, key, name):
    logs = []
    df = df.apply(lambda x: x.str.strip() if x.dtype=='object' else x).drop_duplicates()
    if key and key in df:
        dups = df[df.duplicated(subset=key)]
        if not dups.empty:
            df = df.drop_duplicates(subset=key)
            logs.append(f"🔧 {name}: ลบรหัสซ้ำ {len(dups)} รายการ")
    return df, logs

def load_data(files):
    d, logs = {}, []
    for f in files:
        try:
            df = pd.read_csv(f, dtype=str) if f.name.endswith('.csv') else pd.read_excel(f, dtype=str)
            df.columns = [c.strip() for c in df.columns]
            
            if 'GroupID' in df: d['Groups'], l = validate(df, 'GroupID', 'Groups')
            elif 'RoomID' in df: d['Rooms'], l = validate(df, 'RoomID', 'Rooms')
            elif 'TeacherID' in df:
                df, l = validate(df, 'TeacherID', 'Teachers')
                nm = next((c for c in ['Name','Teacher_Name','ชื่อ','ชื่อ-สกุล'] if c in df.columns), None)
                df['CleanName'] = df[nm].apply(clean) if nm else df['TeacherID']
                d['Teachers'] = df
            elif 'Subject_ID' in df: d['Subjects'], l = validate(df, None, 'Subjects')
            else: l = [f"⚠️ ไม่รู้จักไฟล์: {f.name}"]
            logs.extend(l)
        except Exception as e: logs.append(f"🔥 Error {f.name}: {e}")

    if len(d) == 4:
        sub = d['Subjects']
        vt, vg = set(d['Teachers']['TeacherID']), set(d['Groups']['GroupID'])
        bad_t = sub[~sub['Teacher_ID'].isin(vt)]
        if not bad_t.empty:
            d['Subjects'] = sub[sub['Teacher_ID'].isin(vt)]
            logs.append(f"❌ ตัดวิชาทิ้ง {len(bad_t)} รายการ (รหัสครูผิด)")
        bad_g = sub[~sub['Group_ID'].isin(vg)]
        if not bad_g.empty:
            d['Subjects'] = d['Subjects'][d['Subjects']['Group_ID'].isin(vg)]
            logs.append(f"❌ ตัดวิชาทิ้ง {len(bad_g)} รายการ (รหัสกลุ่มผิด)")
            
    return d, logs

# --- Engines ---
class PDF(FPDF):
    def footer(self): self.set_y(-15); self.set_font('THSarabunNew','',10); self.cell(0,10,f'Page {self.page_no()}',0,0,'R')

def gen_pdf(df, entities, vkey, t_map):
    pdf = PDF('L', 'mm', 'A4'); pdf.set_auto_page_break(True, 15)
    try: pdf.add_font('THSarabunNew','','THSarabunNew.ttf',uni=True)
    except: pdf.add_font('Arial','',10)
    pdf.set_font('THSarabunNew','',12); cfg = VIEWS[vkey]
    
    for ent in ([entities] if isinstance(entities, str) else entities):
        sub = df[df[cfg['id']] == ent]
        if sub.empty: continue
        pdf.add_page(); pdf.set_font_size(20)
        title = t_map.get(ent, ent) if vkey=='Teacher' else ent
        pdf.cell(0, 10, f"ตารางสอน: {title}", 0, 1, 'C')
        
        # Table Header (ใส่เวลา)
        pdf.set_font_size(12); pdf.set_fill_color(240); pdf.cell(20, 8, "Day/Time", 1, 0, 'C', 1)
        for p in PERIODS: 
            w = 15 if p=='Lunch' else 27
            txt = TIME_MAP.get(p, str(p)) # ดึงเวลาจาก TIME_MAP
            pdf.cell(w, 8, txt, 1, 0, 'C', 1)
        pdf.ln()
        
        # Grid
        for d in DAYS:
            pdf.set_font_size(14)
            pdf.cell(20, 22, d, 1, 0, 'C', 1)
            for p in PERIODS:
                w = 15 if p=='Lunch' else 27
                if p=='Lunch': pdf.set_fill_color(220); pdf.cell(w, 22, "พัก", 1, 0, 'C', 1)
                else:
                    r = sub[(sub['Day']==d) & (sub['Period']==p)]
                    if not r.empty:
                        info = "\n".join([str(r.iloc[0][c])[:15] for c in cfg['cols']])
                        x,y = pdf.get_x(), pdf.get_y(); pdf.rect(x,y,w,22); pdf.set_font_size(11); pdf.set_xy(x,y+2); pdf.multi_cell(w,5,info,0,'C'); pdf.set_xy(x+w,y)
                    else: pdf.cell(w, 22, "", 1, 0)
            pdf.ln()
        
        pdf.ln(5); pdf.set_font_size(12); pdf.cell(0, 8, "รายละเอียดรายวิชา:", 0, 1, 'L'); pdf.set_fill_color(230)
        wds = [25, 80, 40, 45]; [pdf.cell(wds[i], 7, h, 1, 0, 'C', 1) for i,h in enumerate(cfg['leg'])]; pdf.ln()
        for _,r in sub[cfg['leg_c']].drop_duplicates().iterrows():
            for i,txt in enumerate(r): pdf.cell(wds[i], 7, str(txt)[:45], 1, 0, 'L' if i==1 else 'C')
            pdf.ln()
    return pdf.output(dest='S').encode('latin-1')

def gen_excel(df, t_map):
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Raw')
        
        # Styles
        center_style = Alignment(horizontal='center', vertical='center', wrap_text=True)
        header_font = Font(bold=True)
        thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

        for k, cfg in VIEWS.items():
            col = f'Disp_{k}'; df[col] = df[cfg['cols'][0]] + "\n" + df[cfg['cols'][1]] + "\n" + df[cfg['cols'][2]]
            for ent in sorted(df[cfg['id']].unique()):
                sub = df[df[cfg['id']] == ent]
                if sub.empty: continue
                
                piv = sub.pivot_table(index='Day', columns='Period', values=col, aggfunc='first').reindex(DAYS).reindex(columns=[1,2,3,4,5,6,7,8])
                try: piv.insert(4, 'Lunch', 'พักกลางวัน') 
                except: pass
                
                # เปลี่ยนชื่อ Column ใน Excel เป็นเวลา
                piv = piv.rename(columns=TIME_MAP)
                
                sh_name = f"{cfg['pfx']}{str(ent)[:20]}".replace(":","").replace("/","-")
                piv.fillna('').to_excel(writer, sheet_name=sh_name)
                
                # Apply Styles
                ws = writer.sheets[sh_name]
                ws.column_dimensions['A'].width = 15
                for c in range(2, 12): # 10 columns (time slots)
                    ws.column_dimensions[chr(64+c)].width = 22
                
                for row in ws.iter_rows():
                    for cell in row:
                        cell.alignment = center_style
                        cell.border = thin_border
                        if cell.row == 1: 
                            cell.font = header_font
                            cell.fill = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")

    return out.getvalue()

# ================= MAIN UI =================
st.sidebar.header("1. นำเข้าข้อมูล")
up = st.sidebar.file_uploader("Upload CSV/Excel", accept_multiple_files=True)

if up:
    data, logs = load_data(up)
    if logs:
        with st.sidebar.expander("📝 บันทึกการตรวจสอบ (Validation Logs)", expanded=True):
            for l in logs:
                if "ลบ" in l or "ตัด" in l: st.warning(l)
                elif "Error" in l: st.error(l)
                else: st.info(l)
            
    if len(data) == 4:
        st.sidebar.success("✅ ข้อมูลพร้อมประมวลผล")
        t_map = dict(zip(data['Teachers']['TeacherID'], data['Teachers']['CleanName']))
        
        if st.sidebar.button("🚀 สร้างตาราง"):
            with st.spinner("กำลังจัดตารางสอน (AI Scheduling)..."):
                res, una = SchedulerCSP(data['Teachers'], data['Subjects'], data['Rooms'], data['Groups']).generate_schedule(45)
                if [i for l in res.values() for i in l]:
                    df = pd.DataFrame([i for l in res.values() for i in l])
                    df['Teacher_Name'] = df['Teacher_ID'].map(t_map).fillna(df['Teacher_ID'])
                    st.session_state.update(res=df, una=una, t_map=t_map)
                    if not una: st.success("🎉 จัดตารางเสร็จสมบูรณ์ 100%")
                    else: st.warning(f"⚠️ จัดไม่ได้ {len(una)} รายการ")
                else: st.error("❌ ไม่สามารถจัดตารางได้")
    else: st.sidebar.warning(f"ไฟล์ไม่ครบ: {set(['Groups','Rooms','Teachers','Subjects']) - data.keys()}")

if 'res' in st.session_state:
    df, t_map = st.session_state.res, st.session_state.t_map
    if st.session_state.una: 
        with st.expander("รายละเอียดรายวิชาที่จัดไม่ได้"): st.write(st.session_state.una)
    st.divider()
    
    # Preview
    c1, c2 = st.columns([1, 4])
    vkey = c1.radio("มุมมอง:", list(VIEWS.keys()), format_func=lambda x: VIEWS[x]['lbl'])
    cfg = VIEWS[vkey]
    ents = sorted(df[cfg['id']].unique())
    sel = c1.selectbox("เลือก:", ents, format_func=(lambda x: t_map.get(x,x)) if vkey=='Teacher' else (lambda x: x))
    
    if sel:
        sub = df[df[cfg['id']] == sel].copy()
        sub['Disp'] = sub[cfg['cols'][0]] + "<br>" + sub[cfg['cols'][1]] + "<br>" + sub[cfg['cols'][2]]
        piv = sub.pivot_table(index='Day', columns='Period', values='Disp', aggfunc='first').reindex(DAYS).fillna("-")
        
        # HTML Table Construction (ใส่เวลาใน Header)
        h = "<table style='width:100%; text-align:center; border-collapse:collapse;'><tr style='background:#f0f2f6'><th>Day/Time</th>"
        for p in PERIODS:
            txt = TIME_MAP.get(p, str(p)) # ใช้เวลาจริง
            h += f"<th>{txt}</th>"
        h += "</tr>"
        
        for d in DAYS:
            h += f"<tr><td style='font-weight:bold'>{d}</td>"
            for p in PERIODS:
                v = "พัก" if p=='Lunch' else (piv.at[d,p] if p in piv.columns and pd.notna(piv.at[d,p]) else "-")
                h += f"<td style='border:1px solid #ddd; padding:5px; background:{'#eee' if p=='Lunch' else ''}'>{v}</td>"
            h += "</tr>"
        c2.markdown(f"### {t_map.get(sel,sel) if vkey=='Teacher' else sel}"); c2.markdown(h+"</table>", unsafe_allow_html=True)
        c2.table(sub[cfg['leg_c']].drop_duplicates().set_axis(cfg['leg'], axis=1))
        c2.download_button("📄 PDF หน้านี้", gen_pdf(df, sel, vkey, t_map), f"{sel}.pdf", "application/pdf")

    st.divider(); st.subheader("💾 ดาวน์โหลดทั้งหมด")
    cols = st.columns(4)
    cols[0].download_button("📥 Excel รวมเล่ม", gen_excel(df, t_map), "Master.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    for i, (k, v) in enumerate(VIEWS.items()):
        if cols[i+1].button(f"📄 PDF {v['lbl'].split('(')[0]}"):
            st.session_state[f'p_{k}'] = gen_pdf(df, sorted(df[v['id']].unique()), k, t_map)
        if f'p_{k}' in st.session_state: cols[i+1].download_button("⬇️ โหลด", st.session_state[f'p_{k}'], f"{k}s_Book.pdf")
