import http.server
import socketserver
import threading
import os
import re
import asyncio
import json
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

# 1. สร้าง Web Server เล็กๆ สำหรับ Health Check
def run_health_check_server():
    port = int(os.getenv("PORT", 8000)) 
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"✅ Health check server started on port {port}")
        httpd.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

# -------------------------
# Configuration & Setup
# -------------------------
TH_TZ = ZoneInfo("Asia/Bangkok")
TOKEN = os.getenv("TOKEN")
EXCHANGE_RATE = 35.0  

SHEET_NAME = "CopyTradeTracker"
g_email = os.getenv("G_EMAIL")
g_private_key = os.getenv("G_PRIVATE_KEY")
g_project_id = os.getenv("G_PROJECT_ID")
SHEET_URL = "https://docs.google.com/spreadsheets/d/1dQXfk5wXwC1rnUPYB-SEAG3ySi3ZqNsTT6mRPb-BLfo/edit?usp=sharing"

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

trade_sheet = None
config_sheet = None
processed_ids = set()

thai_months = [
    "มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน",
    "กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"
]

# -------------------------
# Google Sheet Connection
# -------------------------
try:
    if not g_private_key:
        raise Exception("G_PRIVATE_KEY is missing")

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
# Menu Keyboards (เอาปุ่มซ่อนออกถาวร)
# -------------------------
main_keyboard = [
    ["📊 กำไรวันนี้", "📅 กำไรสัปดาห์นี้"],
    ["📈 กำไร 30 วัน", "💵 แปลงค่าเงิน"],
    ["🔗 ประวัติย้อนหลังทั้งหมด"]
]
main_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True, one_time_keyboard=False)

sheet_inline_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton(text="📂 เปิด Google Sheet", url=SHEET_URL)]
])

# -------------------------
# Utilities
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
            return int(value) if value else 0
        return 0
    except: return 0

def thai_date():
    now = datetime.now(TH_TZ)
    return f"{now.day} {thai_months[now.month-1]} {now.year+543}"

async def delete_message_safe(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 15):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except: pass

def load_processed_ids():
    try:
        if trade_sheet:
            rows = trade_sheet.col_values(8)
            for r in rows[1:]:
                processed_ids.add(str(r))
            print(f"Loaded {len(processed_ids)} processed ids")
    except Exception as e:
        print("Load processed id error:", e)

# -------------------------
# Core Functions
# -------------------------
def read_trades(days):
    try:
        if not trade_sheet: return 0, 0
        rows = trade_sheet.get_all_values()
        total, count, now = 0, 0, datetime.now(TH_TZ)
        for row in rows[1:]:
            try:
                date = datetime.fromisoformat(row[0])
                if now - date <= timedelta(days=days):
                    total += float(row[6])
                    count += 1
            except: continue
        return total, count
    except: return 0, 0

def read_week_trades():
    try:
        if not trade_sheet: return 0, 0
        rows = trade_sheet.get_all_values()
        now = datetime.now(TH_TZ)
        sunday = (now - timedelta(days=(now.weekday()+1)%7)).replace(hour=0, minute=0, second=0, microsecond=0)
        total, count = 0, 0
        for row in rows[1:]:
            try:
                date = datetime.fromisoformat(row[0])
                if date >= sunday:
                    total += float(row[6])
                    count += 1
            except: continue
        return total, count
    except: return 0, 0

def process_trade(text):
    if "ปิดออเดอร์" not in text: return None
    symbol = re.search(r'([A-Z]{3,6}USD\.?[A-Z]*)', text)
    trade_type = re.search(r'\b(BUY|SELL)\b', text)
    lot_match = re.search(r'(\d+\.?\d*)\s*lot', text, re.IGNORECASE)
    open_price = re.search(r'ราคาเปิด[: ]\s*([\d,.]+)', text)
    close_price = re.search(r'ราคาปิด[: ]\s*([\d,.]+)', text)
    profit_match = re.search(r'(กำไร|ขาดทุน)[: ]\s*([+-]?\d+\.?\d*)', text)
    
    if not profit_match: return None
    value = float(profit_match.group(2))
    if profit_match.group(1) == "ขาดทุน": value = -abs(value)
    raw_lot = float(lot_match.group(1)) if lot_match else 0
    
    return {
        "symbol": symbol.group(1) if symbol else "UNKNOWN",
        "type": trade_type.group(1) if trade_type else "UNKNOWN",
        "lot": raw_lot / 10000,
        "open": float(open_price.group(1).replace(",", "")) if open_price else 0,
        "close": float(close_price.group(1).replace(",", "")) if close_price else 0,
        "profit": value
    }

# -------------------------
# Command Handlers
# -------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    msg = await update.message.reply_text("🚀 Copy Trade Tracker พร้อมทำงาน!", reply_markup=main_markup)
    asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, 15))
    try: await update.message.delete()
    except: pass

