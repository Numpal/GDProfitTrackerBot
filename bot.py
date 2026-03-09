import http.server
import socketserver
import threading
import os
import asyncio
import re  # เพิ่ม re สำหรับดึงข้อมูลจากข้อความ
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

# -------------------------
# 1. Health Check Server
# -------------------------
def run_health_check_server():
    port = int(os.getenv("PORT", 8000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"✅ Health check server started on port {port}")
        httpd.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

# -------------------------
# Configuration
# -------------------------
TH_TZ = ZoneInfo("Asia/Bangkok")
TOKEN = os.getenv("TOKEN")
EXCHANGE_RATE = 35.0
INITIAL_BALANCE = 200.0

DELETE_FAST = 10
DELETE_NORMAL = 10
DELETE_LONG = 10

SHEET_NAME = "CopyTradeTracker"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1dQXfk5wXwC1rnUPYB-SEAG3ySi3ZqNsTT6mRPb-BLfo/edit?usp=sharing"

g_email = os.getenv("G_EMAIL")
g_private_key = os.getenv("G_PRIVATE_KEY")
g_project_id = os.getenv("G_PROJECT_ID")

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

trade_sheet = None
config_sheet = None
balance_sheet = None

thai_months = [
    "มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน",
    "กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"
]

thai_days = [
    "วันจันทร์","วันอังคาร","วันพุธ","วันพฤหัสบดี","วันศุกร์","วันเสาร์","วันอาทิตย์"
]

# -------------------------
# Google Sheet Connection
# -------------------------
try:
    formatted_key = g_private_key.replace("\\n","\n")
    creds_info = {
        "type":"service_account",
        "project_id":g_project_id,
        "private_key":formatted_key,
        "client_email":g_email,
        "token_uri":"https://oauth2.googleapis.com/token",
    }
    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open(SHEET_NAME)

    trade_sheet = spreadsheet.worksheet("trades")
    config_sheet = spreadsheet.worksheet("config")
    
    try:
        balance_sheet = spreadsheet.worksheet("balance_history")
    except:
        balance_sheet = spreadsheet.add_worksheet(title="balance_history", rows="1000", cols="4")
        balance_sheet.append_row(["Timestamp", "Daily Start", "Weekly Start", "Monthly Start"])

    print("✅ Connected Google Sheets (Silent Background Mode)")
except Exception as e:
    print("❌ Google Sheet Error:", e)

# -------------------------
# Balance Logic
# -------------------------

def get_latest_balance(col_index):
    try:
        col_values = balance_sheet.col_values(col_index)
        if len(col_values) <= 1: return INITIAL_BALANCE
        for val in reversed(col_values):
            clean_val = val.replace(',', '').strip()
            if clean_val and clean_val.replace('.','',1).isdigit():
                return float(clean_val)
        return INITIAL_BALANCE
    except:
        return INITIAL_BALANCE

def log_new_balance(daily=None, weekly=None, monthly=None):
    try:
        now_str = datetime.now(TH_TZ).strftime("%Y-%m-%d %H:%M")
        new_row = [now_str, daily, weekly, monthly]
        balance_sheet.append_row(new_row, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"❌ Log Balance Error: {e}")

# -------------------------
# Auto-Recording Logic (NEW)
# -------------------------

def parse_and_record_trade(text, msg_id):
    """วิเคราะห์ข้อความที่มี Emoji และบรรทัดใหม่ เพื่อบันทึกลง Sheet"""
    try:
        if "ปิดออเดอร์" not in text or "กำไร:" not in text:
            return False

        print(f"🔍 วิเคราะห์ข้อความ ID:{msg_id}")

        # 1. Symbol/Side: ข้าม Emoji สีแดง/ฟ้า แล้วดึงชื่อคู่เงินกับ BUY/SELL
        # ใช้ [\w.]+ เพื่อรองรับ XAUUSD.VX และข้ามอักขระพิเศษรอบๆ
        symbol_side_match = re.search(r"([\w.]+)\s*(?:🔴|🔵|🟢|⚪)?\s*(BUY|SELL)", text, re.IGNORECASE)
        
        # 2. Lot: เหมือนเดิม
        lot_match = re.search(r"([\d.]+)\s*lot", text, re.IGNORECASE)
        
        # 3. ราคาเปิด: ใช้ความยืดหยุ่นสูงขึ้นเพื่อข้าม Emoji กราฟ
        open_match = re.search(r"ราคาเปิด:\s*([\d,.]+)", text)
        
        # 4. ราคาปิด: เหมือนกัน
        close_match = re.search(r"ราคาปิด:\s*([\d,.]+)", text)
        
        # 5. กำไร: รองรับทั้งที่มี Emoji ✅ และเครื่องหมาย + -
        profit_match = re.search(r"กำไร:\s*([+-]?[\d,.]+)", text)

        if all([symbol_side_match, lot_match, open_match, close_match, profit_match]):
            row_data = [
                datetime.now(TH_TZ).isoformat(),
                symbol_side_match.group(1).strip(),           # XAUUSD.VX
                symbol_side_match.group(2).strip().upper(),   # SELL
                float(lot_match.group(1)),                    # 0.0098
                float(open_match.group(1).replace(',', '')),
                float(close_match.group(1).replace(',', '')),
                float(profit_match.group(1).replace(',', '')),
                f"ID:{msg_id}"
            ]
            
            trade_sheet.append_row(row_data, value_input_option="USER_ENTERED")
            print(f"✅ บันทึกสำเร็จ! {symbol_side_match.group(1)} {profit_match.group(1)} USD")
            return True
        else:
            # Debug ส่วนที่พลาด
            missing = []
            if not symbol_side_match: missing.append("Symbol/Side")
            if not lot_match: missing.append("Lot")
            if not open_match: missing.append("Open Price")
            if not close_match: missing.append("Close Price")
            if not profit_match: missing.append("Profit")
            print(f"⚠️ Regex พลาดที่ส่วน: {', '.join(missing)}")
            return False
            
    except Exception as e:
        print(f"❌ Error ในการบันทึก: {e}")
    return False

# -------------------------
# Utilities
# -------------------------

def save_chat_id(cid):
    try: config_sheet.update("A1", [[cid]])
    except: pass

def get_chat_id():
    try: return int(config_sheet.acell("A1").value)
    except: return 0

def thai_date_full():
    now = datetime.now(TH_TZ)
    return f"{thai_days[now.weekday()]}ที่ {now.day} {thai_months[now.month-1]} {now.year+543}"

async def delete_message_safe(context, chat_id, message_id, delay=DELETE_NORMAL):
    await asyncio.sleep(delay)
    try: await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except: pass

# -------------------------
# Trade Data Functions
# -------------------------

def read_trades(days):
    try:
        rows = trade_sheet.get_all_values()
        total, count = 0.0, 0
        now = datetime.now(TH_TZ)
        for row in rows[1:]:
            try:
                date = datetime.fromisoformat(row[0])
                if now - date <= timedelta(days=days):
                    total += float(row[6])
                    count += 1
            except: continue
        return total, count
    except: return 0.0, 0

def read_week_trades():
    try:
        rows = trade_sheet.get_all_values()
        now = datetime.now(TH_TZ)
        sunday = (now - timedelta(days=(now.weekday() + 1) % 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        total, count = 0.0, 0
        for row in rows[1:]:
            try:
                date = datetime.fromisoformat(row[0])
                if date >= sunday:
                    total += float(row[6])
                    count += 1
            except: continue
        return total, count
    except: return 0.0, 0

# -------------------------
# Commands
# -------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📊 Copy Trade Tracker\nเลือกเมนูที่ต้องการคำนวณกำไร",
        reply_markup=main_markup
    )

async def calc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        capital = float(context.args[0])
        total_today, _ = read_trades(1)
        master_bal = get_latest_balance(2)
        
        pct = (total_today / master_bal * 100) if master_bal > 0 else 0
        profit_user = (capital * pct) / 100
        thb_user = profit_user * EXCHANGE_RATE

        msg = await update.message.reply_text(
            f"🧮 คำนวณตามทุน {capital:,.2f} USD\n"
            f"กำไรวันนี้ ({pct:,.2f}%): {profit_user:,.2f} USD\n"
            f"≈ {thb_user:,.2f} บาท"
        )
        asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, DELETE_FAST))
        await update.message.delete()
    except: pass

