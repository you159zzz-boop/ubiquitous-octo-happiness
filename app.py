import streamlit as st
import pandas as pd
import re
import time
from scheduler_logic import SchedulerCSP
from io import BytesIO
from fpdf import FPDF
from openpyxl.styles import Alignment, Font, Border, Side, PatternFill

st.set_page_config(page_title="ระบบจัดตารางสอน (Complete)", layout="wide")

# --- 1. CSS Styling (หัวตารางมีเวลาชัดเจน) ---
st.markdown("""
<style>
    /* ซ่อนตารางเดิมของ Streamlit */
    .stTable {display: none;} 
    
    /* สไตล์ตารางใหม่ */
    .custom-table {
        width: 100%;
        border-collapse: collapse;
        text-align: center;
        font-family: 'Sarabun', sans-serif;
        margin-bottom: 20px;
    }
    .custom-table th {
        background-color: #2E7D32; /* สีเขียวหัวเป็ด */
        color: white;
        padding: 8px;
        border: 1px solid #ddd;
        vertical-align: middle;
        min-width: 80px;
    }
    .custom-table td {
        padding: 8px;
        border: 1px solid #ddd;
        vertical-align: middle;
        font-size: 14px;
    }
    /* จัดรูปแบบตัวอักษรในหัวตาราง */
    .time-txt { font-size: 14px; font-weight: bold; display: block; margin-bottom: 4px; }
    .period-txt { font-size: 12px; font-weight: normal; opacity: 0.9; }
</style>
""", unsafe_allow_html=True)

# --- 2. Configuration ---
DAYS_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
DAYS_TH = ['วันจันทร์', 'วันอังคาร', 'วันพุธ', 'วันพฤหัสบดี', 'วันศุกร์']
DAY_MAP = dict(zip(DAYS_EN, DAYS_TH))

PERIODS = [1, 2, 3, 4, 'Lunch', 5, 6, 7, 8]

TIME_MAP = {
    1: "08:30-09:30", 2: "09:30-10:30", 3: "10:30-11:30", 4: "11:30-12:30",
    'Lunch': "12:30-13:30",
    5: "13:30-14:30", 6: "14:30-15:30", 7: "15:30-16:30", 8: "16:30-17:30"
}