async def tobath_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_msg_id = update.message.message_id
    try:
        if not context.args:
            msg = await update.message.reply_text("💡 วิธีใช้: `/tobath [ตัวเลข]`", parse_mode="Markdown")
            asyncio.create_task(delete_message_safe(context, chat_id, user_msg_id, 15))
            asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, 15))
            return

        usd = float(context.args[0].replace(",", ""))
        thb = usd * EXCHANGE_RATE
        text = (
            f"💰 **แปลงค่าเงินสำเร็จ**\n"
            f"━━━━━━━━━━━━━━\n"
            f"💵 {usd:,.2f} USD\n"
            f"➡️ {thb:,.2f} บาท\n"
            f"━━━━━━━━━━━━━━\n"
            f"เรท: 1 USD = {EXCHANGE_RATE} บาท"
        )
        msg = await update.message.reply_text(text, parse_mode="Markdown")
        asyncio.create_task(delete_message_safe(context, chat_id, user_msg_id, 15))
        asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, 15))
    except ValueError:
        msg = await update.message.reply_text("❌ กรุณากรอกเป็นตัวเลขเท่านั้น")
        asyncio.create_task(delete_message_safe(context, chat_id, user_msg_id, 15))
        asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, 15))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text: return
        text = update.message.text
        msg_id = update.message.message_id
        chat_id = update.effective_chat.id
        
        save_chat_id(chat_id)

        # 1. ตรวจสอบข้อมูลเทรด
        trade = process_trade(text)
        if trade:
            if str(msg_id) not in processed_ids and trade_sheet:
                trade_sheet.append_row([
                    datetime.now(TH_TZ).isoformat(),
                    trade["symbol"], trade["type"], trade["lot"],
                    trade["open"], trade["close"], trade["profit"], str(msg_id)
                ])
                processed_ids.add(str(msg_id))
            return

        # 2. ตรวจสอบการกดปุ่มเมนู
        menu_buttons = ["📊 กำไรวันนี้", "📅 กำไรสัปดาห์นี้", "📈 กำไร 30 วัน", "🔗 ประวัติย้อนหลังทั้งหมด", "💵 แปลงค่าเงิน"]
        
        if text in menu_buttons:
            try: await update.message.delete()
            except: pass

            if text == "💵 แปลงค่าเงิน":
                msg = await context.bot.send_message(chat_id=chat_id, text="💡 พิมพ์ `/tobath [ตัวเลข]` เพื่อแปลงเงินครับ\nตัวอย่าง: `/tobath 100`", parse_mode="Markdown")
                asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, 15))
                return

            if text == "📊 กำไรวันนี้":
                total, count = read_trades(1)
                report = f"📊 วันนี้\nไม้: {count}\nกำไร: {round(total, 2)} USD"
            elif text == "📅 กำไรสัปดาห์นี้":
                total, count = read_week_trades()
                report = f"📅 สัปดาห์นี้ (สะสม)\nไม้: {count}\nกำไร: {round(total, 2)} USD"
            elif text == "📈 กำไร 30 วัน":
                total, count = read_trades(30)
                report = f"📈 30 วัน\nไม้: {count}\nกำไร: {round(total, 2)} USD"
            elif text == "🔗 ประวัติย้อนหลังทั้งหมด":
                msg = await context.bot.send_message(chat_id=chat_id, text="📑 ลิงก์ดูประวัติการเทรดทั้งหมด:", reply_markup=sheet_inline_keyboard)
                asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, 15))
                return

            msg = await context.bot.send_message(chat_id=chat_id, text=report)
            asyncio.create_task(delete_message_safe(context, chat_id, msg.message_id, 15))

    except Exception as e: print("Handle error:", e)

# -------------------------
# Auto Reports
# -------------------------
async def daily_report_job(context):
    chat_id = get_chat_id()
    if chat_id:
        total, count = read_trades(1)
        await context.bot.send_message(chat_id=chat_id, text=f"📊 สรุปวันนี้\nไม้: {count}\nกำไร: {round(total, 2)} USD")

async def weekly_report_job(context):
    chat_id = get_chat_id()
    if chat_id:
        total, count = read_week_trades()
        await context.bot.send_message(chat_id=chat_id, text=f"📅 กำไรสะสมสัปดาห์นี้\nไม้: {count}\nกำไรสะสม: {round(total, 2)} USD")

# -------------------------
# Main Application
# -------------------------
def main():
    if not TOKEN:
        print("❌ TOKEN is missing!")
        return

    load_processed_ids()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", start_command))
    app.add_handler(CommandHandler("tobath", tobath_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = app.job_queue
    job_queue.run_daily(daily_report_job, time=time(23, 59, tzinfo=TH_TZ))
    job_queue.run_daily(weekly_report_job, time=time(23, 59, tzinfo=TH_TZ))

    print("🚀 Copy Trade Tracker Started (Static Menu Mode)...")
    app.run_polling()

if __name__ == "__main__":
    main()