async def tobath_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        usd = float(context.args[0])
        thb = usd * EXCHANGE_RATE
        msg = await update.message.reply_text(f"💰 {usd:,.2f} USD ➜ {thb:,.2f} บาท")
        asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, DELETE_FAST))
        await update.message.delete()
    except: pass

# -------------------------
# Message Handler
# -------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        if not text: return
        chat_id = update.effective_chat.id
        save_chat_id(chat_id)

        # ตรวจจับและบันทึกข้อมูลออเดอร์อัตโนมัติ
        if "ปิดออเดอร์" in text:
            parse_and_record_trade(text, update.message.message_id)
            return

        if text == "📊 กำไรวันนี้":
            total, count = read_trades(1)
            master_bal = get_latest_balance(2)
            pct = (total / master_bal * 100) if master_bal > 0 else 0
            report = f"📊 วันนี้\nไม้: {count}\nกำไร: {total:,.2f} USD ({pct:,.2f}%)"
        elif text == "📅 กำไรสัปดาห์นี้":
            total, count = read_week_trades()
            week_start_bal = get_latest_balance(3)
            pct = (total / week_start_bal * 100) if week_start_bal > 0 else 0
            report = f"📅 สัปดาห์นี้\nไม้: {count}\nกำไรสะสม: {total:,.2f} USD ({pct:,.2f}%)"
        elif text == "📈 กำไร 30 วัน":
            total, count = read_trades(30)
            report = f"📈 30 วัน\nไม้: {count}\nกำไรสะสม: {total:,.2f} USD"
        elif text == "🧮 คำนวณตามทุน":
            await update.message.delete()
            msg = await context.bot.send_message(chat_id=chat_id, text="ใช้คำสั่ง /calc จำนวนทุน\nตัวอย่าง /calc 500")
            asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, DELETE_LONG))
            return
        elif text == "💵 แปลงค่าเงิน":
            await update.message.delete()
            msg = await context.bot.send_message(chat_id=chat_id, text="ใช้คำสั่ง /tobath (ยอดเงิน USD)")
            asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, DELETE_NORMAL))
            return
        elif text == "🔗 ประวัติย้อนหลังทั้งหมด":
            await update.message.delete()
            msg = await context.bot.send_message(chat_id=chat_id, text="📂 เปิดประวัติย้อนหลัง", reply_markup=sheet_inline_keyboard)
            asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, DELETE_NORMAL))
            return
        else: return

        msg = await context.bot.send_message(chat_id=chat_id, text=report)
        asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, DELETE_NORMAL))
        await update.message.delete()
    except: pass

