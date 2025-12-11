import pandas as pd, random, copy, time

class SchedulerCSP:
    def __init__(self, teachers, subjects, rooms, groups):
        self.rooms, self.master = rooms, self._prep(subjects)
        
        # --- FIX KEYERROR ---
        # รวมรายชื่อกลุ่มเรียนจากทั้งไฟล์ Groups และไฟล์ Subjects (กันพลาดกรณีชื่อไม่ตรง)
        g_in_groups = set(groups['GroupID'].unique())
        g_in_subjects = set(self.master['Group_ID'].unique())
        self.all_groups = list(g_in_groups.union(g_in_subjects))
        
        # Heuristic Maps
        self.t_load = self.master.groupby('Teacher_ID')['Hours'].sum().to_dict()
        self.g_load = self.master.groupby('Group_ID')['Hours'].sum().to_dict()

    def _prep(self, df):
        df = df.copy()
        # แปลง Session เป็น List
        parser = lambda x: [int(s) for s in str(x).split('+')] if '+' in str(x) else [int(x)]
        col = 'Session_Split' if 'Session_Split' in df else ('Hours' if 'Hours' in df else None)
        df['Sessions'] = df[col].apply(parser) if col else [[2]] * len(df)
        return df

    def _reset(self):
        self.sched = {}
        self.busy = {'t': set(), 'g': set(), 'r': set()}
        # สร้าง Load Tracker ให้ครบทุกกลุ่ม (รวมกลุ่มที่ตกหล่นด้วย)
        self.g_daily = {g: {d: 0 for d in ['Mon','Tue','Wed','Thu','Fri']} for g in self.all_groups}

    def check(self, tid, gid, rid, day, dur, start):
        if start + dur - 1 > 8: return False
        for i in range(dur):
            p = start + i
            if (tid, day, p) in self.busy['t'] or (gid, day, p) in self.busy['g'] or (rid, day, p) in self.busy['r']:
                return False
        return True

    def book(self, sub, rid, day, dur, start):
        tid, gid = sub['Teacher_ID'], sub['Group_ID']
        for i in range(dur):
            p = start + i
            self.busy['t'].add((tid, day, p)); self.busy['g'].add((gid, day, p)); self.busy['r'].add((rid, day, p))
            self.sched.setdefault((day, p, gid), []).append({**sub, 'Room_ID': rid, 'Period': p, 'Day': day})
        # Safe Update
        if gid in self.g_daily: self.g_daily[gid][day] += dur

    def try_book(self, sub, dur, rooms, days, agg):
        tid, gid = sub['Teacher_ID'], sub['Group_ID']
        
        # Get Load อย่างปลอดภัย (ถ้าไม่มีให้คืน 0)
        get_load = lambda d: self.g_daily.get(gid, {}).get(d, 0)
        
        d_list = days[:] if agg else sorted(days, key=lambda d: (get_load(d), random.random()))
        if agg: random.shuffle(d_list)
        
        for day in d_list:
            periods = list(range(1, 9))
            if agg: random.shuffle(periods)
            
            for p in periods:
                if p + dur - 1 > 8: continue
                r_list = rooms[:]
                if agg: random.shuffle(r_list)
                
                for r in r_list:
                    if self.check(tid, gid, r, day, dur, p):
                        self.book(sub, r, day, dur, p)
                        return True
        return False

    def solve(self, subs, agg):
        self._reset()
        days, failed = ['Mon','Tue','Wed','Thu','Fri'], []
        
        for idx, row in subs.iterrows():
            rooms = self.rooms[self.rooms['Type'] == row['Room_Type']]['RoomID'].tolist()
            if not rooms: failed.append(idx); continue

            booked_all = True
            for dur in row['Sessions']:
                if self.try_book(row, dur, rooms, days, agg): continue
                
                # Auto-Fragmentation
                parts = [dur//2, dur - dur//2] if dur >= 2 else [dur]
                actual = 0
                for part in parts:
                    if self.try_book(row, part, rooms, days, True): 
                        actual += part
                    else:
                        for _ in range(part):
                            if self.try_book(row, 1, rooms, days, True): actual += 1
                
                if actual < dur: booked_all = False; break
            
            if not booked_all: failed.append(idx)
        return failed

    def generate_schedule(self, timeout_seconds=60):
        start, best_sch, min_fail, best_fail_list = time.time(), {}, float('inf'), []
        
        df = self.master.copy()
        # สูตรความยาก (ครู*50 + ห้อง*20 + ชม*10)
        df['Score'] = df.apply(lambda r: (self.t_load.get(r['Teacher_ID'], 0)*50) + 
                                         (self.g_load.get(r['Group_ID'], 0)*20) + 
                                         (r['Hours']*10), axis=1)
        prio_df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        while time.time() - start < timeout_seconds:
            agg = (time.time() - start) > 5
            fails = self.solve(prio_df, agg)
            
            if len(fails) < min_fail:
                min_fail = len(fails)
                best_sch = copy.deepcopy(self.sched)
                best_fail_list = [f"{r['Subject_Name']} ({r['Group_ID']})" for _, r in prio_df.loc[fails].iterrows()] if fails else []
            
            if min_fail == 0: break
            
            if fails:
                fail_df = prio_df.loc[fails]
                rest_df = prio_df.drop(fails).sample(frac=1).reset_index(drop=True)
                prio_df = pd.concat([fail_df, rest_df]).reset_index(drop=True)
        
        return best_sch, best_fail_list