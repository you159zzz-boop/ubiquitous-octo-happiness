import streamlit as st
import pandas as pd
import re
import time
from scheduler_logic import SchedulerCSP
from io import BytesIO
from fpdf import FPDF
from openpyxl.styles import Alignment, Font, Border, Side, PatternFill

st.set_page_config(page_title="ระบบจัดตารางสอน (Final A4)", layout="wide")

# ==========================================
# 1. CSS Styling
# ==========================================
st.markdown("""
<style>
    thead tr th:first-child {display:none}
    tbody th {display:none}
    
    .custom-table {
        width: 100%;
        border-collapse: collapse;
        text-align: center;
        font-family: 'Sarabun', sans-serif;
        margin-bottom: 10px;
    }
    .custom-table th {
        background-color: #2E7D32;
        color: white;
        padding: 8px;
        border: 1px solid #ddd;
        vertical-align: middle;
        min-width: 85px;
    }
    .custom-table td {
        padding: 6px;
        border: 1px solid #ddd;
        vertical-align: middle;
        font-size: 13px;
    }
    .time-txt { font-size: 13px; font-weight: bold; display: block; margin-bottom: 2px; color: #ffeb3b; }
    .period-txt { font-size: 11px; font-weight: normal; color: white; }
    .day-cell { font-weight: bold; background-color: #f1f8e9; color: #1b5e20; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. Configuration
# ==========================================
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
    'Student': {'lbl': 'นักเรียน', 'id': 'Group_ID', 'cols': ['Room_ID', 'Subject_ID', 'Teacher_Name'], 'leg': ['รหัส', 'ชื่อวิชา', 'ห้อง', 'ครู'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Room_ID', 'Teacher_Name'], 'pfx': 'G-'},
    'Teacher': {'lbl': 'ครูผู้สอน', 'id': 'Teacher_ID', 'cols': ['Room_ID', 'Subject_ID', 'Group_ID'], 'leg': ['รหัส', 'ชื่อวิชา', 'ห้อง', 'นร.'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Room_ID', 'Group_ID'], 'pfx': 'T-'},
    'Room':    {'lbl': 'ห้องเรียน', 'id': 'Room_ID', 'cols': ['Teacher_Name', 'Subject_ID', 'Group_ID'], 'leg': ['รหัส', 'ชื่อวิชา', 'ครู', 'นร.'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Teacher_Name', 'Group_ID'], 'pfx': 'R-'}
}

# ==========================================
# 3. Validation
# ==========================================
def clean_str(n): 
    s = str(n).strip()
    for p in ['ว่าที่ร้อยตรี', 'ว่าที่ ร.ต.', 'ดร.', 'ผศ.', 'นางสาว', 'นาย', 'นาง', 'Mr.', 'Ms.']:
        s = s.replace(p, '')
    return s.strip()

def validate(df, key, name):
    logs = []
    df = df.apply(lambda x: x.str.strip() if x.dtype=='object' else x)
    if df.duplicated().sum() > 0: df = df.drop_duplicates(); logs.append(f"🧹 {name}: ลบข้อมูลซ้ำ")
    if key and key in df:
        dups = df[df.duplicated(subset=key)]
        if not dups.empty: df = df.drop_duplicates(subset=key); logs.append(f"🔧 {name}: แก้ไขรหัสซ้ำ")
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
                df['CleanName'] = df[nm].apply(clean_str) if nm else df['TeacherID']
                d['Teachers'] = df
            elif 'Subject_ID' in df: d['Subjects'], l = validate(df, None, 'Subjects')
            else: l = [f"⚠️ ไม่รู้จักไฟล์: {f.name}"]
            logs.extend(l)
        except Exception as e: logs.append(f"🔥 Error {f.name}: {e}")

    if len(d) == 4:
        sub = d['Subjects']
        vt, vg = set(d['Teachers']['TeacherID']), set(d['Groups']['GroupID'])
        bad_t = sub[~sub['Teacher_ID'].isin(vt)]
        if not bad_t.empty: d['Subjects'] = sub[sub['Teacher_ID'].isin(vt)]; logs.append(f"❌ ลบ {len(bad_t)} วิชา (รหัสครูผิด)")
        sub = d['Subjects']
        bad_g = sub[~sub['Group_ID'].isin(vg)]
        if not bad_g.empty: d['Subjects'] = sub[sub['Group_ID'].isin(vg)]; logs.append(f"❌ ลบ {len(bad_g)} วิชา (รหัสกลุ่มผิด)")
    return d, logs

# ==========================================
# 4. Export Engines (PDF A4 Optimized)
# ==========================================
class PDF(FPDF):
    def footer(self): 
        self.set_y(-12)
        self.set_font('THSarabunNew','',10)
        self.cell(0,10,f'หน้า {self.page_no()}',0,0,'R')

def gen_pdf(df, entities, vkey, t_map):
    # A4 Landscape: 297mm x 210mm
    pdf = PDF('L', 'mm', 'A4')
    pdf.set_auto_page_break(False) # ปิด Auto Page break เพื่อคุมเองให้จบใน 1 หน้า
    
    try: pdf.add_font('THSarabunNew','','THSarabunNew.ttf',uni=True)
    except: pdf.add_font('Arial','',10)
    
    cfg = VIEWS[vkey]
    
    for ent in ([entities] if isinstance(entities, str) else entities):
        sub = df[df[cfg['id']] == ent]
        if sub.empty: continue
        
        pdf.add_page()
        
        # --- 1. Title ---
        title = t_map.get(ent, ent) if vkey=='Teacher' else ent
        pdf.set_font('THSarabunNew', '', 20)
        pdf.cell(0, 10, f"ตารางสอน: {title}", 0, 1, 'C')
        pdf.ln(10) # เว้นระยะลงมา
        
        # --- 2. Schedule Grid ---
        # Config Dimensions
        col_w_day = 20
        col_w_period = 27
        col_w_lunch = 18
        row_height = 18 # ลดความสูงแถวเพื่อให้พอดีหน้า
        
        # Header Row
        pdf.set_font('THSarabunNew', '', 12)
        pdf.set_fill_color(46, 125, 50) # Green Header
        pdf.set_text_color(255, 255, 255) # White Text
        
        # Day Header
        x_start = pdf.get_x()
        y_start = pdf.get_y()
        pdf.cell(col_w_day, 10, "วัน / เวลา", 1, 0, 'C', 1)
        
        # Period Headers
        for p in PERIODS:
            w = col_w_lunch if p=='Lunch' else col_w_period
            
            # Text Content
            if p == 'Lunch':
                line1, line2 = "12:30-13:30", "พักกลางวัน"
            else:
                line1, line2 = TIME_MAP[p], f"คาบ {p}"
            
            # Manually draw multi-line header
            current_x = pdf.get_x()
            pdf.cell(w, 10, "", 1, 0, 'C', 1) # กรอบ
            
            pdf.set_xy(current_x, y_start + 1)
            pdf.set_font('THSarabunNew', '', 12) # เวลาตัวใหญ่
            pdf.cell(w, 4, line1, 0, 2, 'C')
            pdf.set_font('THSarabunNew', '', 10) # คาบตัวเล็ก
            pdf.cell(w, 4, line2, 0, 0, 'C')
            pdf.set_xy(current_x + w, y_start) # Restore position
            
        pdf.ln(10) # End Header Row
        pdf.set_text_color(0, 0, 0) # Reset text color
        
        # Data Rows
        for d in DAYS_EN:
            pdf.set_font('THSarabunNew', '', 14)
            # Day Cell
            pdf.set_fill_color(241, 248, 233) # Light Green
            pdf.cell(col_w_day, row_height, DAY_MAP[d], 1, 0, 'C', 1)
            
            for p in PERIODS:
                w = col_w_lunch if p=='Lunch' else col_w_period
                if p=='Lunch':
                    pdf.set_fill_color(238, 238, 238)
                    pdf.cell(w, row_height, "พัก", 1, 0, 'C', 1)
                else:
                    r = sub[(sub['Day']==d) & (sub['Period']==p)]
                    if not r.empty:
                        # Extract Data
                        line1 = str(r.iloc[0][cfg['cols'][0]])[:15]
                        line2 = str(r.iloc[0][cfg['cols'][1]])[:15]
                        line3 = str(r.iloc[0][cfg['cols'][2]])[:15]
                        info = f"{line1}\n{line2}\n{line3}"
                        
                        x,y = pdf.get_x(), pdf.get_y()
                        pdf.rect(x,y,w,row_height)
                        pdf.set_font('THSarabunNew', '', 10) # Font เล็กในตาราง
                        pdf.set_xy(x, y + 2)
                        pdf.multi_cell(w, 4.5, info, 0, 'C')
                        pdf.set_xy(x+w, y)
                    else:
                        pdf.cell(w, row_height, "", 1, 0, 'C')
            pdf.ln()
            
        # --- 3. Compact Legend Table ---
        pdf.ln(5)
        pdf.set_font('THSarabunNew', '', 12)
        pdf.cell(0, 6, "รายละเอียดรายวิชา:", 0, 1, 'L')
        
        # Legend Header
        pdf.set_fill_color(224, 224, 224)
        wds = [25, 90, 40, 50] # Adjusted widths
        for i,h in enumerate(cfg['leg']): 
            pdf.cell(wds[i], 7, h, 1, 0, 'C', 1)
        pdf.ln()
        
        # Legend Rows (Smaller Font)
        pdf.set_font('THSarabunNew', '', 11)
        leg_df = sub[cfg['leg_c']].drop_duplicates()
        
        for _, r in leg_df.iterrows():
            # Check for page break
            if pdf.get_y() > 190: # ถ้าใกล้หมดหน้า
                pdf.add_page() # ขึ้นหน้าใหม่ (กรณีวิชาเยอะจัด)
            
            for i, txt in enumerate(r):
                align = 'L' if i==1 else 'C'
                pdf.cell(wds[i], 6, str(txt)[:55], 1, 0, align) # สูงแค่ 6mm พอ
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
                piv.index = piv.index.map(DAY_MAP)
                piv.columns = [TIME_MAP.get(c, str(c)) if c!='Lunch' else "12:30-13:30" for c in piv.columns]
                
                sh_name = f"{cfg['pfx']}{str(ent)[:20]}".replace(":","").replace("/","-")
                piv.fillna('').to_excel(writer, sheet_name=sh_name)
                
                ws = writer.sheets[sh_name]
                ws.column_dimensions['A'].width = 15
                for c in range(2, 12): ws.column_dimensions[chr(64+c)].width = 25; ws.cell(row=1, column=c).alignment = align
                for row in ws.iter_rows():
                    for cell in row: cell.alignment = align; cell.border = thin
    return out.getvalue()

# ==========================================
# 5. Helper for Categorized Download
# ==========================================
def get_categories(df, id_col):
    # แยก Prefix จาก Group ID (เช่น AUTO จาก AUTO-VC1-1)
    cats = {}
    for item in df[id_col].unique():
        prefix = item.split('-')[0] if '-' in str(item) else 'Other'
        if prefix not in cats: cats[prefix] = []
        cats[prefix].append(item)
    return cats

# ==========================================
# 6. MAIN UI
# ==========================================
st.sidebar.header("1. นำเข้าข้อมูล")
up = st.sidebar.file_uploader("Upload CSV/Excel", accept_multiple_files=True)

if up:
    data, logs = load_data(up)
    if logs:
        with st.sidebar.expander("🛠️ บันทึกการตรวจสอบ (Validation Logs)", expanded=True):
            for l in logs:
                if "ลบ" in l or "ตัด" in l: st.warning(l)
                elif "Error" in l: st.error(l)
                else: st.info(l)
            
    if len(data) == 4:
        st.sidebar.success("✅ ข้อมูลพร้อม")
        t_map = dict(zip(data['Teachers']['TeacherID'], data['Teachers']['CleanName']))
        
        if st.sidebar.button("🚀 สร้างตาราง"):
            with st.spinner("กำลังจัดตารางสอน (AI)..."):
                res, una = SchedulerCSP(data['Teachers'], data['Subjects'], data['Rooms'], data['Groups']).generate_schedule(45)
                if [i for l in res.values() for i in l]:
                    df = pd.DataFrame([i for l in res.values() for i in l])
                    df['Teacher_Name'] = df['Teacher_ID'].map(t_map).fillna(df['Teacher_ID'])
                    st.session_state.update(res=df, una=una, t_map=t_map)
                    if not una: st.success("🎉 สำเร็จ 100%")
                    else: st.warning(f"⚠️ จัดไม่ได้ {len(una)} รายการ")
                else: st.error("❌ ล้มเหลว")
    else: st.sidebar.warning(f"ไฟล์ไม่ครบ: {set(['Groups','Rooms','Teachers','Subjects']) - data.keys()}")

if 'res' in st.session_state:
    df, t_map = st.session_state.res, st.session_state.t_map
    if st.session_state.una: st.expander("รายการตกหล่น").write(st.session_state.una)
    st.divider()
    
    # --- Preview ---
    c1, c2 = st.columns([1, 4])
    vkey = c1.radio("มุมมอง:", list(VIEWS.keys()), format_func=lambda x: VIEWS[x]['lbl'])
    cfg = VIEWS[vkey]
    ents = sorted(df[cfg['id']].unique())
    sel = c1.selectbox("เลือก:", ents, format_func=(lambda x: t_map.get(x,x)) if vkey=='Teacher' else (lambda x: x))
    
    if sel:
        sub = df[df[cfg['id']] == sel].copy()
        sub['Disp'] = sub[cfg['cols'][0]] + "<br>" + sub[cfg['cols'][1]] + "<br>" + sub[cfg['cols'][2]]
        piv = sub.pivot_table(index='Day', columns='Period', values='Disp', aggfunc='first').reindex(DAYS_EN).fillna("-")
        
        # HTML Table Construction
        h = "<table class='custom-table'><thead><tr><th>วัน / เวลา</th>"
        for p in PERIODS:
            if p == 'Lunch': time_str, label = "12:30 - 13:30", "พักกลางวัน"
            else: time_str, label = TIME_MAP.get(p, ""), f"คาบ {p}"
            h += f"<th><span class='time-txt'>{time_str}</span><span class='period-txt'>{label}</span></th>"
        h += "</tr></thead><tbody>"
        
        for d in DAYS_EN:
            h += f"<tr><td class='day-cell'>{DAY_MAP[d]}</td>"
            for p in PERIODS:
                v = "พัก" if p=='Lunch' else (piv.at[d,p] if p in piv.columns and pd.notna(piv.at[d,p]) else "-")
                bg = "background:#eee;" if p=='Lunch' else ""
                h += f"<td style='{bg}'>{v}</td>"
            h += "</tr>"
        h += "</tbody></table>"
        
        c2.markdown(f"### {t_map.get(sel,sel) if vkey=='Teacher' else sel}")
        c2.markdown(h, unsafe_allow_html=True)
        
        c2.markdown("#### ℹ️ รายละเอียดรายวิชา")
        ref_df = sub[cfg['leg_c']].drop_duplicates()
        ref_df.columns = cfg['leg']
        c2.table(ref_df)
        c2.download_button("📄 PDF หน้านี้", gen_pdf(df, sel, vkey, t_map), f"{sel}.pdf", "application/pdf")

    st.divider()
    st.subheader("💾 ดาวน์โหลดทั้งหมด")
    
    tab1, tab2 = st.tabs(["📁 รวมเล่ม (All in One)", "📂 แยกตามสาขา (By Major)"])
    
    with tab1:
        cols = st.columns(4)
        cols[0].download_button("📥 Excel รวม", gen_excel(df, t_map), "Master.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        for i, (k, v) in enumerate(VIEWS.items()):
            if cols[i+1].button(f"📄 PDF {v['lbl'].split('(')[0]}"):
                with st.spinner("Generating..."):
                    st.session_state[f'p_{k}'] = gen_pdf(df, sorted(df[v['id']].unique()), k, t_map)
            if f'p_{k}' in st.session_state: cols[i+1].download_button("⬇️ โหลด", st.session_state[f'p_{k}'], f"{k}s_Book.pdf")

    with tab2:
        st.info("💡 ดาวน์โหลด PDF แยกตามสาขาวิชา (เฉพาะมุมมองนักเรียน)")
        # จัดหมวดหมู่ตาม Prefix (เช่น AUTO, ELEC)
        cats = get_categories(df, 'Group_ID')
        
        # สร้าง Grid ปุ่มดาวน์โหลด
        cat_cols = st.columns(4)
        for i, (cat, items) in enumerate(cats.items()):
            col_idx = i % 4
            with cat_cols[col_idx]:
                if st.button(f"📄 สาขา {cat} ({len(items)} ห้อง)"):
                    with st.spinner(f"Creating PDF for {cat}..."):
                        pdf_bytes = gen_pdf(df, sorted(items), 'Student', t_map)
                        # ใช้ Session state แบบ dynamic key เพื่อไม่ให้ปุ่มตีกัน
                        st.session_state[f'pdf_cat_{cat}'] = pdf_bytes
                
                if f'pdf_cat_{cat}' in st.session_state:
                    st.download_button(f"⬇️ โหลด {cat}", st.session_state[f'pdf_cat_{cat}'], f"Schedule_{cat}.pdf", "application/pdf")
