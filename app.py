import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import altair as alt
from datetime import datetime, timedelta
import json
import re

CREDENTIALS_FILE = "credentials.json"
SHEET_NAME = "포커_기록장"
players = ["고", "손", "장", "전", "황", "guest"]
buy_in_amount = 20000

def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = dict(st.secrets["gcp_service_account"]) if "gcp_service_account" in st.secrets else None
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope) if creds_dict else ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"구글 시트 인증 오류: {e}")
        return None

def load_data_from_sheet(client):
    cols = ["회차", "고", "손", "장", "전", "황", "guest", "날짜", "송금상태", "sheet_row"]
    try:
        sheet = client.open(SHEET_NAME).sheet1
        values = sheet.get_all_values()
        if len(values) > 1:
            data = []
            for i, row in enumerate(values[1:]):
                r = row[:9] + [""] * max(0, 9 - len(row))
                r.append(i + 2)
                data.append(r)
            if data: data[0][0] = "총 누적"
            df = pd.DataFrame(data, columns=cols)
            df = df[(df['회차'] == '총 누적') | (df['고'].astype(str).str.strip() != '')]
            for c in players:
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0).astype(int)
            return df
    except: pass
    return pd.DataFrame(columns=cols)

def color_profit_loss(val):
    if isinstance(val, (int, float)):
        if val > 0: return 'background-color: #e3f2fd; color: #000000;'
        elif val < 0: return 'background-color: #ffebee; color: #000000;'
    return ''

def bold_total_row(row):
    return ['font-weight: bold'] * len(row) if row.name == '총 누적' else [''] * len(row)

def calculate_transfers(adjusted_amounts):
    debtors = [[p, abs(a)] for p, a in adjusted_amounts.items() if a < 0]
    creditors = [[p, a] for p, a in adjusted_amounts.items() if a > 0]
    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)
    transactions, i, j = [], 0, 0
    while i < len(debtors) and j < len(creditors):
        d_name, d_amt = debtors[i]
        c_name, c_amt = creditors[j]
        t_amt = min(d_amt, c_amt)
        if t_amt == 0: break
        transactions.append((f"{d_name}->{c_name}", f"{d_name} ➡️ {c_name} : {t_amt:,}원"))
        debtors[i][1] -= t_amt
        creditors[j][1] -= t_amt
        if debtors[i][1] == 0: i += 1
        if creditors[j][1] == 0: j += 1
    return transactions

st.set_page_config(page_title="포커 기록장", layout="wide")
st.title("🃏 가계부")
client = get_gsheet_client()

if 'ledger' not in st.session_state:
    st.session_state.ledger = load_data_from_sheet(client) if client else pd.DataFrame(columns=["회차", "고", "손", "장", "전", "황", "guest", "날짜", "송금상태", "sheet_row"])

# --- 1. 정산 및 추가 ---
st.header("1. 정산 및 추가")
with st.form("input_form"):
    st.write(f"**최종 잔액**과 **추가 바이인 횟수**를 입력하세요. *(체크된 사람은 기본 참가비 {buy_in_amount:,}원 차감)*")
    c_p, c_b, c_a = st.columns([1, 2, 2])
    c_p.write("**참여**"); c_b.write("**최종 잔액**"); c_a.write("**추가 바이인 횟수**")
    
    p_inputs = {}
    for p in players:
        cp, cb, ca = st.columns([1, 2, 2])
        with cp: part = st.checkbox(f"{p}", value=(p != "guest"), key=f"part_{p}")
        with cb: bal = st.number_input(f"{p}잔액", value=0, step=1000, key=f"bal_{p}", label_visibility="collapsed")
        with ca: buyin = st.number_input(f"{p}바이인", min_value=0, value=0, step=1, key=f"buyin_{p}", label_visibility="collapsed")
        p_inputs[p] = {"part": part, "bal": bal, "buyins": buyin}
        
    if st.form_submit_button("정산 및 구글 시트에 저장") and client:
        try:
            raw_amts = {p: (p_inputs[p]["bal"] - (buy_in_amount + p_inputs[p]["buyins"] * buy_in_amount)) if p_inputs[p]["part"] else 0 for p in players}
            amts = list(raw_amts.values())
            t_loss, t_win = abs(sum(a for a in amts if a < 0)), sum(a for a in amts if a > 0)
            adj_amts = {p: round(a * (t_loss / t_win)) if a > 0 and t_win > 0 else a for p, a in raw_amts.items()}
            
            sheet = client.open(SHEET_NAME).sheet1
            all_vals = sheet.get_all_values()
            t_row = next((i + 1 for i, r in enumerate(all_vals) if i >= 2 and (len(r) < 2 or str(r[1]).strip() == "")), max(len(all_vals) + 1, 3))
            
            now_kst = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M:%S')
            final_vals = [adj_amts[p] for p in players] + [now_kst, "{}"] # 새로운 회차는 송금상태 "{}" 빈칸
            
            with st.spinner("저장 중..."):
                if len(all_vals) >= t_row and str(all_vals[t_row-1][0]).strip() != "":
                    sheet.update(values=[final_vals], range_name=f"B{t_row}:I{t_row}")
                else:
                    sheet.update(values=[[f"{t_row-2}회차"] + final_vals], range_name=f"A{t_row}:I{t_row}")
                st.session_state.ledger = load_data_from_sheet(client)
            st.success("✅ 저장 성공!")
        except Exception as e: st.error("입력 오류")

