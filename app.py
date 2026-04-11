import streamlit as st
import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import altair as alt
from datetime import datetime, timedelta
import json

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
            data = []
            for i, row in enumerate(values[1:]):
                r = row[:9]
                while len(r) < 9:
                    r.append("")
                r.append(i + 2)
                data.append(r)
                    
            if len(data[0]) > 0:
                data[0][0] = "총 누적"
                    
            df = pd.DataFrame(data, columns=["회차", "고", "손", "장", "전", "황", "문", "날짜", "송금상태", "sheet_row"])
            
            df = df[(df['회차'] == '총 누적') | (df['고'].astype(str).str.strip() != '')]
            
            for col in ["고", "손", "장", "전", "황", "문"]:
                df[col] = df[col].astype(str).str.replace(',', '', regex=False)
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
                
            return df
        else:
            return pd.DataFrame(columns=["회차", "고", "손", "장", "전", "황", "문", "날짜", "송금상태", "sheet_row"])
    except Exception as e:
        st.error(f"데이터를 불러오는 중 문제가 발생했습니다: {e}")
        return pd.DataFrame(columns=["회차", "고", "손", "장", "전", "황", "문", "날짜", "송금상태", "sheet_row"])

def color_profit_loss(val):
    if isinstance(val, (int, float)):
        if val > 0:
            return 'background-color: #e3f2fd; color: #000000;'
        elif val < 0:
            return 'background-color: #ffebee; color: #000000;'
    return ''

def bold_total_row(row):
    if row.name == '총 누적':
        return ['font-weight: bold'] * len(row)
    return [''] * len(row)

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
            
        t_key = f"{debtor_name}->{creditor_name}"
        t_text = f"{debtor_name} ➡️ {creditor_name} : {transfer_amount:,}원"
        transactions.append((t_key, t_text))
        
        debtors[i][1] -= transfer_amount
        creditors[j][1] -= transfer_amount
        
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
            
    return transactions

st.set_page_config(page_title="포커 기록장", layout="wide")
st.title("🃏 가계부")

client = get_gsheet_client()

if 'ledger' not in st.session_state:
    if client:
        st.session_state.ledger = load_data_from_sheet(client)
    else:
        st.session_state.ledger = pd.DataFrame(columns=["회차", "고", "손", "장", "전", "황", "문", "날짜", "송금상태", "sheet_row"])

players = ["고", "손", "장", "전", "황", "문"]

# --- 2. 정산 및 추가 ---
st.header("1. 정산 및 추가")

buy_in_amount = st.radio(
    "👉 **오늘의 기본 참가비 (1회 바이인 금액)를 선택하세요:**",
    options=[20000, 10000],
    format_func=lambda x: f"{x:,}원",
    horizontal=True
)
    
with st.form("input_form"):
    st.write("오늘 게임에 참여한 사람을 체크하고 **최종 잔액**과 **추가 바이인 횟수**를 입력하세요.")
    
    col_p, col_b, col_a = st.columns([1, 2, 2])
    col_p.write("**참여**")
    col_b.write("**최종 잔액**")
    col_a.write("**추가 바이인 횟수**")
    
    player_inputs = {}
    for player in players:
        col_part, col_bal, col_buyin = st.columns([1, 2, 2])
        
        with col_part:
            default_part = False if player == "문" else True
            part = st.checkbox(f"{player}", value=default_part, key=f"main_part_{player}")
            
        with col_bal:
            bal = st.number_input(f"{player} 잔액", value=0, step=1000, key=f"main_bal_{player}", label_visibility="collapsed")
            
        with col_buyin:
            buyin = st.number_input(f"{player} 추가바이인", min_value=0, value=0, step=1, key=f"main_buyin_{player}", label_visibility="collapsed")
            
        player_inputs[player] = {"participating": part, "balance": bal, "buyins": buyin}
        
    calculate_btn = st.form_submit_button("정산 및 구글 시트에 저장")