# -------------------------
# Scheduled Jobs
# -------------------------

async def daily_report_and_compound_job(context):
    chat_id = get_chat_id()
    if chat_id:
        total, count = read_trades(1)
        latest_daily = get_latest_balance(2)
        latest_weekly = get_latest_balance(3)
        latest_monthly = get_latest_balance(4)
        
        new_daily = latest_daily + total
        pct = (total / latest_daily * 100) if latest_daily > 0 else 0
        log_new_balance(daily=new_daily, weekly=latest_weekly, monthly=latest_monthly)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📊 สรุปกำไรวันนี้\nไม้: {count}\nกำไร: {total:,.2f} USD ({pct:,.2f}%)"
        )

async def weekly_reset_job(context):
    now = datetime.now(TH_TZ)
    if now.weekday() == 6: 
        latest_monthly = get_latest_balance(4)
        log_new_balance(daily=INITIAL_BALANCE, weekly=INITIAL_BALANCE, monthly=latest_monthly)

async def monthly_reset_job(context):
    now = datetime.now(TH_TZ)
    if now.day == 1:
        latest_daily = get_latest_balance(2)
        latest_weekly = get_latest_balance(3)
        log_new_balance(daily=latest_daily, weekly=latest_weekly, monthly=INITIAL_BALANCE)

async def morning_date_job(context):
    chat_id = get_chat_id()
    if chat_id:
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"📅 {thai_date_full()}"
        )

# -------------------------
# Main Application
# -------------------------

main_keyboard = [
    ["🧮 คำนวณตามทุน","📊 กำไรวันนี้"],
    ["📅 กำไรสัปดาห์นี้","📈 กำไร 30 วัน"],
    ["💵 แปลงค่าเงิน","🔗 ประวัติย้อนหลังทั้งหมด"]
]
main_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
sheet_inline_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="📂 เปิด Google Sheet", url=SHEET_URL)]])

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", start_command))
    app.add_handler(CommandHandler("calc", calc_command))
    app.add_handler(CommandHandler("tobath", tobath_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = app.job_queue
    job_queue.run_daily(morning_date_job, time=time(0, 1, tzinfo=TH_TZ))
    job_queue.run_daily(monthly_reset_job, time=time(23, 56, tzinfo=TH_TZ))
    job_queue.run_daily(daily_report_and_compound_job, time=time(23, 58, tzinfo=TH_TZ))
    job_queue.run_daily(weekly_reset_job, time=time(23, 59, tzinfo=TH_TZ))

    print("🚀 Bot Started | Auto-Recording Mode Active")
    app.run_polling()

if __name__ == "__main__":
    main()
