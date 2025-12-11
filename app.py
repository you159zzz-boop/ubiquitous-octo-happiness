import streamlit as st
import pandas as pd
import re
import time
from scheduler_logic import SchedulerCSP
from io import BytesIO
from fpdf import FPDF
from openpyxl.styles import Alignment, Font, Border, Side, PatternFill

st.set_page_config(page_title="ระบบจัดตารางสอน (PDF Perfect)", layout="wide")

# ==========================================
# 1. CSS Styling (หน้าเว็บ)
# ==========================================
st.markdown("""
<style>
    /* ซ่อนตารางเดิม */
    thead tr th:first-child {display:none}
    tbody th {display:none}
    
    /* ตาราง HTML Custom */
    .custom-table {
        width: 100%;
        border-collapse: collapse;
        text-align: center;
        font-family: 'Sarabun', sans-serif;
        margin-bottom: 20px;
        table-layout: fixed; /* บังคับขนาดคอลัมน์ให้เท่ากัน */
    }
    /* บังคับโชว์หัวตารางช่องแรก (วันที่) */
    .custom-table thead tr th:first-child {
        display: table-cell !important;
        width: 100px;
    }
    .custom-table th {
        background-color: #2E7D32;
        color: white;
        padding: 5px;
        border: 1px solid #ddd;
        vertical-align: middle;
        font-size: 14px;
    }
    .custom-table td {
        padding: 5px;
        border: 1px solid #ddd;
        vertical-align: middle;
        font-size: 13px;
        word-wrap: break-word;
    }
    .time-txt { font-size: 12px; font-weight: bold; display: block; margin-bottom: 2px; color: #ffeb3b; }
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
    'Student': {'lbl': 'นักเรียน (Student)', 'id': 'Group_ID', 'cols': ['Room_ID', 'Subject_ID', 'Teacher_Name'], 'leg': ['รหัส', 'ชื่อ', 'ห้อง', 'ครู'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Room_ID', 'Teacher_Name'], 'pfx': 'G-'},
    'Teacher': {'lbl': 'ครูผู้สอน (Teacher)', 'id': 'Teacher_ID', 'cols': ['Room_ID', 'Subject_ID', 'Group_ID'], 'leg': ['รหัส', 'ชื่อ', 'ห้อง', 'นร.'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Room_ID', 'Group_ID'], 'pfx': 'T-'},
    'Room':    {'lbl': 'ห้องเรียน (Room)', 'id': 'Room_ID', 'cols': ['Teacher_Name', 'Subject_ID', 'Group_ID'], 'leg': ['รหัส', 'ชื่อ', 'ครู', 'นร.'], 'leg_c': ['Subject_ID', 'Subject_Name', 'Teacher_Name', 'Group_ID'], 'pfx': 'R-'}
}

# ==========================================
# 3. Validation Logic
# ==========================================
def clean_str(n): 
    s = str(n).strip()
    for p in ['ว่าที่ร้อยตรี', 'ว่าที่ ร.ต.', 'ดร.', 'ผศ.', 'นางสาว', 'นาย', 'นาง', 'Mr.', 'Ms.']:
        s = s.replace(p, '')
    return s.strip()

def validate(df, key, name):
    logs = []
    df = df.apply(lambda x: x.str.strip() if x.dtype=='object' else x)
    if df.duplicated().sum() > 0:
        df = df.drop_duplicates()
        logs.append(f"🧹 {name}: ลบข้อมูลซ้ำซ้อนออก")
    if key and key in df:
        dups = df[df.duplicated(subset=key)]
        if not dups.empty:
            df = df.drop_duplicates(subset=key)
            logs.append(f"🔧 {name}: แก้ไขรหัสซ้ำ {len(dups)} รายการ")
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
            else: l = [f"⚠️ ไฟล์ไม่ระบุประเภท: {f.name}"]
            logs.extend(l)
        except Exception as e: logs.append(f"🔥 อ่านไฟล์ไม่ได้ {f.name}: {e}")

    if len(d) == 4:
        sub = d['Subjects']
        vt, vg = set(d['Teachers']['TeacherID']), set(d['Groups']['GroupID'])
        bad_t = sub[~sub['Teacher_ID'].isin(vt)]
        if not bad_t.empty:
            d['Subjects'] = sub[sub['Teacher_ID'].isin(vt)]
            logs.append(f"❌ ลบ {len(bad_t)} วิชาทิ้ง (รหัสครูผิด)")
        sub = d['Subjects']
        bad_g = sub[~sub['Group_ID'].isin(vg)]
        if not bad_g.empty:
            d['Subjects'] = sub[sub['Group_ID'].isin(vg)]
            logs.append(f"❌ ลบ {len(bad_g)} วิชาทิ้ง (รหัสกลุ่มผิด)")
    return d, logs

# ==========================================
# 4. Export Engines (Fixed PDF Layout)
# ==========================================
class PDF(FPDF):
    def footer(self): 
        self.set_y(-12)
        self.set_font('THSarabunNew','',10)
        self.cell(0,10,f'หน้า {self.page_no()}',0,0,'R')

def gen_pdf(df, entities, vkey, t_map):
    # A4 Landscape: 297mm x 210mm
    pdf = PDF('L', 'mm', 'A4')
    pdf.set_auto_page_break(False)
    
    try: pdf.add_font('THSarabunNew','','THSarabunNew.ttf',uni=True)
    except: pdf.add_font('Arial','',10)
    
    cfg = VIEWS[vkey]
    
    # PDF Dimension Config (Tight & Fit)
    MARGIN_LEFT = 8
    W_DAY = 22
    W_LUNCH = 15
    W_PERIOD = 28
    H_HEADER = 14
    H_ROW = 20 # ลดความสูงแถวลงเล็กน้อยให้พอดี
    
    for ent in ([entities] if isinstance(entities, str) else entities):
        sub = df[df[cfg['id']] == ent]
        if sub.empty: continue
        
        pdf.add_page()
        
        # --- 1. Title ---
        title = t_map.get(ent, ent) if vkey=='Teacher' else ent
        pdf.set_font('THSarabunNew', '', 18)
        pdf.cell(0, 8, f"ตารางสอน: {title}", 0, 1, 'C')
        pdf.ln(5)
        
        # --- 2. Header ---
        pdf.set_font('THSarabunNew', '', 11)
        start_y = pdf.get_y()
        curr_x = MARGIN_LEFT
        
        # Day Header
        pdf.set_fill_color(46, 125, 50) 
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(curr_x, start_y)
        pdf.cell(W_DAY, H_HEADER, "วันที่", 1, 0, 'C', 1)
        curr_x += W_DAY
        
        # Period Headers
        for p in PERIODS:
            w = W_LUNCH if p == 'Lunch' else W_PERIOD
            l1 = "12:30-13:30" if p == 'Lunch' else TIME_MAP[p]
            l2 = "พักกลางวัน" if p == 'Lunch' else f"คาบ {p}"
            
            pdf.set_xy(curr_x, start_y)
            pdf.cell(w, H_HEADER, "", 1, 0, 'C', 1)
            
            pdf.set_text_color(255, 235, 59)
            pdf.set_xy(curr_x, start_y + 2)
            pdf.cell(w, 4, l1, 0, 2, 'C')
            
            pdf.set_text_color(255, 255, 255)
            pdf.cell(w, 4, l2, 0, 0, 'C')
            
            curr_x += w
            
        pdf.ln(H_HEADER); pdf.set_text_color(0, 0, 0)
        
        # --- 3. Grid Rows (Fix Overflow) ---
        for d in DAYS_EN:
            curr_x = MARGIN_LEFT; curr_y = pdf.get_y()
            
            # Day Cell
            pdf.set_font('THSarabunNew', '', 13)
            pdf.set_fill_color(241, 248, 233)
            pdf.set_xy(curr_x, curr_y)
            pdf.cell(W_DAY, H_ROW, DAY_MAP[d], 1, 0, 'C', 1)
            curr_x += W_DAY
            
            # Content Cells
            for p in PERIODS:
                w = W_LUNCH if p=='Lunch' else W_PERIOD
                pdf.set_xy(curr_x, curr_y)
                
                if p=='Lunch':
                    pdf.set_fill_color(230, 230, 230)
                    pdf.cell(w, H_ROW, "พัก", 1, 0, 'C', 1)
                else:
                    r = sub[(sub['Day']==d) & (sub['Period']==p)]
                    pdf.set_fill_color(255, 255, 255)
                    pdf.rect(curr_x, curr_y, w, H_ROW) # วาดกรอบก่อน
                    
                    if not r.empty:
                        # Extract & Truncate Data (สำคัญ: ตัดคำให้สั้นพอดีช่อง)
                        l1 = str(r.iloc[0][cfg['cols'][0]])[:12] # ห้อง (สั้นๆ)
                        l2 = str(r.iloc[0][cfg['cols'][1]])[:14] # รหัสวิชา
                        l3 = str(r.iloc[0][cfg['cols'][2]])[:14] # ชื่อครู/กลุ่ม
                        
                        # ใช้ Cell แทน MultiCell เพื่อคุมบรรทัดเอง (แก้ปัญหาล้น)
                        pdf.set_font('THSarabunNew', '', 9) # ฟอนต์เล็ก 9pt
                        
                        # บรรทัด 1 (บน)
                        pdf.set_xy(curr_x, curr_y + 2)
                        pdf.cell(w, 4, l1, 0, 0, 'C')
                        
                        # บรรทัด 2 (กลาง)
                        pdf.set_xy(curr_x, curr_y + 7) 
                        pdf.cell(w, 4, l2, 0, 0, 'C')
                        
                        # บรรทัด 3 (ล่าง)
                        pdf.set_xy(curr_x, curr_y + 12)
                        pdf.cell(w, 4, l3, 0, 0, 'C')
                
                curr_x += w
            pdf.set_y(curr_y + H_ROW)
            
        # --- 4. Legend (Compact) ---
        pdf.ln(3)
        pdf.set_font('THSarabunNew', '', 11)
        pdf.cell(0, 6, "รายละเอียดรายวิชา:", 0, 1, 'L')
        
        pdf.set_fill_color(224, 224, 224)
        wds = [25, 90, 40, 50]
        for i, h in enumerate(cfg['leg']): pdf.cell(wds[i], 6, h, 1, 0, 'C', 1)
        pdf.ln()
        
        pdf.set_font('THSarabunNew', '', 10)
        leg_df = sub[cfg['leg_c']].drop_duplicates()
        for _, r in leg_df.iterrows():
            if pdf.get_y() > 190: pdf.add_page() # Check Page break
            for i, txt in enumerate(r):
                align = 'L' if i==1 else 'C'
                pdf.cell(wds[i], 6, str(txt)[:50], 1, 0, align)
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
    data, logs = load_data(up)
    if logs:
        with st.sidebar.expander("🛠️ บันทึกการตรวจสอบ (Validation Logs)", expanded=True):
            for l in logs:
                if "ลบ" in l or "ตัด" in l: st.warning(l, icon="🧹")
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
                    else: st.warning(f"⚠️ ตกหล่น {len(una)} วิชา")
                else: st.error("❌ ล้มเหลว")
    else: st.sidebar.warning(f"ไฟล์ไม่ครบ: {set(['Groups','Rooms','Teachers','Subjects']) - data.keys()}")

if 'res' in st.session_state:
    df, t_map = st.session_state.res, st.session_state.t_map
    if st.session_state.una: st.expander("รายการตกหล่น").write(st.session_state.una)
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
        piv = sub.pivot_table(index='Day', columns='Period', values='Disp', aggfunc='first').reindex(DAYS_EN).fillna("-")
        
        # HTML Table Construction
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
        
        # Legend
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