st.divider()

# --- 2. 회차별 정산 확인 ---
st.header("2. 📌 회차별 정산 결과 확인")
if not st.session_state.ledger.empty:
    v_df = st.session_state.ledger[st.session_state.ledger['회차'] != '총 누적']
    if not v_df.empty:
        n_rounds = len(v_df)
        if 'v_idx' not in st.session_state or st.session_state.get('l_rounds', 0) < n_rounds:
            st.session_state.v_idx = n_rounds - 1
        st.session_state.l_rounds = n_rounds
        st.session_state.v_idx = max(0, min(st.session_state.v_idx, n_rounds - 1))

        nc1, nc2, nc3 = st.columns([1, 3, 1])
        with nc1: st.button("◀ 이전 회차", on_click=lambda: st.session_state.update(v_idx=st.session_state.v_idx-1), disabled=(st.session_state.v_idx <= 0), use_container_width=True)
        with nc3: st.button("다음 회차 ▶", on_click=lambda: st.session_state.update(v_idx=st.session_state.v_idx+1), disabled=(st.session_state.v_idx >= n_rounds - 1), use_container_width=True)
        
        t_row = v_df.iloc[st.session_state.v_idx]
        r_name, t_date = t_row['회차'], t_row.get('날짜', '')
        d_str = f" ⏱️({t_date})" if str(t_date).strip() else ""
        
        with nc2: st.markdown(f"<h4 style='text-align: center;'>[{r_name}] 보정 결과 및 송금액<br><span style='font-size: 0.6em; color: gray;'>{d_str}</span></h4>", unsafe_allow_html=True)
        
        t_amts = {p: int(t_row[p]) for p in players}
        c1, c2 = st.columns([1, 1])
        with c1:
            try: st.dataframe(pd.DataFrame([t_amts], index=[r_name]).style.format("{:,}").map(color_profit_loss), use_container_width=True)
            except: st.dataframe(pd.DataFrame([t_amts], index=[r_name]).style.format("{:,}").applymap(color_profit_loss), use_container_width=True)
            
        with c2:
            transfers = calculate_transfers(t_amts)
            if not transfers: st.write("정산할 금액이 없습니다.")
            else:
                s_str = t_row.get('송금상태', '{}')
                try: cur_status = json.loads(s_str) if s_str else {}
                except: cur_status = {}
                
                t_data = [{"t_key": k, "송금 내역": f"💸 {t}", "완료": cur_status.get(k, False)} for k, t in transfers]
                e_df = st.data_editor(pd.DataFrame(t_data), hide_index=True, column_config={"t_key": None, "송금 내역": st.column_config.TextColumn("송금 내역", disabled=True), "완료": st.column_config.CheckboxColumn("✅ 확인")}, use_container_width=True, key=f"ed_{r_name}")
                
                if st.button("💾 체크 상태 구글 시트에 저장", key=f"sv_{r_name}", use_container_width=True):
                    new_stat = json.dumps({r["t_key"]: r["완료"] for _, r in e_df.iterrows()}, ensure_ascii=False)
                    try:
                        client.open(SHEET_NAME).sheet1.update_acell(f"I{t_row.get('sheet_row', 3)}", new_stat)
                        st.session_state.ledger.at[t_row.name, '송금상태'] = new_stat
                        st.success("✅ 저장되었습니다!")
                    except: st.error("저장 실패")