if calculate_btn and client:
    try:
        raw_amounts = {}
        for p in players:
            if player_inputs[p]["participating"]:
                raw_amounts[p] = player_inputs[p]["balance"] - (buy_in_amount + (player_inputs[p]["buyins"] * buy_in_amount))
            else:
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
        final_values_with_time = [adjusted_amounts[p] for p in players] + [now_kst, "{}"]
            
        with st.spinner("구글 시트에 당일 순이익 저장 중..."):
            current_row_val = all_values[target_row-1] if target_row <= len(all_values) else []
            has_round_name = len(current_row_val) > 0 and str(current_row_val[0]).strip() != ""
            
            if not has_round_name:
                round_str = f"{target_row-2}회차"
                sheet.update(values=[[round_str] + final_values_with_time], range_name=f"A{target_row}:I{target_row}")
            else:
                sheet.update(values=[final_values_with_time], range_name=f"B{target_row}:I{target_row}")
            
            st.session_state.ledger = load_data_from_sheet(client)
            
        st.success("해당 회차의 정산 결과가 구글 시트에 성공적으로 저장되었습니다!")
        
    except ValueError:
        st.error("입력값을 확인해주세요.")

st.divider()

# --- 3. 회차별 정산 결과 ---
st.header("2. 📌 회차별 정산 결과 확인")