VIEWS = {
    'Student': {'lbl': 'นักเรียน (Student)', 'id': 'Group_ID', 'cols': ['Room_ID', 'Subject_ID', 'Teacher_Name'], 'leg': ['รหัส', 'ชื่อ', 'ห้อง', 'ครู'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Room_ID', 'Teacher_Name'], 'pfx': 'G-'},
    'Teacher': {'lbl': 'ครูผู้สอน (Teacher)', 'id': 'Teacher_ID', 'cols': ['Room_ID', 'Subject_ID', 'Group_ID'], 'leg': ['รหัส', 'ชื่อ', 'ห้อง', 'นร.'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Room_ID', 'Group_ID'], 'pfx': 'T-'},
    'Room':    {'lbl': 'ห้องเรียน (Room)', 'id': 'Room_ID', 'cols': ['Teacher_Name', 'Subject_ID', 'Group_ID'], 'leg': ['รหัส', 'ชื่อ', 'ครู', 'นร.'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Teacher_Name', 'Group_ID'], 'pfx': 'R-'}
}

# --- 3. Data Validation & Cleaning (ระบบตรวจสอบกลับมาแล้ว!) ---
def clean_str(n): 
    # ตัดคำนำหน้าชื่อ
    s = str(n).strip()
    for p in ['ว่าที่ร้อยตรี', 'ว่าที่ ร.ต.', 'ดร.', 'ผศ.', 'นางสาว', 'นาย', 'นาง', 'Mr.', 'Ms.']:
        s = s.replace(p, '')
    return s.strip()

def load_and_validate_data(files):
    d = {}
    logs = []
    
    # Step A: Load & Basic Clean
    for f in files:
        try:
            # อ่านเป็น String เพื่อกัน ID เพี้ยน
            df = pd.read_csv(f, dtype=str) if f.name.endswith('.csv') else pd.read_excel(f, dtype=str)
            # Trim whitespace หัวตารางและข้อมูล
            df.columns = [c.strip() for c in df.columns]
            df = df.apply(lambda x: x.str.strip() if x.dtype=='object' else x)
            
            # ลบแถวซ้ำ
            if df.duplicated().sum() > 0:
                df = df.drop_duplicates()
                logs.append(f"🧹 {f.name}: ลบข้อมูลซ้ำซ้อนออก")

            if 'GroupID' in df: d['Groups'] = df
            elif 'RoomID' in df: d['Rooms'] = df
            elif 'TeacherID' in df:
                # หาคอลัมน์ชื่อครูอัตโนมัติ
                nm = next((c for c in ['Name','Teacher_Name','ชื่อ','ชื่อ-สกุล'] if c in df.columns), None)
                df['CleanName'] = df[nm].apply(clean_str) if nm else df['TeacherID']
                d['Teachers'] = df
            elif 'Subject_ID' in df: d['Subjects'] = df
            else: logs.append(f"⚠️ ไม่รู้จักโครงสร้างไฟล์: {f.name}")
            
        except Exception as e: logs.append(f"🔥 Error reading {f.name}: {e}")

    # Step B: Cross-Validation (ตรวจสอบความเชื่อมโยง)
    if len(d) == 4:
        sub = d['Subjects']
        valid_t = set(d['Teachers']['TeacherID'])
        valid_g = set(d['Groups']['GroupID'])
        valid_r = set(d['Rooms']['Type']) # เช็คประเภทห้อง
        
        # 1. เช็คครู
        bad_t = sub[~sub['Teacher_ID'].isin(valid_t)]
        if not bad_t.empty:
            d['Subjects'] = sub[sub['Teacher_ID'].isin(valid_t)]
            logs.append(f"❌ ลบวิชาทิ้ง {len(bad_t)} รายการ: เนื่องจากรหัสครูไม่มีในทะเบียน")
            
        # 2. เช็คกลุ่มเรียน
        sub = d['Subjects'] # อัปเดตค่าใหม่
        bad_g = sub[~sub['Group_ID'].isin(valid_g)]
        if not bad_g.empty:
            d['Subjects'] = sub[sub['Group_ID'].isin(valid_g)]
            logs.append(f"❌ ลบวิชาทิ้ง {len(bad_g)} รายการ: เนื่องจากรหัสกลุ่มเรียนผิด")
            
        # 3. เช็คห้อง (แจ้งเตือนเฉยๆ หรือลบก็ได้)
        sub = d['Subjects']
        if 'Room_Type' in sub.columns:
            bad_r = sub[~sub['Room_Type'].isin(valid_r)]
            if not bad_r.empty:
                d['Subjects'] = sub[sub['Room_Type'].isin(valid_r)]
                logs.append(f"❌ ลบวิชาทิ้ง {len(bad_r)} รายการ: ประเภทห้องไม่ตรงกับฐานข้อมูล")

    return d, logs

# --- 4. Export Engines ---
class PDF(FPDF):
    def footer(self): self.set_y(-15); self.set_font('THSarabunNew','',10); self.cell(0,10,f'หน้า {self.page_no()}',0,0,'R')

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
        
        # Header (มีเวลา)
        pdf.set_font_size(12); pdf.set_fill_color(240); pdf.cell(20, 12, "วัน / เวลา", 1, 0, 'C', 1)
        for p in PERIODS:
            txt = "พักกลางวัน" if p=='Lunch' else f"{TIME_MAP[p]}\n(คาบ {p})"
            w = 15 if p=='Lunch' else 27
            x,y = pdf.get_x(), pdf.get_y()
            pdf.multi_cell(w, 6, txt, 1, 'C', 1)
            pdf.set_xy(x+w, y)
        pdf.ln(12)
        
        # Grid
        for d in DAYS_EN:
            pdf.set_font_size(14)
            pdf.cell(20, 22, DAY_MAP[d], 1, 0, 'C', 1)
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
    return pdf.output(dest='S').encode('latin-1')

def gen_excel(df, t_map):
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Raw')
        align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        thin = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        
        for k, cfg in VIEWS.items():
            col = f'Disp_{k}'; df[col] = df[cfg['cols'][0]] + "\n" + df[cfg['cols'][1]] + "\n" + df[cfg['cols'][2]]
            for ent in sorted(df[cfg['id']].unique()):
                sub = df[df[cfg['id']] == ent]
                if sub.empty: continue
                piv = sub.pivot_table(index='Day', columns='Period', values=col, aggfunc='first').reindex(DAYS_EN).reindex(columns=[1,2,3,4,5,6,7,8])
                try: piv.insert(4, 'Lunch', 'พักกลางวัน') 
                except: pass
                piv.index = piv.index.map(DAY_MAP) # วันไทย
                piv.columns = [TIME_MAP.get(c, str(c)) if c!='Lunch' else "12:30-13:30" for c in piv.columns] # เวลา
                
                sh_name = f"{cfg['pfx']}{str(ent)[:20]}".replace(":","").replace("/","-")
                piv.fillna('').to_excel(writer, sheet_name=sh_name)
                
                ws = writer.sheets[sh_name]
                ws.column_dimensions['A'].width = 15
                for c in range(2, 12): ws.column_dimensions[chr(64+c)].width = 25; ws.cell(row=1, column=c).alignment = align
                for row in ws.iter_rows():
                    for cell in row: cell.alignment = align; cell.border = thin
    return out.getvalue()

# ================= 5. MAIN UI =================
st.sidebar.header("1. นำเข้าข้อมูล")
up = st.sidebar.file_uploader("Upload CSV/Excel", accept_multiple_files=True)

if up:
    # เรียกใช้ฟังก์ชันตรวจสอบข้อมูล (Validator)
    data, logs = load_and_validate_data(up)
    
    # แสดง Logs การแก้ไขข้อมูล
    if logs:
        with st.sidebar.expander("🛠️ รายงานการซ่อมแซมข้อมูล (Logs)", expanded=True):
            for l in logs:
                if "ลบ" in l or "ตัด" in l: st.warning(l, icon="🧹")
                elif "Error" in l: st.error(l)
                else: st.info(l)
            
    if len(data) == 4:
        st.sidebar.success("✅ ข้อมูลพร้อมใช้งาน")
        t_map = dict(zip(data['Teachers']['TeacherID'], data['Teachers']['CleanName']))
        
        if st.sidebar.button("🚀 สร้างตาราง"):
            with st.spinner("กำลังจัดตารางสอน..."):
                res, una = SchedulerCSP(data['Teachers'], data['Subjects'], data['Rooms'], data['Groups']).generate_schedule(45)
                if [i for l in res.values() for i in l]:
                    df = pd.DataFrame([i for l in res.values() for i in l])
                    df['Teacher_Name'] = df['Teacher_ID'].map(t_map).fillna(df['Teacher_ID'])
                    st.session_state.update(res=df, una=una, t_map=t_map)
                    if not una: st.success("🎉 สำเร็จ 100%")
                    else: st.warning(f"⚠️ จัดไม่ได้ {len(una)} รายการ")
                else: st.error("❌ ไม่สามารถจัดตารางได้")
    else: st.sidebar.warning(f"ไฟล์ไม่ครบ: {set(['Groups','Rooms','Teachers','Subjects']) - data.keys()}")

if 'res' in st.session_state:
    df, t_map = st.session_state.res, st.session_state.t_map
    if st.session_state.una: st.expander("รายการตกหล่น").write(st.session_state.una)
    st.divider()
    
    # Preview Section
    c1, c2 = st.columns([1, 4])
    vkey = c1.radio("มุมมอง:", list(VIEWS.keys()), format_func=lambda x: VIEWS[x]['lbl'])
    cfg = VIEWS[vkey]
    ents = sorted(df[cfg['id']].unique())
    sel = c1.selectbox("เลือก:", ents, format_func=(lambda x: t_map.get(x,x)) if vkey=='Teacher' else (lambda x: x))
    
    if sel:
        sub = df[df[cfg['id']] == sel].copy()
        sub['Disp'] = sub[cfg['cols'][0]] + "<br>" + sub[cfg['cols'][1]] + "<br>" + sub[cfg['cols'][2]]
        piv = sub.pivot_table(index='Day', columns='Period', values='Disp', aggfunc='first').reindex(DAYS_EN).fillna("-")
        
        # --- สร้างตาราง HTML บนหน้าเว็บ (ใส่เวลาตรงนี้) ---
        h = "<table class='custom-table'><thead><tr><th>วัน / เวลา</th>"
        for p in PERIODS:
            if p == 'Lunch':
                time_str = "12:30 - 13:30"
                label = "พักกลางวัน"
            else:
                time_str = TIME_MAP.get(p, "")
                label = f"คาบ {p}"
            # ใส่เวลาบรรทัดแรก + คาบที่บรรทัดสอง
            h += f"<th><span class='time-txt'>{time_str}</span><span class='period-txt'>{label}</span></th>"
        h += "</tr></thead><tbody>"
        
        for d in DAYS_EN:
            h += f"<tr><td style='font-weight:bold; background:#f9f9f9;'>{DAY_MAP[d]}</td>"
            for p in PERIODS:
                v = "พัก" if p=='Lunch' else (piv.at[d,p] if p in piv.columns and pd.notna(piv.at[d,p]) else "-")
                bg = "background:#eee;" if p=='Lunch' else ""
                h += f"<td style='{bg}'>{v}</td>"
            h += "</tr>"
        h += "</tbody></table>"
        
        c2.markdown(f"### {t_map.get(sel,sel) if vkey=='Teacher' else sel}")
        c2.markdown(h, unsafe_allow_html=True)
        
        c2.markdown("#### ℹ️ รายละเอียดรายวิชา")
        c2.table(sub[cfg['leg_c']].drop_duplicates().set_axis(cfg['leg'], axis=1))
        c2.download_button("📄 PDF หน้านี้", gen_pdf(df, sel, vkey, t_map), f"{sel}.pdf", "application/pdf")

    st.divider(); st.subheader("💾 ดาวน์โหลดทั้งหมด")
    cols = st.columns(4)
    cols[0].download_button("📥 Excel รวม", gen_excel(df, t_map), "Master.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    for i, (k, v) in enumerate(VIEWS.items()):
        if cols[i+1].button(f"📄 PDF {v['lbl'].split('(')[0]}"):
            st.session_state[f'p_{k}'] = gen_pdf(df, sorted(df[v['id']].unique()), k, t_map)
        if f'p_{k}' in st.session_state: cols[i+1].download_button("⬇️ โหลด", st.session_state[f'p_{k}'], f"{k}s.pdf")
