import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import altair as alt
from datetime import datetime, timedelta

# --- 1. 구글 시트 연동 설정 ---
CREDENTIALS_FILE = "credentials.json"
SHEET_NAME = "포커_기록장"

def get_gsheet_client():
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive"
        ]
        try:
            if "gcp_service_account" in st.secrets:
                creds_dict = dict(st.secrets["gcp_service_account"])
                creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            else:
                creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        except:
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"구글 시트 인증 오류가 발생했습니다: {e}")
        return None

def load_data_from_sheet(client):
    try:
        sheet = client.open(SHEET_NAME).sheet1
        values = sheet.get_all_values()
        
        if len(values) > 1:
            data = [row[:8] for row in values[1:]]
            
            for r in data:
                while len(r) < 8:
                    r.append("")
                    
            if len(data[0]) > 0:
                data[0][0] = "총 누적"
                    
            df = pd.DataFrame(data, columns=["회차", "고", "손", "장", "전", "황", "guest", "날짜"])
            
            df = df[(df['회차'] == '총 누적') | (df['고'].astype(str).str.strip() != '')]
            
            for col in ["고", "손", "장", "전", "황", "guest"]:
                df[col] = df[col].astype(str).str.replace(',', '', regex=False)
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
                
            return df
        else:
            return pd.DataFrame(columns=["회차", "고", "손", "장", "전", "황", "guest", "날짜"])
    except Exception as e:
        st.error(f"데이터를 불러오는 중 문제가 발생했습니다: {e}")
        return pd.DataFrame(columns=["회차", "고", "손", "장", "전", "황", "guest", "날짜"])

def color_profit_loss(val):
    if isinstance(val, (int, float)):
        if val > 0:
            return 'background-color: #e3f2fd; color: #000000;'
        elif val < 0:
            return 'background-color: #ffebee; color: #000000;'
    return ''

def calculate_transfers(adjusted_amounts):
    debtors = []
    creditors = []
    
    for player, amount in adjusted_amounts.items():
        if amount < 0:
            debtors.append([player, abs(amount)])
        elif amount > 0:
            creditors.append([player, amount])
            
    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)
    
    transactions = []
    i, j = 0, 0
    
    while i < len(debtors) and j < len(creditors):
        debtor_name, debt_amount = debtors[i]
        creditor_name, credit_amount = creditors[j]
        
        transfer_amount = min(debt_amount, credit_amount)
        if transfer_amount == 0:
            break
            
        transactions.append(f"💸 **{debtor_name}** ➡️ **{creditor_name}** : {transfer_amount:,}원")
        
        debtors[i][1] -= transfer_amount
        creditors[j][1] -= transfer_amount
        
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
            
    return transactions if transactions else ["정산할 금액이 없습니다."]

st.set_page_config(page_title="포커 기록장", layout="wide")
st.title("🃏 가계부")

client = get_gsheet_client()

if 'ledger' not in st.session_state:
    if client:
        st.session_state.ledger = load_data_from_sheet(client)
    else:
        st.session_state.ledger = pd.DataFrame(columns=["회차", "고", "손", "장", "전", "황", "guest", "날짜"])

players = ["고", "손", "장", "전", "황", "guest"]

# --- 1.5. 게임 기본 설정 (바이인 금액 고정) ---
buy_in_amount = 20000

# --- 2. 정산 및 추가 ---
st.header("1. 정산 및 추가")
    
with st.form("input_form"):
    st.write(f"오늘 게임에 참여한 사람을 체크하고 **최종 잔액**과 **추가 바이인 횟수**를 입력하세요. \n*(체크된 사람은 기본 참가비 {buy_in_amount:,}원이 자동으로 차감 계산됩니다.)*")
    
    # 표 헤더 (타이틀)
    col_p, col_b, col_a = st.columns([1, 2, 2])
    col_p.write("**참여**")
    col_b.write("**최종 잔액**")
    col_a.write("**추가 바이인 횟수**")
    
    player_inputs = {}
    for player in players:
        col_part, col_bal, col_buyin = st.columns([1, 2, 2])
        
        with col_part:
            # guest는 기본적으로 체크 해제(False), 나머지는 체크(True)
            default_part = False if player == "guest" else True
            part = st.checkbox(f"{player}", value=default_part, key=f"main_part_{player}")
            
        with col_bal:
            # 최종 잔액 입력 (label_visibility="collapsed"로 위쪽 라벨 숨김)
            bal = st.number_input(f"{player} 잔액", value=0, step=1000, key=f"main_bal_{player}", label_visibility="collapsed")
            
        with col_buyin:
            # 추가 바이인 횟수 (기본 0)
            buyin = st.number_input(f"{player} 추가바이인", min_value=0, value=0, step=1, key=f"main_buyin_{player}", label_visibility="collapsed")
            
        player_inputs[player] = {"participating": part, "balance": bal, "buyins": buyin}
        
    calculate_btn = st.form_submit_button("정산 및 구글 시트에 저장")