if not st.session_state.ledger.empty:
    valid_rounds_df = st.session_state.ledger[st.session_state.ledger['회차'] != '총 누적']
    
    if not valid_rounds_df.empty:
        num_rounds = len(valid_rounds_df)
        
        if 'view_idx' not in st.session_state:
            st.session_state.view_idx = num_rounds - 1
        if 'last_num_rounds' not in st.session_state:
            st.session_state.last_num_rounds = num_rounds
            
        if num_rounds > st.session_state.last_num_rounds:
            st.session_state.view_idx = num_rounds - 1
        st.session_state.last_num_rounds = num_rounds
        
        if st.session_state.view_idx >= num_rounds:
            st.session_state.view_idx = num_rounds - 1
        if st.session_state.view_idx < 0:
            st.session_state.view_idx = 0

        def go_prev():
            st.session_state.view_idx -= 1
        def go_next():
            st.session_state.view_idx += 1
            
        nav_col1, nav_col2, nav_col3 = st.columns([1, 3, 1])
        
        with nav_col1:
            st.button("◀ 이전 회차", on_click=go_prev, disabled=(st.session_state.view_idx <= 0), use_container_width=True)
            
        target_row = valid_rounds_df.iloc[st.session_state.view_idx]
        target_round_name = target_row['회차']
        target_date = target_row.get('날짜', '')
        date_str = f" ⏱️({target_date})" if str(target_date).strip() != '' else ""
        
        df_index = target_row.name
        sheet_row_num = target_row.get('sheet_row', 3)
        status_str = target_row.get('송금상태', '{}')
        
        try:
            current_status = json.loads(status_str) if status_str else {}
        except:
            current_status = {}
        
        with nav_col2:
            st.markdown(f"<h4 style='text-align: center;'>[{target_round_name}] 보정 결과 및 송금액<br><span style='font-size: 0.6em; color: gray;'>{date_str}</span></h4>", unsafe_allow_html=True)
            
        with nav_col3:
            st.button("다음 회차 ▶", on_click=go_next, disabled=(st.session_state.view_idx >= num_rounds - 1), use_container_width=True)
        
        target_amounts = {p: int(target_row[p]) for p in players}
        
        col_last1, col_last2 = st.columns([1, 1])
        
        with col_last1:
            target_df = pd.DataFrame([target_amounts], index=[target_round_name])
            try:
                styled_target = target_df.style.format("{:,}").map(color_profit_loss)
            except AttributeError:
                styled_target = target_df.style.format("{:,}").applymap(color_profit_loss)
            st.dataframe(styled_target, use_container_width=True)
            
        with col_last2:
            transfers = calculate_transfers(target_amounts)
            if not transfers:
                st.write("정산할 금액이 없습니다.")
            else:
                transfer_data = []
                for t_key, t_text in transfers:
                    is_checked = current_status.get(t_key, False)
                    transfer_data.append({"t_key": t_key, "송금 내역": f"💸 {t_text}", "완료": is_checked})
                
                tdf = pd.DataFrame(transfer_data)
                
                edited_tdf = st.data_editor(
                    tdf,
                    hide_index=True,
                    column_config={
                        "t_key": None, 
                        "송금 내역": st.column_config.TextColumn("송금 내역", disabled=True),
                        "완료": st.column_config.CheckboxColumn("✅ 확인")
                    },
                    use_container_width=True,
                    key=f"editor_{target_round_name}"
                )
                
                if st.button("💾 체크 상태 구글 시트에 저장", key=f"save_{target_round_name}", use_container_width=True):
                    new_status = {row["t_key"]: row["완료"] for _, row in edited_tdf.iterrows()}
                    new_status_str = json.dumps(new_status, ensure_ascii=False)
                    
                    with st.spinner("구글 시트에 저장 중..."):
                        try:
                            sheet = client.open(SHEET_NAME).sheet1
                            sheet.update_acell(f"I{sheet_row_num}", new_status_str)
                            st.session_state.ledger.at[df_index, '송금상태'] = new_status_str
                            st.success("✅ 저장되었습니다!")
                        except Exception as e:
                            st.error(f"저장 실패: {e}")
                            
        # ---------------------------------------------------------
        # ★ 새로 추가된 기능: 전체 미수금 리스트 (아직 안 받은 돈 모아보기)
        # ---------------------------------------------------------
        st.markdown("<br><hr><br>", unsafe_allow_html=True)
        st.markdown("### 🚨 미수금 리스트 (아직 정산되지 않은 내역)")
        
        unpaid_data = []
        original_statuses = {}
        
        # 모든 회차를 돌면서 체크 안 된 항목 수집
        for idx, row in valid_rounds_df.iterrows():
            s_row = row.get('sheet_row')
            if pd.isna(s_row): continue
                
            s_str = row.get('송금상태', '{}')
            try:
                status = json.loads(s_str) if s_str else {}
            except:
                status = {}
                
            original_statuses[s_row] = status
            t_amts = {p: int(row[p]) for p in players}
            transfers = calculate_transfers(t_amts)
            
            for t_key, t_text in transfers:
                # 상태가 False이거나 아예 데이터가 없으면 미수금
                if not status.get(t_key, False):
                    unpaid_data.append({
                        "sheet_row": s_row,
                        "t_key": t_key,
                        "회차": row['회차'],
                        "송금 내역": f"💸 {t_text}",
                        "완료": False
                    })
                    
        if unpaid_data:
            unpaid_df = pd.DataFrame(unpaid_data)
            edited_unpaid = st.data_editor(
                unpaid_df,
                hide_index=True,
                column_config={
                    "sheet_row": None,  # 숨김 처리
                    "t_key": None,      # 숨김 처리
                    "회차": st.column_config.TextColumn("회차", disabled=True),
                    "송금 내역": st.column_config.TextColumn("송금 내역", disabled=True),
                    "완료": st.column_config.CheckboxColumn("✅ 확인")
                },
                use_container_width=True,
                key="unpaid_editor"
            )
            
            if st.button("💾 선택한 미수금 일괄 완료 처리", type="primary", use_container_width=True):
                updates_by_row = {}
                
                # 체크된 항목만 찾아서 원본 JSON에 병합
                for _, r in edited_unpaid.iterrows():
                    if r["완료"]:
                        sr = r["sheet_row"]
                        tk = r["t_key"]
                        if sr not in updates_by_row:
                            updates_by_row[sr] = original_statuses[sr].copy()
                        updates_by_row[sr][tk] = True
                        
                if updates_by_row:
                    with st.spinner("구글 시트에 미수금 정산 저장 중..."):
                        try:
                            sheet = client.open(SHEET_NAME).sheet1
                            batch_data = []
                            for sr, new_stat in updates_by_row.items():
                                batch_data.append({
                                    'range': f'I{sr}',
                                    'values': [[json.dumps(new_stat, ensure_ascii=False)]]
                                })
                            sheet.batch_update(batch_data) # 여러 회차를 한 번에 통신(최적화)
                            st.session_state.ledger = load_data_from_sheet(client)
                            st.success("✅ 선택한 미수금이 성공적으로 완료 처리되었습니다!")
                            st.rerun() # 화면 새로고침하여 미수금 리스트 업데이트
                        except Exception as e:
                            st.error(f"저장 실패: {e}")
                else:
                    st.warning("체크된 항목이 없습니다. 완료할 내역을 체크해 주세요.")
        else:
            st.success("🎉 모든 회차의 정산이 완벽하게 끝났습니다! (미수금 0원)")

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
    
    display_df = temp_df.drop(columns=['sort_key', '날짜', '송금상태', 'sheet_row'], errors='ignore').set_index('회차').fillna(0)
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("회차 별")
        try:
            styled_df = display_df.style.format("{:,}").map(color_profit_loss).apply(bold_total_row, axis=1)
        except AttributeError:
            styled_df = display_df.style.format("{:,}").applymap(color_profit_loss).apply(bold_total_row, axis=1)
            
        st.dataframe(styled_df, use_container_width=True)
        
    with col2:
        st.subheader("📈 플레이어별 누적 금액 변화")
        
        chart_base_df = temp_df[temp_df['sort_key'] > 0].copy()
        
        if not chart_base_df.empty:
            calc_df = chart_base_df.drop(columns=['sort_key', '날짜', '송금상태', 'sheet_row'], errors='ignore').set_index('회차').fillna(0)
            cumulative_df = calc_df.cumsum()
            
            for p in players:
                if p in cumulative_df.columns:
                    if cumulative_df[p].any():
                        first_valid_idx = cumulative_df[p].to_numpy().nonzero()[0][0]
                        if first_valid_idx > 0:
                            cumulative_df.iloc[:first_valid_idx, cumulative_df.columns.get_loc(p)] = np.nan
                    else:
                        cumulative_df[p] = np.nan
            
            chart_df = cumulative_df.copy()
            chart_df['회차_번호'] = chart_base_df['sort_key'].values
            
            melted_df = chart_df.melt(id_vars=['회차_번호'], var_name='플레이어', value_name='누적금액')
            
            # --- 🌟 레이아웃 분리: 상단(그래프) & 하단(체크박스) ---
            chart_container = st.container()
            control_container = st.container()
            
            # 1. 하단 체크박스 그리기 (선택된 데이터 수집)
            with control_container:
                st.markdown("##### 🔍 그래프에 표시할 사람 선택")
                cols = st.columns(len(players))
                selected_players = []
                for i, p in enumerate(players):
                    with cols[i]:
                        if st.checkbox(p, value=True, key=f"filter_{p}"):
                            selected_players.append(p)
            
            # 2. 상단 그래프 그리기
            with chart_container:
                if selected_players:
                    filtered_df = melted_df[melted_df['플레이어'].isin(selected_players)]
                    
                    fixed_colors = alt.Scale(
                        domain=["고", "손", "장", "전", "황", "문"],
                        range=['#5897D8', '#FF6E6E', '#FFC5C5', '#70CDB6', '#AAEFAD', '#A5D6FF']
                    )
                    
                    base = alt.Chart(filtered_df).encode(
                        x=alt.X('회차_번호:Q', 
                                scale=alt.Scale(domainMin=1), 
                                axis=alt.Axis(tickMinStep=1, format='d', title='회차')), 
                        y=alt.Y('누적금액:Q', title='누적 수익 (원)'),
                        color=alt.Color('플레이어:N', scale=fixed_colors, legend=alt.Legend(title="플레이어"))
                    )
                    
                    lines = base.mark_line(size=2.5)
                    visible_points = base.mark_circle(size=60).encode(
                        tooltip=['회차_번호', '플레이어', '누적금액']
                    )
                    
                    chart = (lines + visible_points)
                    st.altair_chart(chart, use_container_width=True)
                else:
                    st.warning("표시할 플레이어를 1명 이상 체크해 주세요.")
            
        else:
            st.info("아직 누적 그래프를 그릴 회차 데이터가 없습니다.")
else:
    st.info("아직 기록된 데이터가 없습니다. 위에서 새 회차를 등록해 보세요.")

st.divider()

st.link_button("📊 원본 구글 시트에서 데이터 확인하기", "https://docs.google.com/spreadsheets/d/1fg8Hkgfb7LQx0AWJ9p9IyvWnuoOzYHqSgx7SdWZp47k/edit?gid=0#gid=0")