st.divider()

# --- 3. 전체 누적 및 그래프 ---
st.header("3. 전체 누적 및 그래프")
if not st.session_state.ledger.empty:
    t_df = st.session_state.ledger.copy()
    t_df['s_key'] = t_df['회차'].str.extract(r'(\d+)', expand=False).fillna(0).astype(int)
    t_df = t_df.sort_values('s_key')
    d_df = t_df.drop(columns=['s_key', '날짜', '송금상태', 'sheet_row'], errors='ignore').set_index('회차').fillna(0)
    
    c1, c2 = st.columns([1, 2])
    with c1:
        st.subheader("회차 별")
        try: st.dataframe(d_df.style.format("{:,}").map(color_profit_loss).apply(bold_total_row, axis=1), use_container_width=True)
        except: st.dataframe(d_df.style.format("{:,}").applymap(color_profit_loss).apply(bold_total_row, axis=1), use_container_width=True)
        
    with c2:
        st.subheader("📈 누적 금액 변화")
        cb_df = t_df[t_df['s_key'] > 0].copy()
        if not cb_df.empty:
            c_df = cb_df.drop(columns=['s_key', '날짜', '송금상태', 'sheet_row'], errors='ignore').set_index('회차').fillna(0).cumsum()
            c_df['회차_번호'] = cb_df['s_key'].values
            m_df = c_df.melt(id_vars=['회차_번호'], var_name='플레이어', value_name='누적금액')
            st.altair_chart(alt.Chart(m_df).mark_line(point=True).encode(x=alt.X('회차_번호:Q', scale=alt.Scale(domainMin=1), axis=alt.Axis(tickMinStep=1, format='d')), y=alt.Y('누적금액:Q'), color=alt.Color('플레이어:N'), tooltip=['회차_번호', '플레이어', '누적금액']), use_container_width=True)

st.divider()

# --- 4. 관리자 도구 (1~20회차 일괄 시트 업데이트) ---
with st.expander("🛠️ 관리자 도구 (1~20회차 일괄 체크 적용)"):
    st.write("이 버튼을 누르면 구글 시트를 스캔하여 **1회차부터 20회차까지의 송금 내역을 모두 '완료(체크)' 상태로 구글 시트 원본에 덮어씌웁니다.** 딱 한 번만 누르시면 됩니다!")
    if st.button("🚨 1~20회차 구글 시트 일괄 완료 처리 실행", type="primary"):
        with st.spinner("구글 시트 업데이트 중... (약 5~10초 소요)"):
            try:
                sheet = client.open(SHEET_NAME).sheet1
                all_vals = sheet.get_all_values()
                updates = []
                for i, row in enumerate(all_vals):
                    if i < 2: continue # 헤더와 총누적 행 건너뜀
                    r_str = str(row[0])
                    match = re.search(r'\d+', r_str)
                    
                    # 20회차 이하인 경우에만 로직 실행
                    if match and int(match.group()) <= 20:
                        amts = {p: int(str(row[idx+1]).replace(',', '') or 0) for idx, p in enumerate(players)}
                        transfers = calculate_transfers(amts)
                        
                        # 전부 True 로 묶어서 JSON 텍스트 생성
                        status = {t_key: True for t_key, _ in transfers}
                        status_str = json.dumps(status, ensure_ascii=False)
                        
                        # I열(9번째 열) 업데이트 목록에 추가
                        updates.append({'range': f'I{i+1}', 'values': [[status_str]]})
                
                if updates:
                    sheet.batch_update(updates)
                    st.session_state.ledger = load_data_from_sheet(client) # 화면 새로고침
                    st.success("✅ 1~20회차 시트 일괄 업데이트 성공! 이제 접어두시고 평소처럼 쓰시면 됩니다.")
                else:
                    st.info("업데이트할 1~20회차 데이터가 없거나, 시트를 읽지 못했습니다.")
            except Exception as e:
                st.error(f"오류 발생: {e}")

st.link_button("📊 원본 구글 시트에서 데이터 확인하기", "https://docs.google.com/spreadsheets/d/1fg8Hkgfb7LQx0AWJ9p9IyvWnuoOzYHqSgx7SdWZp47k/edit?gid=0#gid=0")
