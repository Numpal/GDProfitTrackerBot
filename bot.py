import re
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import json
import asyncio

import gspread
from google.oauth2.service_account import Credentials

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from telegram.error import TelegramError

TH_TZ = ZoneInfo("Asia/Bangkok")
TOKEN = os.getenv("TOKEN")

# -------------------------
# Google Sheet Setup
# -------------------------
SHEET_NAME = "CopyTradeTracker"
g_email = os.getenv("G_EMAIL")
g_private_key = os.getenv("G_PRIVATE_KEY")
g_project_id = os.getenv("G_PROJECT_ID")

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

trade_sheet = None
config_sheet = None

try:
    if not g_private_key:
        raise Exception("G_PRIVATE_KEY is missing in Railway Variables")

    formatted_key = g_private_key.strip().replace('"', '').replace("'", "").replace("\\n", "\n")
    
    if "-----BEGIN PRIVATE KEY-----" not in formatted_key:
        formatted_key = "-----BEGIN PRIVATE KEY-----\n" + formatted_key
    if "-----END PRIVATE KEY-----" not in formatted_key:
        formatted_key = formatted_key + "\n-----END PRIVATE KEY-----"

    creds_info = {
        "type": "service_account",
        "project_id": g_project_id,
        "private_key": formatted_key,
        "client_email": g_email,
        "token_uri": "https://oauth2.googleapis.com/token",
    }

    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open(SHEET_NAME)
    
    trade_sheet = spreadsheet.worksheet("trades")
    config_sheet = spreadsheet.worksheet("config")
    
    print("✅ Successfully connected to Google Sheets")
except Exception as e:
    print(f"❌ Error during Google Sheets setup: {e}")
    
# -------------------------
# Cache (FAST MODE)
# -------------------------
processed_ids = set()

# -------------------------
# Menu Keyboard
# -------------------------
keyboard = [
    ["📊 กำไรวันนี้"],
    ["📅 กำไรสัปดาห์นี้"],
    ["📈 กำไร 30 วัน"]
]
reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

thai_months = [
    "มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน",
    "กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"
]

# -------------------------
# System Config
# -------------------------
def save_chat_id(cid):
    try:
        if config_sheet:
            config_sheet.update(range_name="A1", values=[[str(cid)]])
    except Exception as e:
        print(f"Save Chat ID Error: {e}")

def get_chat_id():
    try:
        if config_sheet:
            value = config_sheet.acell("A1").value
            if value:
                return int(value)
        return 0
    except:
        return 0

# -------------------------
# Utilities
# -------------------------
def thai_date():
    now = datetime.now(TH_TZ)
    return f"{now.day} {thai_months[now.month-1]} {now.year+543}"

async def delete_message_safe(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 15):
    """ฟังก์ชันลบข้อความหลังจากผ่านไปกี่วินาที (ค่าเริ่มต้น 15 วิ)"""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError as e:
        print(f"⚠️ Could not delete message {message_id}: {e}")

# -------------------------
# Load Existing Trades
# -------------------------
def load_processed_ids():
    global trade_sheet
    try:
        if trade_sheet:
            rows = trade_sheet.col_values(8)
            for r in rows[1:]:
                processed_ids.add(str(r))
            print("Loaded processed ids:", len(processed_ids))
        else:
            print("❌ Cannot load IDs: trade_sheet is not defined")
    except Exception as e:
        print("Load processed id error:", e)

# -------------------------
# Save Trade
# -------------------------
def save_trade(trade, msg_id):
    try:
        if str(msg_id) in processed_ids:
            return

        if trade_sheet:
            trade_sheet.append_row([
                datetime.now(TH_TZ).isoformat(),
                trade["symbol"],
                trade["type"],
                trade["lot"],
                trade["open"],
                trade["close"],
                trade["profit"],
                str(msg_id)
            ])
            processed_ids.add(str(msg_id))
    except Exception as e:
        print("Save trade error:", e)

# -------------------------
# Read Trades
# -------------------------
def read_trades(days):
    try:
        if not trade_sheet: return 0, 0
        rows = trade_sheet.get_all_values()
        total = 0
        count = 0
        now = datetime.now(TH_TZ)

        for row in rows[1:]:
            try:
                date = datetime.fromisoformat(row[0])
                profit = float(row[6])
                if now - date <= timedelta(days=days):
                    total += profit
                    count += 1
            except:
                continue
        return total, count
    except Exception as e:
        print(f"Read trades error: {e}")
        return 0, 0

def read_week_trades():
    try:
        if not trade_sheet: return 0, 0
        rows = trade_sheet.get_all_values()
        now = datetime.now(TH_TZ)
        sunday = now - timedelta(days=(now.weekday()+1)%7)
        sunday = sunday.replace(hour=0, minute=0, second=0, microsecond=0)

        total = 0
        count = 0
        for row in rows[1:]:
            try:
                date = datetime.fromisoformat(row[0])
                profit = float(row[6])
                if date >= sunday:
                    total += profit
                    count += 1
            except:
                continue
        return total, count
    except Exception as e:
        print(f"Read week trades error: {e}")
        return 0, 0

