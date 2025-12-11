import streamlit as st
import pandas as pd
import re
import time
from scheduler_logic import SchedulerCSP
from io import BytesIO
from fpdf import FPDF
from openpyxl.styles import Alignment, Font, Border, Side, PatternFill

st.set_page_config(page_title="ระบบจัดตารางสอน (Final Fixed)", layout="wide")

# ==========================================
# 1. CSS Styling (แก้ไขบั๊กหัวตารางหาย)
# ==========================================
st.markdown("""
<style>
    /* ลบโค้ดที่ซ่อนหัวตารางช่องแรกออก เพื่อไม่ให้กระทบตารางเรียน */
    /* .stTable thead tr th:first-child {display:none} <--- ลบตัวนี้ทิ้ง */
    
    .custom-table {
        width: 100%;
        border-collapse: collapse;
        text-align: center;
        font-family: 'Sarabun', sans-serif;
        margin-bottom: 20px;
    }
    .custom-table th {
        background-color: #1976D2; /* สีน้ำเงินเข้ม */
        color: white;
        padding: 8px;
        border: 1px solid #ddd;
        vertical-align: middle;
        min-width: 85px;
    }
    .custom-table td {
        padding: 8px;
        border: 1px solid #ddd;
        vertical-align: middle;
        font-size: 14px;
    }
    .time-txt { font-size: 13px; font-weight: bold; display: block; margin-bottom: 2px; color: #ffeb3b; }
    .period-txt { font-size: 12px; font-weight: normal; color: white; }
    .day-cell { font-weight: bold; background-color: #f5f5f5; color: #333; width: 100px; }
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
    'Student': {'lbl': 'นักเรียน (Student)', 'id': 'Group_ID', 'cols': ['Room_ID', 'Subject_ID', 'Teacher_Name'], 'leg': ['รหัส', 'ชื่อ', 'ห้อง', 'ครู'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Room_ID', 'Teacher_Name'], 'pfx': 'G-'},
    'Teacher': {'lbl': 'ครูผู้สอน (Teacher)', 'id': 'Teacher_ID', 'cols': ['Room_ID', 'Subject_ID', 'Group_ID'], 'leg': ['รหัส', 'ชื่อ', 'ห้อง', 'นร.'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Room_ID', 'Group_ID'], 'pfx': 'T-'},
    'Room':    {'lbl': 'ห้องเรียน (Room)', 'id': 'Room_ID', 'cols': ['Teacher_Name', 'Subject_ID', 'Group_ID'], 'leg': ['รหัส', 'ชื่อ', 'ครู', 'นร.'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Teacher_Name', 'Group_ID'], 'pfx': 'R-'}
}

# ==========================================
# 3. Data Validation (ระบบตรวจสอบที่ขอกลับมา)
# ==========================================
def clean_str(n): 
    # ฟังก์ชันทำความสะอาดชื่อ (ตัดคำนำหน้า)
    s = str(n).strip()
    for p in ['ว่าที่ร้อยตรี', 'ว่าที่ ร.ต.', 'ดร.', 'ผศ.', 'นางสาว', 'นาย', 'นาง', 'Mr.', 'Ms.']:
        s = s.replace(p, '')
    return s.strip()

def validate_df(df, key, name):
    logs = []
    # 1. Trim Whitespace
    df = df.apply(lambda x: x.str.strip() if x.dtype=='object' else x)
    
    # 2. Check Duplicates
    if df.duplicated().sum() > 0:
        df = df.drop_duplicates()
        logs.append(f"🧹 {name}: ลบข้อมูลซ้ำซ้อนออก")
        
    # 3. Check Key ID
    if key and key in df:
        dups = df[df.duplicated(subset=key)]
        if not dups.empty:
            df = df.drop_duplicates(subset=key)
            logs.append(f"🔧 {name}: แก้ไขรหัสซ้ำ {len(dups)} รายการ")
            
    return df, logs

def load_and_validate(files):
    d, logs = {}, []
    
    # Step 1: Load Files
    for f in files:
        try:
            df = pd.read_csv(f, dtype=str) if f.name.endswith('.csv') else pd.read_excel(f, dtype=str)
            df.columns = [c.strip() for c in df.columns]
            
            if 'GroupID' in df: d['Groups'], l = validate_df(df, 'GroupID', 'Groups')
            elif 'RoomID' in df: d['Rooms'], l = validate_df(df, 'RoomID', 'Rooms')
            elif 'TeacherID' in df:
                df, l = validate_df(df, 'TeacherID', 'Teachers')
                nm = next((c for c in ['Name','Teacher_Name','ชื่อ','ชื่อ-สกุล'] if c in df.columns), None)
                df['CleanName'] = df[nm].apply(clean_str) if nm else df['TeacherID']
                d['Teachers'] = df
            elif 'Subject_ID' in df: d['Subjects'], l = validate_df(df, None, 'Subjects')
            else: l = [f"⚠️ ไม่รู้จักไฟล์: {f.name}"]
            logs.extend(l)
        except Exception as e: logs.append(f"🔥 Error reading {f.name}: {e}")

    # Step 2: Cross-Validation (สำคัญมาก! ตัดข้อมูลขยะทิ้ง)
    if len(d) == 4:
        sub = d['Subjects']
        vt = set(d['Teachers']['TeacherID'])
        vg = set(d['Groups']['GroupID'])
        
        # ตัดวิชาที่รหัสครูผิด
        bad_t = sub[~sub['Teacher_ID'].isin(vt)]
        if not bad_t.empty:
            d['Subjects'] = sub[sub['Teacher_ID'].isin(vt)]
            logs.append(f"❌ ลบวิชาทิ้ง {len(bad_t)} รายการ: รหัสครูไม่มีในฐานข้อมูล")
            
        # ตัดวิชาที่รหัสกลุ่มผิด
        sub = d['Subjects'] # update
        bad_g = sub[~sub['Group_ID'].isin(vg)]
        if not bad_g.empty:
            d['Subjects'] = sub[sub['Group_ID'].isin(vg)]
            logs.append(f"❌ ลบวิชาทิ้ง {len(bad_g)} รายการ: รหัสกลุ่มเรียนผิด")
            
    return d, logs

# ==========================================
# 4. Export Engines
# ==========================================
class PDF(FPDF):
    def footer(self): self.set_y(-15); self.set_font('THSarabunNew','',10); self.cell(0,10,f'หน้า {self.page_no()}',0,0,'R')

def gen_pdf(df, entities, vkey, t_map):
    pdf = PDF('L', 'mm', 'A4'); pdf.set_auto_page_break(True, 15)
    try: pdf.add_font('THSarabunNew','','THSarabunNew.ttf',uni=True)
    except: pdf.add_font('Arial','',10)
    
    cfg = VIEWS[vkey]
    
    # PDF Config (A4 Landscape)
    MARGIN_LEFT = 10
    W_DAY = 25
    W_LUNCH = 20
    W_PERIOD = 27
    H_HEADER = 14
    H_ROW = 22
    
    for ent in ([entities] if isinstance(entities, str) else entities):
        sub = df[df[cfg['id']] == ent]
        if sub.empty: continue
        
        pdf.add_page()
        pdf.set_font('THSarabunNew', '', 20)
        title = t_map.get(ent, ent) if vkey=='Teacher' else ent
        pdf.cell(0, 10, f"ตารางสอน: {title}", 0, 1, 'C')
        pdf.ln(10)
        
        # --- Header ---
        pdf.set_font('THSarabunNew', '', 12)
        start_y = pdf.get_y()
        curr_x = MARGIN_LEFT
        
        # วันที่
        pdf.set_fill_color(25, 118, 210) # Blue Header
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(curr_x, start_y)
        pdf.cell(W_DAY, H_HEADER, "วันที่", 1, 0, 'C', 1)
        curr_x += W_DAY
        
        # เวลา
        for p in PERIODS:
            w = W_LUNCH if p == 'Lunch' else W_PERIOD
            if p == 'Lunch': l1, l2 = "12:30-13:30", "พักกลางวัน"
            else: l1, l2 = TIME_MAP[p], f"คาบ {p}"
            
            pdf.set_xy(curr_x, start_y)
            pdf.cell(w, H_HEADER, "", 1, 0, 'C', 1)
            
            pdf.set_text_color(255, 235, 59) # Yellow Time
            pdf.set_xy(curr_x, start_y + 2)
            pdf.cell(w, 4, l1, 0, 2, 'C')
            
            pdf.set_text_color(255, 255, 255) # White Period
            pdf.cell(w, 4, l2, 0, 0, 'C')
            
            curr_x += w
            
        pdf.ln(H_HEADER); pdf.set_text_color(0, 0, 0)
        
        # --- Grid ---
        for d in DAYS_EN:
            curr_x = MARGIN_LEFT; curr_y = pdf.get_y()
            
            # Day
            pdf.set_font('THSarabunNew', '', 14)
            pdf.set_fill_color(245, 245, 245)
            pdf.set_xy(curr_x, curr_y)
            pdf.cell(W_DAY, H_ROW, DAY_MAP[d], 1, 0, 'C', 1)
            curr_x += W_DAY
            
            # Slots
            for p in PERIODS:
                w = W_LUNCH if p=='Lunch' else W_PERIOD
                pdf.set_xy(curr_x, curr_y)
                if p=='Lunch':
                    pdf.set_fill_color(230, 230, 230)
                    pdf.cell(w, H_ROW, "พัก", 1, 0, 'C', 1)
                else:
                    r = sub[(sub['Day']==d) & (sub['Period']==p)]
                    pdf.set_fill_color(255, 255, 255)
                    pdf.rect(curr_x, curr_y, w, H_ROW)
                    if not r.empty:
                        info = f"{str(r.iloc[0][cfg['cols'][0]])[:15]}\n{str(r.iloc[0][cfg['cols'][1]])[:15]}\n{str(r.iloc[0][cfg['cols'][2]])[:15]}"
                        pdf.set_font('THSarabunNew', '', 10)
                        pdf.set_xy(curr_x, curr_y + 3)
                        pdf.multi_cell(w, 4.5, info, 0, 'C')
                curr_x += w
            pdf.set_y(curr_y + H_ROW)
            
        # --- Legend ---
        pdf.ln(5); pdf.set_font('THSarabunNew', '', 12)
        pdf.cell(0, 8, "รายละเอียดรายวิชา:", 0, 1, 'L')
        pdf.set_fill_color(224, 224, 224)
        wds = [25, 90, 40, 50]
        for i, h in enumerate(cfg['leg']): pdf.cell(wds[i], 7, h, 1, 0, 'C', 1)
        pdf.ln()
        
        pdf.set_font('THSarabunNew', '', 11)
        for _, r in sub[cfg['leg_c']].drop_duplicates().iterrows():
            if pdf.get_y() > 185: pdf.add_page()
            for i, txt in enumerate(r):
                pdf.cell(wds[i], 7, str(txt)[:50], 1, 0, 'L' if i==1 else 'C')
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
                piv.columns = [TIME_MAP.get(c, str(c)).replace("\n", " ") if c!='Lunch' else "12:30-13:30" for c in piv.columns]
                
                sh_name = f"{cfg['pfx']}{str(ent)[:20]}".replace(":","").replace("/","-")
                piv.fillna('').to_excel(writer, sheet_name=sh_name)
                
                ws = writer.sheets[sh_name]
                ws.column_dimensions['A'].width = 15
                for c in range(2, 12): ws.column_dimensions[chr(64+c)].width = 25; ws.cell(row=1, column=c).alignment = align
                for row in ws.iter_rows():
                    for cell in row: cell.alignment = align; cell.border = thin
    return out.getvalue()

# ==========================================
# 5. MAIN UI
# ==========================================
st.sidebar.header("1. นำเข้าข้อมูล")
up = st.sidebar.file_uploader("Upload CSV/Excel", accept_multiple_files=True)

if up:
    data, logs = load_and_validate(up)
    if logs:
        with st.sidebar.expander("🛠️ ผลการตรวจสอบข้อมูล (Validation Logs)", expanded=True):
            for l in logs:
                if "ลบ" in l or "ตัด" in l: st.warning(l, icon="🧹")
                elif "Error" in l: st.error(l)
                else: st.info(l)
            
    if len(data) == 4:
        st.sidebar.success("✅ ข้อมูลพร้อมใช้งาน")
        t_map = dict(zip(data['Teachers']['TeacherID'], data['Teachers']['CleanName']))
        
        if st.sidebar.button("🚀 สร้างตาราง"):
            with st.spinner("กำลังประมวลผล (AI Scheduling)..."):
                res, una = SchedulerCSP(data['Teachers'], data['Subjects'], data['Rooms'], data['Groups']).generate_schedule(45)
                if [i for l in res.values() for i in l]:
                    df = pd.DataFrame([i for l in res.values() for i in l])
                    df['Teacher_Name'] = df['Teacher_ID'].map(t_map).fillna(df['Teacher_ID'])
                    st.session_state.update(res=df, una=una, t_map=t_map)
                    if not una: st.success("🎉 สำเร็จ! จัดตารางได้ครบ 100%")
                    else: st.warning(f"⚠️ จัดไม่ได้ {len(una)} รายการ (เช็คด้านล่าง)")
                else: st.error("❌ ไม่สามารถจัดตารางได้")
    else: st.sidebar.warning(f"ไฟล์ไม่ครบ: {set(['Groups','Rooms','Teachers','Subjects']) - data.keys()}")

if 'res' in st.session_state:
    df, t_map = st.session_state.res, st.session_state.t_map
    if st.session_state.una: st.expander("รายการที่จัดไม่ได้").write(st.session_state.una)
    st.divider()
    
    c1, c2 = st.columns([1, 4])
    vkey = c1.radio("มุมมอง:", list(VIEWS.keys()), format_func=lambda x: VIEWS[x]['lbl'])
    cfg = VIEWS[vkey]
    ents = sorted(df[cfg['id']].unique())
    sel = c1.selectbox("เลือกรายการ:", ents, format_func=(lambda x: t_map.get(x,x)) if vkey=='Teacher' else (lambda x: x))
    
    if sel:
        sub = df[df[cfg['id']] == sel].copy()
        sub['Disp'] = sub[cfg['cols'][0]] + "<br>" + sub[cfg['cols'][1]] + "<br>" + sub[cfg['cols'][2]]
        piv = sub.pivot_table(index='Day', columns='Period', values='Disp', aggfunc='first').reindex(DAYS_EN).fillna("-")
        
        # HTML Table
        h = "<table class='custom-table'><thead><tr><th>วันที่</th>"
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
        
        # --- รายละเอียดรายวิชา ---
        c2.markdown("#### ℹ️ รายละเอียดรายวิชา")
        ref_df = sub[cfg['leg_c']].drop_duplicates()
        ref_df.columns = cfg['leg']
        c2.table(ref_df)
        
        c2.download_button("📄 PDF หน้านี้", gen_pdf(df, sel, vkey, t_map), f"{sel}.pdf", "application/pdf")

    st.divider(); st.subheader("💾 ดาวน์โหลดทั้งหมด")
    cols = st.columns(4)
    cols[0].download_button("📥 Excel รวม", gen_excel(df, t_map), "Master.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    for i, (k, v) in enumerate(VIEWS.items()):
        if cols[i+1].button(f"📄 PDF {v['lbl'].split('(')[0]}"):
            st.session_state[f'p_{k}'] = gen_pdf(df, sorted(df[v['id']].unique()), k, t_map)
        if f'p_{k}' in st.session_state: cols[i+1].download_button("⬇️ โหลด", st.session_state[f'p_{k}'], f"{k}s.pdf")