if calculate_btn and client:
    try:
        raw_amounts = {}
        for p in players:
            # ★ 참여 체크박스가 켜져 있을 때만 기본금 2만원 차감 로직 실행
            if player_inputs[p]["participating"]:
                # 순이익 = (최종 잔액) - (기본 20000원 + 추가 바이인 횟수 * 20000원)
                raw_amounts[p] = player_inputs[p]["balance"] - (buy_in_amount + (player_inputs[p]["buyins"] * buy_in_amount))
            else:
                # 참여하지 않은 사람은 무조건 0원
                raw_amounts[p] = 0
        
        amounts = list(raw_amounts.values())
        total_loss = abs(sum(a for a in amounts if a < 0))
        total_win = sum(a for a in amounts if a > 0)
        
        adjusted_amounts = {}
        for player in players:
            amount = raw_amounts[player]
            if amount > 0 and total_win > 0:
                adjusted_amounts[player] = round(amount * (total_loss / total_win))
            else:
                adjusted_amounts[player] = amount
                
        sheet = client.open(SHEET_NAME).sheet1
        all_values = sheet.get_all_values()
        
        target_row = None
        for i, row in enumerate(all_values):
            if i < 2: continue
            
            if len(row) < 2 or str(row[1]).strip() == "":
                target_row = i + 1
                break
                
        if target_row is None:
            target_row = max(len(all_values) + 1, 3)

        now_kst = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M:%S')
        final_values_with_time = [adjusted_amounts[p] for p in players] + [now_kst]
            
        with st.spinner("구글 시트에 당일 순이익 저장 중..."):
            current_row_val = all_values[target_row-1] if target_row <= len(all_values) else []
            has_round_name = len(current_row_val) > 0 and str(current_row_val[0]).strip() != ""
            
            if not has_round_name:
                round_str = f"{target_row-2}회차"
                sheet.update(values=[[round_str] + final_values_with_time], range_name=f"A{target_row}:H{target_row}")
            else:
                sheet.update(values=[final_values_with_time], range_name=f"B{target_row}:H{target_row}")
            
            st.session_state.ledger = load_data_from_sheet(client)
            
        st.success("해당 회차의 정산 결과가 구글 시트에 성공적으로 저장되었습니다!")
        
    except ValueError:
        st.error("입력값을 확인해주세요.")

st.divider()

# --- 3. 최근 회차 정산 요약 (모두가 볼 수 있는 고정 영역) ---
st.header("2. 📌 가장 최근 회차 정산 결과")

if not st.session_state.ledger.empty:
    valid_rounds_df = st.session_state.ledger[st.session_state.ledger['회차'] != '총 누적']
    
    if not valid_rounds_df.empty:
        last_row = valid_rounds_df.iloc[-1]
        last_round_name = last_row['회차']
        last_amounts = {p: int(last_row[p]) for p in players}
        
        last_date = last_row.get('날짜', '')
        date_str = f" ⏱️({last_date})" if str(last_date).strip() != '' else ""
        
        st.subheader(f"[{last_round_name}] 보정 결과 및 송금액 {date_str}")
        
        col_last1, col_last2 = st.columns([1, 1])
        
        with col_last1:
            last_df = pd.DataFrame([last_amounts], index=[last_round_name])
            try:
                styled_last = last_df.style.format("{:,}").map(color_profit_loss)
            except AttributeError:
                styled_last = last_df.style.format("{:,}").applymap(color_profit_loss)
            st.dataframe(styled_last, use_container_width=True)
            
        with col_last2:
            transfers = calculate_transfers(last_amounts)
            for t in transfers:
                st.write(t)
    else:
        st.info("아직 완료된 회차가 없습니다.")
else:
    st.info("아직 기록된 데이터가 없습니다.")

st.divider()

# --- 4. 기록 및 그래프 ---
st.header("3. 전체 누적 및 그래프")

if not st.session_state.ledger.empty:
    temp_df = st.session_state.ledger.copy()
    
    temp_df['sort_key'] = temp_df['회차'].str.extract(r'(\d+)', expand=False).fillna(0).astype(int)
    temp_df = temp_df.sort_values('sort_key')
    
    display_df = temp_df.drop(columns=['sort_key', '날짜'], errors='ignore').set_index('회차').fillna(0)
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("회차 별")
        try:
            styled_df = display_df.style.format("{:,}").map(color_profit_loss)
        except AttributeError:
            styled_df = display_df.style.format("{:,}").applymap(color_profit_loss)
            
        st.dataframe(styled_df, use_container_width=True)
        
    with col2:
        st.subheader("📈 플레이어별 누적 금액 변화")
        
        chart_base_df = temp_df[temp_df['sort_key'] > 0].copy()
        
        if not chart_base_df.empty:
            calc_df = chart_base_df.drop(columns=['sort_key', '날짜'], errors='ignore').set_index('회차').fillna(0)
            cumulative_df = calc_df.cumsum()
            
            chart_df = cumulative_df.copy()
            chart_df['회차_번호'] = chart_base_df['sort_key'].values
            
            melted_df = chart_df.melt(id_vars=['회차_번호'], var_name='플레이어', value_name='누적금액')
            
            chart = alt.Chart(melted_df).mark_line(point=True).encode(
                x=alt.X('회차_번호:Q', 
                        scale=alt.Scale(domainMin=1), 
                        axis=alt.Axis(tickMinStep=1, format='d', title='회차')), 
                y=alt.Y('누적금액:Q', title='누적 수익 (원)'),
                color=alt.Color('플레이어:N', legend=alt.Legend(title="플레이어")),
                tooltip=['회차_번호', '플레이어', '누적금액']
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("아직 누적 그래프를 그릴 회차 데이터가 없습니다.")
else:
    st.info("아직 기록된 데이터가 없습니다. 위에서 새 회차를 등록해 보세요.")

st.divider()

st.link_button("📊 원본 구글 시트에서 데이터 확인하기", "https://docs.google.com/spreadsheets/d/1fg8Hkgfb7LQx0AWJ9p9IyvWnuoOzYHqSgx7SdWZp47k/edit?gid=0#gid=0")