# -------------------------
# Parse CopyTrade Message
# -------------------------
def process_trade(text):
    if "ปิดออเดอร์" not in text:
        return None

    symbol = re.search(r'([A-Z]{3,6}USD\.?[A-Z]*)', text)
    trade_type = re.search(r'\b(BUY|SELL)\b', text)
    lot_match = re.search(r'(\d+\.?\d*)\s*lot', text, re.IGNORECASE)
    open_price = re.search(r'ราคาเปิด[: ]\s*([\d,.]+)', text)
    close_price = re.search(r'ราคาปิด[: ]\s*([\d,.]+)', text)
    profit_match = re.search(r'(กำไร|ขาดทุน)[: ]\s*([+-]?\d+\.?\d*)', text)

    if not profit_match:
        return None

    value = float(profit_match.group(2))
    if profit_match.group(1) == "ขาดทุน":
        value = -abs(value)

    raw_lot = float(lot_match.group(1)) if lot_match else 0
    calculated_lot = raw_lot / 10000

    trade_data = {
        "symbol": symbol.group(1) if symbol else "UNKNOWN",
        "type": trade_type.group(1) if trade_type else "UNKNOWN",
        "lot": calculated_lot,
        "open": float(open_price.group(1).replace(",", "")) if open_price else 0,
        "close": float(close_price.group(1).replace(",", "")) if close_price else 0,
        "profit": value
    }
    return trade_data

# -------------------------
# Menu & Time Check
# -------------------------
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        member = await context.bot.get_chat_member(chat_id, user_id)

        if member.status not in ["administrator", "creator"]:
            return

        save_chat_id(chat_id)
        
        # ลบคำสั่ง /menu ของ user เพื่อความสะอาด
        try: await update.message.delete()
        except: pass

        # ส่งเมนู (ไม่ลบข้อความนี้ เพื่อให้ปุ่มยังคงอยู่)
        await update.message.reply_text(
            "📊 เลือกดูรายการกำไรด้านล่างนี้ครับ:",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        print("Menu error:", e)

async def check_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TH_TZ)
    current_time = now.strftime("%H:%M:%S")
    current_date = thai_date()
    
    try: await update.message.delete()
    except: pass

    msg = await update.message.reply_text(f"🕒 เวลาบอทปัจจุบัน (ไทย):\nวันที่: {current_date}\nเวลา: {current_time}")
    # ลบข้อความบอกเวลาหลังจาก 15 วิ
    asyncio.create_task(delete_message_safe(context, update.effective_chat.id, msg.message_id, 15))

# -------------------------
# Handle Message
# -------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return

        text = update.message.text
        msg_id = update.message.message_id
        chat_id = update.effective_chat.id
        trade = process_trade(text)

        if trade:
            save_trade(trade, msg_id)

        # ถ้ากดปุ่มรายงาน
        if text in ["📊 กำไรวันนี้", "📅 กำไรสัปดาห์นี้", "📈 กำไร 30 วัน"]:
            # 1. ลบข้อความที่ user กดปุ่มทันที
            try: await update.message.delete()
            except: pass

            # 2. เตรียมข้อมูลและส่งรายงาน
            if text == "📊 กำไรวันนี้":
                total, count = read_trades(1)
                report_text = f"📊 วันนี้\nไม้: {count}\nกำไร: {round(total, 2)} USD"
            elif text == "📅 กำไรสัปดาห์นี้":
                total, count = read_week_trades()
                report_text = f"📅 สัปดาห์นี้ (สะสม)\nไม้: {count}\nกำไร: {round(total, 2)} USD"
            elif text == "📈 กำไร 30 วัน":
                total, count = read_trades(30)
                report_text = f"📈 30 วัน\nไม้: {count}\nกำไร: {round(total, 2)} USD"
            
            # ส่งรายงาน
            msg = await update.message.reply_text(report_text)
            # 3. สั่งลบข้อความรายงานหลังจาก 15 วินาที
            asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, 15))

    except Exception as e:
        print("Message error:", e)

# -------------------------
# Auto Reports (ไม่ลบ)
# -------------------------
async def send_thai_date(context):
    chat_id = get_chat_id()
    if chat_id != 0:
        await context.bot.send_message(chat_id=chat_id, text=f"📅 วันนี้\n{thai_date()}")

async def daily_report(context):
    chat_id = get_chat_id()
    if chat_id != 0:
        total, count = read_trades(1)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📊 สรุปวันนี้\nไม้: {count}\nกำไร: {round(total, 2)} USD"
        )

async def weekly_report(context):
    chat_id = get_chat_id()
    if chat_id != 0:
        total, count = read_week_trades()
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📅 กำไรสะสมสัปดาห์นี้\nไม้: {count}\nกำไรสะสม: {round(total, 2)} USD"
        )

# -------------------------
# Main
# -------------------------
def main():
    if TOKEN is None:
        return

    load_processed_ids()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("checktime", check_time))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = app.job_queue
    job_queue.run_daily(send_thai_date, time=time(0, 1, tzinfo=TH_TZ))
    job_queue.run_daily(daily_report, time=time(23, 59, tzinfo=TH_TZ))
    job_queue.run_daily(weekly_report, time=time(23, 59, tzinfo=TH_TZ))

    print("Copy Trade Tracker Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
